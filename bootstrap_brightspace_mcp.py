#!/usr/bin/env python3
import os, sys, json, time, threading, http.server, socketserver, webbrowser, fcntl
import urllib.request, urllib.parse, urllib.error, subprocess, tempfile

# ====== CONFIG ======
CLIENT_ID     = os.getenv("BS_CLIENT_ID",     "your_client_id")
CLIENT_SECRET = os.getenv("BS_CLIENT_SECRET", "your_client_secret")
BS_BASE_URL   = os.getenv("BS_BASE_URL",      "https://your.brightspace.host")
AUTH_HOST     = os.getenv("BS_AUTH_HOST",     "https://auth.brightspace.com")
SCOPE         = os.getenv("BS_SCOPE",         "core:*:* data:*:*")
CALLBACK_PORT = int(os.getenv("BS_CALLBACK_PORT", "53682"))
TOKENS_PATH   = os.getenv("TOKENS_PATH", "tokens.json")
LOCK_PATH     = ".tokens.lock"
MCP_BIN       = os.getenv("MCP_BIN", "")
MCP_CMD       = [sys.executable, "-m", "brightspace_mcp.main", "--stdio"]
STATE         = "xyz"
# =======================================

def die(msg): print(msg, file=sys.stderr); sys.exit(1)
def pkill_safe(pattern): subprocess.run(["pkill","-f",pattern], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def wait_http_200(url, timeout=20):
    t0=time.time()
    while time.time()-t0 < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                return r.read()
        except Exception:
            time.sleep(0.5)
    return None

def http_post_form(url, data_dict, timeout=15):
    data = urllib.parse.urlencode(data_dict).encode()
    req  = urllib.request.Request(url, data=data, headers={"Content-Type":"application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def write_atomic(path, content_bytes):
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp_tokens_")
    with os.fdopen(fd, "wb") as f: f.write(content_bytes)
    os.replace(tmp, path)

def get_ngrok_https():
    data = wait_http_200("http://127.0.0.1:4040/api/tunnels", timeout=30)
    if not data: return None
    j = json.loads(data.decode())
    for t in j.get("tunnels", []):
        pub = t.get("public_url","")
        if pub.startswith("https://"): return pub
    return None

def start_ngrok():
    pkill_safe("ngrok")
    p = subprocess.Popen(["ngrok","http",str(CALLBACK_PORT)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url=None
    for _ in range(60):
        url = get_ngrok_https()
        if url: break
        time.sleep(0.5)
    if not url: die("ngrok did not expose https tunnel on 4040")
    return p, url

class CodeHolder:
    def __init__(self): self.code=None; self.ev=threading.Event()
holder = CodeHolder()  # global used by handler

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        u = urllib.parse.urlparse(self.path); q = dict(urllib.parse.parse_qsl(u.query))
        code = q.get("code")
        self.send_response(200); self.end_headers()
        self.wfile.write(b"OK. You can close this tab.")
        if code and not holder.code:
            holder.code = code
            holder.ev.set()
    def log_message(self,*a,**k): pass

def wait_auth_code(timeout=180):
    with socketserver.TCPServer(("127.0.0.1", CALLBACK_PORT), H) as httpd:
        th = threading.Thread(target=httpd.serve_forever, daemon=True); th.start()
        got = holder.ev.wait(timeout)
        httpd.shutdown()
        return holder.code if got else None

def authorize_flow(redirect_uri):
    qs = urllib.parse.urlencode({
        "response_type":"code",
        "client_id": CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": SCOPE,
        "state": STATE,
        "prompt":"consent"
    }, quote_via=urllib.parse.quote)
    auth_url = f"{AUTH_HOST}/oauth2/auth?{qs}"
    print("Authorize URL:\n", auth_url, "\n", flush=True)
    try: webbrowser.open(auth_url)
    except Exception: pass
    code = wait_auth_code()
    if not code: die("No auth code received. Check Redirect URI and try again.")
    print("Auth code received.", flush=True)
    body = {
        "grant_type":"authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    try:
        tok = http_post_form(f"{AUTH_HOST}/core/connect/token", body)
    except urllib.error.HTTPError as e:
        die(f"Token exchange failed: {e.read().decode()}")
    j = json.loads(tok.decode())
    if "access_token" not in j or "refresh_token" not in j:
        die(f"Token response missing fields: {j}")
    write_atomic(TOKENS_PATH, tok)
    try: os.chmod(TOKENS_PATH, 0o600)
    except Exception: pass
    print("tokens.json written.", flush=True)
    return j

def jsonrpc_send(p, obj):
    p.stdin.write(json.dumps(obj) + "\n"); p.stdin.flush()

def jsonrpc_recv_until(p, want_id=None, timeout=20):
    t0=time.time()
    while time.time()-t0 < timeout:
        line = p.stdout.readline()
        if not line: break
        line=line.strip()
        print(line, flush=True)
        if not want_id: continue
        try:
            o=json.loads(line)
            if o.get("id")==want_id:
                return o
        except Exception:
            pass
    return None

def start_mcp(tokens):
    lf = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        die("Another MCP instance holds lock. Abort.")
    # Prefer portable module invocation if MCP_BIN not provided or invalid
    use_cmd = None
    if MCP_BIN and os.path.exists(MCP_BIN):
        use_cmd = [MCP_BIN, "--stdio"]
    else:
        use_cmd = MCP_CMD
    env = os.environ.copy()
    env["BS_BASE_URL"]      = BS_BASE_URL
    env["BS_CLIENT_ID"]     = CLIENT_ID
    env["BS_CLIENT_SECRET"] = CLIENT_SECRET
    env["BS_REFRESH_TOKEN"] = tokens["refresh_token"]
    p = subprocess.Popen(use_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    return p, lf

def mcp_handshake_and_test(p):
    jsonrpc_send(p, {"jsonrpc":"2.0","id":"init","method":"initialize",
                     "params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"bootstrap","version":"1.0"}}})
    jsonrpc_recv_until(p, "init")
    jsonrpc_send(p, {"jsonrpc":"2.0","method":"notifications/initialized"})
    jsonrpc_send(p, {"jsonrpc":"2.0","id":"who","method":"tools/call",
                     "params":{"name":"bs.whoami","arguments":{}}})
    resp = jsonrpc_recv_until(p, "who", timeout=30)
    if not resp: die("No response to whoami.")
    if resp.get("result",{}).get("isError"):
        die(f"whoami error: {resp['result']}")
    print("\nMCP whoami OK.\n", flush=True)

def pump_stdio(p):
    try:
        for line in sys.stdin:
            p.stdin.write(line); p.stdin.flush()
    except BrokenPipeError:
        pass
    p.wait()

if __name__=="__main__":
    # 0) clean slate
    pkill_safe("run_brightspace_mcp_locked.py")
    pkill_safe("brightspace-mcp")
    pkill_safe("brightspace_oauth_ngrok.sh")

    # 1) start ngrok and set redirect
    print("Starting ngrok...", flush=True)
    ngrok_proc, public = start_ngrok()
    redirect_uri = f"{public}/callback"
    print(f"Redirect URI = {redirect_uri}\n", flush=True)
    input("ACTION: In Brightspace Admin > Manage OAuth 2.0 > your app, set Redirect URI to EXACTLY the above value and Save. Press Enter when done...")

    # 2) authorize and write tokens.json
    holder = CodeHolder()  # fresh holder
    tokens = authorize_flow(redirect_uri)

    # 3) direct sanity call
    try:
        req = urllib.request.Request(f"{BS_BASE_URL}/d2l/api/lp/1.50/users/whoami", headers={"Authorization": f"Bearer {tokens['access_token']}"})
        with urllib.request.urlopen(req, timeout=10) as r:
            who = json.loads(r.read().decode())
        print("Direct whoami:", who, "\n", flush=True)
    except Exception as e:
        print("Direct whoami failed (will rely on MCP refresh):", e, flush=True)

    # 4) stop ngrok
    try: ngrok_proc.terminate()
    except Exception: pass

    # 5) start MCP with lock and test
    print("Starting MCP with lock...", flush=True)
    mcp, lockfile = start_mcp(tokens)
    try:
        mcp_handshake_and_test(mcp)
        print("MCP is running. You can now send JSON-RPC lines here, or attach your agent.", flush=True)
        pump_stdio(mcp)
    finally:
        try: fcntl.flock(lockfile.fileno(), fcntl.LOCK_UN)
        except Exception: pass
