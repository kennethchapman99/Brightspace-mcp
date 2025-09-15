#!/usr/bin/env python3
import os, sys, json, time, threading, http.server, socketserver, webbrowser
import urllib.request, urllib.parse, urllib.error, subprocess, tempfile
try:
  from dotenv import load_dotenv
  load_dotenv()
except Exception:
  pass
CLIENT_ID=os.getenv("BS_CLIENT_ID","your_client_id")
CLIENT_SECRET=os.getenv("BS_CLIENT_SECRET","your_client_secret")
AUTH_HOST=os.getenv("BS_AUTH_HOST","https://auth.brightspace.com")
SCOPE=os.getenv("BS_SCOPE","core:*:* data:*:*")
CALLBACK_PORT=int(os.getenv("BS_CALLBACK_PORT","53682"))
def wait_http_200(url, timeout=30):
  t0=time.time()
  while time.time()-t0<timeout:
    try: 
      with urllib.request.urlopen(url,timeout=2) as r: return r.read()
    except: time.sleep(0.5)
  return None
def get_ngrok_https():
  d=wait_http_200("http://127.0.0.1:4040/api/tunnels",30)
  if not d: return None
  j=json.loads(d.decode())
  for t in j.get("tunnels",[]):
    if t.get("public_url","").startswith("https://"): return t["public_url"]
  return None
def start_ngrok():
  subprocess.run(["pkill","-f","ngrok"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  p=subprocess.Popen(["ngrok","http",str(CALLBACK_PORT)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  for _ in range(60):
    u=get_ngrok_https()
    if u: return p,u
    time.sleep(0.5)
  print("ngrok failed",file=sys.stderr); sys.exit(1)
class H(http.server.BaseHTTPRequestHandler):
  code=None
  def do_GET(self):
    from urllib.parse import urlparse, parse_qsl
    q=dict(parse_qsl(urlparse(self.path).query))
    self.send_response(200); self.end_headers(); self.wfile.write(b"OK. You can close this tab.")
    if "code" in q and not H.code: H.code=q["code"]
  def log_message(self,*a,**k): pass
def wait_code(timeout=180):
  with socketserver.TCPServer(("127.0.0.1",CALLBACK_PORT),H) as httpd:
    th=threading.Thread(target=httpd.serve_forever,daemon=True); th.start()
    t0=time.time()
    while time.time()-t0<timeout and not H.code: time.sleep(0.2)
    httpd.shutdown()
  return H.code
def post_form(url,data):
  b=urllib.parse.urlencode(data).encode()
  req=urllib.request.Request(url,data=b,headers={"Content-Type":"application/x-www-form-urlencoded"})
  with urllib.request.urlopen(req,timeout=15) as r: return r.read()
def write_atomic(path,content_bytes):
  d=os.path.dirname(os.path.abspath(path)) or "."
  fd,tmp=tempfile.mkstemp(dir=d,prefix=".tmp_tokens_"); os.write(fd,content_bytes); os.close(fd); os.replace(tmp,path)
ng, public = start_ngrok()
redirect=f"{public}/callback"
print(f"Redirect URI: {redirect}")
input("Set this in Brightspace OAuth app, Save, then press Enter...")
qs=urllib.parse.urlencode({"response_type":"code","client_id":CLIENT_ID,"redirect_uri":redirect,"scope":SCOPE,"state":"xyz","prompt":"consent"},quote_via=urllib.parse.quote)
auth_url=f"{AUTH_HOST}/oauth2/auth?{qs}"
print("Open:",auth_url)
try: webbrowser.open(auth_url)
except: pass
code=wait_code()
if not code: print("No auth code",file=sys.stderr); sys.exit(1)
tok=post_form(f"{AUTH_HOST}/core/connect/token",{"grant_type":"authorization_code","code":code,"redirect_uri":redirect,"client_id":CLIENT_ID,"client_secret":CLIENT_SECRET})
j=json.loads(tok.decode())
if "refresh_token" not in j: print("Missing refresh_token",file=sys.stderr); sys.exit(1)
write_atomic("tokens.json",tok)
try: os.chmod("tokens.json",0o600)
except: pass
print("tokens.json written.")
try: ng.terminate()
except: pass
