# Buff-like post validation

Read-only protocol modules copied from the supplied AutoBuffDoHot_Khach.exe/backend_native source project. The entrypoint authenticates a dedicated source, resolves the exact submitted character name and queries its first feed page. It sends no likes and creates no engine orders.

Runtime: Python 3, cryptography and liblz4 (installed in the backend image).
Set BUFF_SCAN_ACCOUNTS on the server to a JSON array of username/password objects. Never commit actual credentials. Two sources are tried in order on failures; concurrent scans are rejected to avoid concurrent source logins. Checkout fails closed on timeout, malformed response, unknown target or unavailable scanner. An authenticated empty feed page blocks checkout as BUFF_NO_POSTS.
