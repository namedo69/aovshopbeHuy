import { Router } from 'express';
import { z } from 'zod';
import { sqlClient } from '../db/sql.js';
import { AppError, parse, requireAdmin, requireUser } from '../lib/core.js';

// Separate from Chung Suc's outbox: a claimed engine job must never be
// automatically reassigned or submitted again after a network timeout.
export const buffLikeRouter = Router();
export const buffLikeCustomerRouter = Router();
buffLikeCustomerRouter.use(requireUser);
buffLikeCustomerRouter.get('/jobs', async (req, res) => {
  const result = await sqlClient.query(`SELECT b.order_id,b.target_name,b.requested,b.done,b.state,
    b.updated_at,o.order_code,o.status FROM buff_like_jobs b JOIN orders o ON o.id=b.order_id
    WHERE o.user_id=$1 ORDER BY b.created_at DESC LIMIT 100`, [req.user!.id]);
  res.json(result.rows);
});
buffLikeRouter.use(requireUser, requireAdmin);
const owner = z.object({ deviceId: z.uuid(), claimToken: z.uuid() });

export function buffLikeInput(schema: Record<string, any>, input: Record<string, unknown>, quantity: number) {
  const targetName = parse(z.string().trim().min(1).max(100), input.targetName);
  const likesPerItem = parse(z.number().int().min(1).max(1_000_000), schema.likesPerItem);
  const requested = likesPerItem * quantity;
  if (!Number.isSafeInteger(requested) || requested > 1_000_000) {
    throw new AppError(400, 'INVALID_LIKE_QUANTITY', 'Mỗi đơn tối đa 1.000.000 like');
  }
  return { productType: 'buff_like', targetName, requested };
}

buffLikeRouter.post('/claim', async (req, res) => {
  const data = parse(owner, req.body);
  const client = await sqlClient.connect();
  try {
    await client.query('BEGIN');
    // Serialize claims while allowing up to ten owned jobs per PC.
    await client.query('SELECT pg_advisory_xact_lock(741026, 18801)');
    const replay = await client.query('SELECT * FROM buff_like_jobs WHERE claim_token=$1', [data.claimToken]);
    if (replay.rows[0]) {
      const row = replay.rows[0];
      if (row.device_id !== data.deviceId || row.admin_id !== req.user!.id) throw new AppError(409, 'CLAIM_CONFLICT', 'Đơn thuộc phiên PC khác');
      await client.query('COMMIT');
      res.json({ job: row });
      return;
    }
    const busy = await client.query(`SELECT 1 FROM buff_like_jobs b JOIN orders o ON o.id=b.order_id
      WHERE b.device_id=$1 AND b.state IN ('claimed','running','needs_review') AND o.status='processing'
      HAVING count(*) >= 10`, [data.deviceId]);
    if (busy.rows.length) {
      await client.query('COMMIT');
      res.json({ job: null });
      return;
    }
    const next = await client.query(`SELECT b.* FROM buff_like_jobs b JOIN orders o ON o.id=b.order_id
      WHERE b.state='queued' AND o.status='queued' ORDER BY b.created_at, b.order_id
      LIMIT 1 FOR UPDATE OF b,o`);
    if (!next.rows[0]) {
      await client.query('COMMIT');
      res.json({ job: null });
      return;
    }
    const result = await client.query(`UPDATE buff_like_jobs SET state='claimed', device_id=$2,
      claim_token=$3, admin_id=$4, updated_at=now() WHERE order_id=$1 RETURNING *`,
    [next.rows[0].order_id, data.deviceId, data.claimToken, req.user!.id]);
    await client.query("UPDATE orders SET status='processing', updated_at=now() WHERE id=$1", [next.rows[0].order_id]);
    await client.query("INSERT INTO order_status_logs(order_id,from_status,to_status,actor_type,reason) VALUES($1,'queued','processing','system','Buff like PC claimed')", [next.rows[0].order_id]);
    await client.query('COMMIT');
    res.json({ job: result.rows[0] });
  } catch (error) {
    await client.query('ROLLBACK');
    throw error;
  } finally { client.release(); }
});

buffLikeRouter.post('/report', async (req, res) => {
  const data = parse(owner.extend({
    orderId: z.uuid(), engineOrderId: z.string().max(200),
    state: z.enum(['running', 'completed', 'needs_review']),
    done: z.number().int().min(0).max(1_000_000), engineStopped: z.boolean(),
  }), req.body);
  const client = await sqlClient.connect();
  try {
    await client.query('BEGIN');
    const result = await client.query(`SELECT b.*, o.status AS order_status FROM buff_like_jobs b
      JOIN orders o ON o.id=b.order_id WHERE b.order_id=$1 FOR UPDATE OF b,o`, [data.orderId]);
    const row = result.rows[0];
    if (!row || row.admin_id !== req.user!.id || row.device_id !== data.deviceId || row.claim_token !== data.claimToken) {
      throw new AppError(409, 'CLAIM_CONFLICT', 'PC không sở hữu đơn này');
    }
    if (['refunded', 'cancelled'].includes(row.order_status)) {
      await client.query('COMMIT');
      res.json({ ok: true, closed: true, orderStatus: row.order_status });
      return;
    }
    if (data.done < row.done || data.done > row.requested ||
        (row.engine_order_id && row.engine_order_id !== data.engineOrderId) ||
        (data.state === 'completed' && (!data.engineStopped || data.done !== row.requested || !data.engineOrderId)) ||
        (data.state === 'running' && (data.engineStopped || !data.engineOrderId)) ||
        (row.state === 'needs_review' && data.state === 'running') ||
        (row.state === 'completed' && data.state !== 'completed')) {
      throw new AppError(409, 'INVALID_PROGRESS', 'Tiến độ hoặc trạng thái engine không hợp lệ');
    }
    if (!['processing','completed'].includes(row.order_status) || (row.order_status === 'completed' && row.state !== 'completed')) {
      throw new AppError(409, 'ORDER_CLOSED', 'Đơn đã được quản trị thay đổi; dừng engine và kiểm tra');
    }
    await client.query(`UPDATE buff_like_jobs SET state=$2, done=$3, engine_order_id=$4,
      engine_stopped=$5, updated_at=now() WHERE order_id=$1`,
    [data.orderId, data.state, data.done, data.engineOrderId || null, data.engineStopped]);
    if (data.state === 'completed' && row.state !== 'completed') {
      await client.query("UPDATE orders SET status='completed',completed_at=now(),updated_at=now() WHERE id=$1", [data.orderId]);
      await client.query("INSERT INTO order_status_logs(order_id,from_status,to_status,actor_type,reason) VALUES($1,'processing','completed','system','Buff like engine DONE, full quota')", [data.orderId]);
    }
    await client.query('COMMIT');
    res.json({ ok: true });
  } catch (error) {
    await client.query('ROLLBACK');
    throw error;
  } finally { client.release(); }
});

buffLikeRouter.get('/jobs', async (_req, res) => {
  const result = await sqlClient.query(`SELECT b.order_id,b.target_name,b.requested,b.done,b.state,
    b.engine_stopped,b.updated_at,o.order_code FROM buff_like_jobs b JOIN orders o ON o.id=b.order_id
    ORDER BY b.created_at DESC LIMIT 100`);
  res.json(result.rows);
});
