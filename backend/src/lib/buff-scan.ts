import { spawn } from 'node:child_process';
import { AppError } from './core.js';

let scanning = false;

export async function requireBuffPosts(targetName: string): Promise<void> {
  if (!process.env.BUFF_SCAN_ACCOUNTS) throw new AppError(503, 'SCAN_UNAVAILABLE', 'Chưa cấu hình tài khoản quét bài');
  if (scanning) throw new AppError(409, 'SCAN_BUSY', 'Đang quét bài cho đơn khác, vui lòng thử lại sau');
  scanning = true;
  try {
    const status = await new Promise<string>((resolve) => {
      const child = spawn('python3', ['scanner/scan.py'], { stdio: ['pipe', 'pipe', 'ignore'] });
      let output = '';
      const timer = setTimeout(() => child.kill('SIGKILL'), 75_000);
      child.stdout.on('data', chunk => {
        output += String(chunk);
        if (output.length > 8192) child.kill('SIGKILL');
      });
      child.stdin.on('error', () => {});
      child.on('error', () => { clearTimeout(timer); resolve('unavailable'); });
      child.on('close', code => {
        clearTimeout(timer);
        try {
          const result = JSON.parse(output);
          resolve(code === 0 && (result.status !== 'found' || (Number.isInteger(result.postCount) && result.postCount > 0)) ? result.status : 'unavailable');
        } catch { resolve('unavailable'); }
      });
      child.stdin.end(JSON.stringify({ targetName }) + '\n');
    });
    if (status === 'no_posts') throw new AppError(400, 'BUFF_NO_POSTS', 'Nhân vật chưa có bài đăng để buff like. Đơn chưa được tạo, chưa trừ tiền.');
    if (status !== 'found') throw new AppError(503, 'SCAN_UNAVAILABLE', 'Chưa quét được bài của nhân vật. Vui lòng kiểm tra tên và thử lại; đơn chưa được tạo, chưa trừ tiền.');
  } finally { scanning = false; }
}
