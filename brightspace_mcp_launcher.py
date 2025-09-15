#!/usr/bin/env python3
import os, sys, json, ssl, http.server, socketserver, threading, time, tempfile, subprocess, webbrowser
from urllib.parse import urlencode, urlparse, parse_qsl, quote
from urllib.request import urlopen, Request
# ---- Config ----
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

CLIENT_ID     = os.getenv("BS_CLIENT_ID", "your_client_id")
CLIENT_SECRET = os.getenv("BS_CLIENT_SECRET", "your_client_secret")
AUTH_HOST     = os.getenv("BS_AUTH_HOST", "https://auth.brightspace.com")
BS_BASE_URL   = os.getenv("BS_BASE_URL", "https://your.brightspace.host")
SCOPE         = os.getenv("BS_SCOPE", "core:*:* data:*:*")
CALLBACK_HOST = os.getenv("BS_CALLBACK_HOST", "127.0.0.1")
CALLBACK_PORT = int(os.getenv("BS_CALLBACK_PORT", "53682"))
REDIRECT_URI  = os.getenv("BS_REDIRECT_URI", f"https://localhost:{CALLBACK_PORT}/callback")
TOKENS_FILE   = os.getenv("BS_TOKENS_FILE", "tokens.json")
LOCK_FILE     = os.getenv("BS_TOKENS_LOCK", ".tokens.lock")
# Prefer invoking the installed module via current Python for portability
MCP_CMD       = [sys.executable, "-m", "brightspace_mcp.main", "--stdio"]
# -------------- helpers --------------
def write_atomic(path: str, data: bytes):
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp_tokens_")
    with os.fdopen(fd, "wb") as f: f.write(data)
    os.replace(tmp, path)
def http_post_form(url: str, form: dict, timeout=20):
    b = urlencode(form).encode()
    req = Request(url, data=b, headers={"Content-Type":"application/x-www-form-urlencoded"})
    with urlopen(req, timeout=timeout) as r: return r.read()
def try_refresh(tokens_path: str):
    if not os.path.exists(tokens_path): return False
    try:
        j = json.load(open(tokens_path))
        rt = j.get("refresh_token")
        if not rt: return False
        resp = http_post_form(f"{AUTH_HOST}/core/connect/token", {
            "grant_type":"refresh_token",
            "refresh_token": rt,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET
        })
        jr = json.loads(resp.decode())
        if "access_token" in jr and "refresh_token" in jr:
            write_atomic(tokens_path, resp)
            try: os.chmod(tokens_path, 0o600)
            except: pass
            return True
        return False
    except Exception:
        return False
# ---- HTTPS callback with self-signed cert ----
CRT="localhost.crt"; KEY="localhost.key"
def ensure_self_signed():
    if os.path.exists(CRT) and os.path.exists(KEY): return
    # openssl-only, no sudo needed
    cmd = ["openssl","req","-x509","-newkey","rsa:2048","-nodes",
           "-keyout", KEY, "-out", CRT, "-days","365","-subj","/CN=localhost"]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
class CodeHolder: code=None
class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        q = dict(parse_qsl(urlparse(self.path).query))
        self.send_response(200); self.end_headers()
        self.wfile.write(b"OK. You can close this tab.")
        if "code" in q and not CodeHolder.code: CodeHolder.code = q["code"]
    def log_message(self, *a, **k): pass
def get_code_via_https():
    ensure_self_signed()
    httpd = socketserver.TCPServer((CALLBACK_HOST, CALLBACK_PORT), CallbackHandler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=CRT, keyfile=KEY)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    # Build authorize URL
    auth_qs = urlencode({
        "response_type":"code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "state":"xyz",
        "prompt":"consent"
    }, quote_via=lambda s, *_: quote(s, safe=""))
    auth_url = f"{AUTH_HOST}/oauth2/auth?{auth_qs}"
    print("\nACTION: Confirm your Brightspace OAuth app Redirect URI is exactly:")
    print(f"  {REDIRECT_URI}\n")
    print("Opening consent URL...")
    try: webbrowser.open(auth_url)
    except: print(auth_url)
    # wait for code
    t0=time.time()
    while time.time()-t0 < 300 and not CodeHolder.code: time.sleep(0.2)
    httpd.shutdown()
    return CodeHolder.code
def mint_tokens():
    code = get_code_via_https()
    if not code:
        print("No auth code captured.", file=sys.stderr); sys.exit(1)
    tok = http_post_form(f"{AUTH_HOST}/core/connect/token", {
        "grant_type":"authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    })
    j = json.loads(tok.decode())
    if "refresh_token" not in j:
        print("Token exchange failed: no refresh_token.", file=sys.stderr); sys.exit(1)
    write_atomic(TOKENS_FILE, tok)
    try: os.chmod(TOKENS_FILE, 0o600)
    except: pass
    print("tokens.json written.")
# ---- lock + spawn MCP and bridge stdio ----
def run_locked_mcp():
    import fcntl
    lf = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Another Brightspace MCP is running (lock held).", file=sys.stderr); sys.exit(1)
    env = os.environ.copy()
    env["BS_BASE_URL"]      = BS_BASE_URL
    env["BS_CLIENT_ID"]     = CLIENT_ID
    env["BS_CLIENT_SECRET"] = CLIENT_SECRET
    env["BS_REFRESH_TOKEN"] = json.load(open(TOKENS_FILE))["refresh_token"]
    p = subprocess.Popen(MCP_CMD, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, env=env)
    # bridge stdio
    def pump(src, dst):
        for line in iter(src.readline, ''):
            dst.write(line); dst.flush()
    import threading
    threading.Thread(target=pump, args=(p.stdout, sys.stdout), daemon=True).start()
    threading.Thread(target=pump, args=(p.stderr, sys.stderr), daemon=True).start()
    try:
        for line in sys.stdin:
            p.stdin.write(line); p.stdin.flush()
    except BrokenPipeError:
        pass
    p.wait()
# ---- main ----
# Try to refresh if tokens exist; else run full mint.
ok = try_refresh(TOKENS_FILE)
if not ok:
    print("No valid refresh token found. Starting local HTTPS auth...")
    mint_tokens()
# Quick direct sanity call using the fresh access token
try:
    at = json.load(open(TOKENS_FILE))["access_token"]
    req = Request(f"{BS_BASE_URL}/d2l/api/lp/1.50/users/whoami", headers={"Authorization": f"Bearer {at}"})
    with urlopen(req, timeout=10) as r: 
        print("Direct whoami:", r.read().decode()[:160], "...")
except Exception as e:
    print("Direct whoami skipped:", e)
# Now hand over to MCP with lock, bridged stdio
run_locked_mcp()
