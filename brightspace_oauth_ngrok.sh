#!/usr/bin/env bash
# brightspace_oauth_ngrok.sh — single-run Brightspace OAuth via ngrok
set -euo pipefail

# ===== REQUIRED: set your values here (or export before running) =====
export BRIGHTSPACE_CLIENT_ID="${BRIGHTSPACE_CLIENT_ID:-your_client_id}"
export BRIGHTSPACE_CLIENT_SECRET="${BRIGHTSPACE_CLIENT_SECRET:-your_client_secret}"
export BS_BASE_URL="${BS_BASE_URL:-https://your.brightspace.host}"
# ===== no edits below unless you want to =====

BS_AUTH_HOST="${BS_AUTH_HOST:-https://auth.brightspace.com}"
SCOPE="${SCOPE:-core:*:* data:*:*}"
LP_VER="${LP_VER:-1.50}"
CALLBACK_PORT="${CALLBACK_PORT:-53682}"

need() { command -v "$1" >/dev/null || { echo "missing: $1"; exit 1; }; }
need curl; need jq; need python3; need ngrok

TMPDIR="$(mktemp -d)"; CODE_FILE="$TMPDIR/auth_code.txt"; PIDFILE="$TMPDIR/pids"
cleanup(){ set +e; [ -f "$PIDFILE" ] && while read -r p; do kill "$p" 2>/dev/null||true; done <"$PIDFILE"; rm -rf "$TMPDIR"; }
trap cleanup EXIT

# tiny local HTTP server to capture ?code=
python3 - "$CODE_FILE" "$CALLBACK_PORT" <<'PY' & 
import sys, urllib.parse, http.server, socketserver, threading
code_file, port = sys.argv[1], int(sys.argv[2])
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        u = urllib.parse.urlparse(self.path); q = dict(urllib.parse.parse_qsl(u.query))
        code = q.get("code",""); self.send_response(200); self.end_headers()
        self.wfile.write(b"OK. You can close this tab.")
        if code: open(code_file,"w").write(code)
    def log_message(self,*a,**k): pass
httpd = socketserver.TCPServer(("127.0.0.1", port), H)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
try:
    threading.Event().wait()  # keep alive
except KeyboardInterrupt:
    httpd.shutdown()
PY
echo $! >> "$PIDFILE"

# ngrok tunnel
ngrok http "$CALLBACK_PORT" >/dev/null 2>&1 & echo $! >> "$PIDFILE"

# discover https public URL
PUB=""
for i in {1..60}; do
  sleep 0.5
  PUB="$(curl -sS http://127.0.0.1:4040/api/tunnels \
        | jq -r '.tunnels[]?|select(.proto=="https")|.public_url' | head -n1)"
  [ -n "${PUB:-}" ] && break
done
[ -n "${PUB:-}" ] || { echo "ngrok public URL not found"; exit 1; }
REDIRECT_URI="${PUB%/}/callback"
echo "Using redirect_uri: $REDIRECT_URI"

echo
echo "ACTION: In Brightspace Admin > Manage OAuth 2.0 > your app"
echo "Set Redirect URI to exactly: $REDIRECT_URI"
read -r -p "Press Enter when saved..."

# build authorize URL
urlencode(){ python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1],safe=''))" "$1"; }
AUTH_URL="$BS_AUTH_HOST/oauth2/auth?response_type=code&client_id=$(urlencode "$BRIGHTSPACE_CLIENT_ID")&redirect_uri=$(urlencode "$REDIRECT_URI")&scope=$(urlencode "$SCOPE")&state=xyz&prompt=consent"
echo "Authorize URL:"
echo "$AUTH_URL"
command -v open >/dev/null && open "$AUTH_URL" || command -v xdg-open >/dev/null && xdg-open "$AUTH_URL" || true

# wait for auth code
echo -n "Waiting for auth code"
for i in {1..240}; do
  [ -s "$CODE_FILE" ] && { echo " ✓"; break; }
  sleep 0.5; echo -n "."
done
[ -s "$CODE_FILE" ] || { echo; echo "Timeout waiting for code"; exit 1; }
CODE="$(cat "$CODE_FILE")"

# exchange code -> tokens
echo "Exchanging code for tokens..."
TOKENS_JSON="$TMPDIR/tokens.json"
curl -sS -X POST "$BS_AUTH_HOST/core/connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=authorization_code" \
  -d "code=$CODE" \
  -d "redirect_uri=$REDIRECT_URI" \
  -d "client_id=$BRIGHTSPACE_CLIENT_ID" \
  -d "client_secret=$BRIGHTSPACE_CLIENT_SECRET" \
  | tee "$TOKENS_JSON" >/dev/null

ACCESS_TOKEN="$(jq -r .access_token "$TOKENS_JSON")"
REFRESH_TOKEN="$(jq -r .refresh_token "$TOKENS_JSON")"
[ "$ACCESS_TOKEN" != "null" ] || { echo "Failed to obtain access_token:"; cat "$TOKENS_JSON"; exit 1; }
echo "Access token acquired."
[ "$REFRESH_TOKEN" != "null" ] && echo "Refresh token acquired."

# sanity call
echo "Calling whoami..."
curl -sS "$BS_BASE_URL/d2l/api/lp/$LP_VER/users/whoami" \
  -H "Authorization: Bearer $ACCESS_TOKEN" | jq .

# demo refresh
if [ "$REFRESH_TOKEN" != "null" ]; then
  echo "Refreshing token..."
  REFRESH_JSON="$TMPDIR/refresh.json"
  curl -sS -X POST "$BS_AUTH_HOST/core/connect/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=refresh_token" \
    -d "refresh_token=$REFRESH_TOKEN" \
    -d "client_id=$BRIGHTSPACE_CLIENT_ID" \
    -d "client_secret=$BRIGHTSPACE_CLIENT_SECRET" \
    | tee "$REFRESH_JSON" >/dev/null
  NEW_RT="$(jq -r .refresh_token "$REFRESH_JSON" 2>/dev/null || echo null)"
  [ "$NEW_RT" != "null" ] && echo "New refresh token returned. Persist it."
fi

cp "$TOKENS_JSON" ./tokens.json 2>/dev/null || true
echo "Saved tokens.json. Done."
