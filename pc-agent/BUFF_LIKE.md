# chaysk.com — Buff Like PC (engine bản 4)

## Backend

Apply `backend/src/db/buff_like.sql` to PostgreSQL before starting this version.
This additive table retains claims permanently; no automatic reassignment on timeout.
Build backend with `npm run build`. Existing admin JWT authentication protects
`/api/v1/admin/buff-like/{claim,report,jobs}`. Customer progress is available at
`/api/v1/buff-like/jobs` and scoped to the authenticated owner.

## Web

Admin → Products → create a **Buff Like (PC)** product. Set price and likes per
package. Customers visit `/buff-like`, enter exact character name and package
quantity. The server snapshots the quota and charges the wallet in the same
transaction as the queue insert. No Chung Suc provider/outbox is used.

## Windows PC

1. Open `AutoBuffDoHot_Khach.exe (4)/AutoBuffDoHot_Khach.exe` yourself, activate
   normally and load your accounts. Use its moments API port (usually 18801).
2. Install Python 3; no third-party Python package is required.
3. Run:

   ```powershell
   python buff_like.py --backend https://api.chaysk.com --port 18801
   ```

4. Enter shop admin email/password at the prompts (password stays in memory).
5. Leave the receiver and engine open. It polls every 5 seconds and submits
   `{target_name, amount}` to `/api/order`, then polls `/api/order/{id}`.

The backend HTTPS certificate must be valid; TLS verification is never disabled.
Progress comes from engine `added_likes`; completion requires engine `DONE` and
the full quota. It is an engine report, not an independent game-side measurement.

## Recovery

Journal: `%LOCALAPPDATA%/ChaySKBuffLike/state.json`. Keep this file; never delete
it to retry a bill. The local OS lock permits only one receiver per journal.
Server claims also prevent another PC taking an unresolved order.

Network failure replays the same claim/report. An engine POST whose result is
unknown is NOT retried: inspect engine and journal before resolving it. A stopped
engine with incomplete quota is `needs_review` and blocks the next claim.
No automatic refund or restart. Operator reconciliation/release for review jobs
is not included in this first version. Do not manually refund/change a running
order until the engine has stopped. Ctrl+C closes the receiver, not the engine.

No real engine order is created by builds or automated tests.
