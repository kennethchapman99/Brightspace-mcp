**Brightspace MCP: Implementation, OAuth, AWS Deployment, and Testing**

- **Purpose:** Complete guide to running this Brightspace MCP, obtaining and managing OAuth tokens, deploying on AWS, and producing high‑quality tests and adoption docs for new contributors.
- **Scope:** Tailored to this repository’s code and tooling (`brightspace_mcp`, `brightspace_mcp_launcher.py`, `.env`, tests/).

**Overview**
- **What it is:** An MCP server exposing safe, high‑level tools to interact with Brightspace’s REST API using OAuth2 refresh tokens. Implemented with `mcp.server.fastmcp` and an internal `BrightspaceClient`.
- **Transports:** Defaults to MCP over stdio (ideal for Claude Desktop or any stdio‑based MCP client). Cloud/http usage requires an MCP‑compatible gateway or an HTTP/WS transport for MCP.
- **Key files:**
  - `brightspace_mcp/main.py`: Registers MCP tools and runs `FastMCP` (stdio by default).
  - `brightspace_mcp/brightspace.py`: OAuth, retry/backoff, pagination, helpers, and high‑value wrappers.
  - `brightspace_mcp/authcheck.py`: Validates environment for live calls.
  - `brightspace_mcp_launcher.py` and `auth_only_brightspace.py`: Convenience scripts to mint/refresh tokens locally.
  - `.env.example`: Canonical environment variable names and defaults.

**Supported Tools (Use‑Case Oriented)**
- **Generic API:** `bs.api_call`, `bs.request`, `bs.paginate`, `bs.build_path`, `bs.upload_multipart`, `bs.download_b64`.
- **Identity & Discovery:** `bs.whoami`, `bs.list_org_units`, `bs.list_courses`, `bs.list_users`, `bs.get_user`.
- **Announcements:** `bs.list_announcements`, `bs.create_announcement`, `bs.update_announcement`, `bs.delete_announcement`.
- **Content:** `bs.get_content_toc`, `bs.get_content_topic`, `bs.download_content_topic_file_b64`, `bs.create_content_module`, `bs.create_content_topic`.
- **Assignments (Dropbox):** `bs.list_assignments`, `bs.get_assignment`, `bs.create_assignment`.
- **Discussions:** `bs.list_discussion_forums`, `bs.list_discussion_topics`, `bs.create_discussion_forum`, `bs.create_discussion_topic`.
- **Quizzes:** `bs.list_quizzes`, `bs.get_quiz`.
- **Grades:** `bs.list_grade_items`, `bs.get_user_grades`, `bs.create_grade_item`, `bs.upsert_user_grade_value`.
- **Enrollments:** `bs.list_course_enrollments`, `bs.enroll_user`, `bs.unenroll_user`.

These wrappers cover common Brightspace workflows and can be extended with `bs.api_call` for specialized endpoints.

**Prerequisites**
- **Python:** `3.10+` with `httpx`, `python-dotenv`, `pytest`, and MCP libs installed (managed via `pyproject.toml`).
- **Brightspace OAuth app:** Admin‑registered client with appropriate scopes, e.g. `core:*:* data:*:*` for broad demos; scope down for production.
- **Access to a Brightspace instance:** Example: `https://your-org.brightspacedemo.com` or a self‑hosted D2L domain.

**Environment Variables**
- `BS_BASE_URL`: Brightspace base URL (e.g. `https://d2l.example.com`).
- `BS_CLIENT_ID`: OAuth2 Client ID.
- `BS_CLIENT_SECRET`: OAuth2 Client Secret.
- `BS_REFRESH_TOKEN`: Long‑lived Refresh token (obtained via the flow below).
- `BS_TOKEN_URL` (optional): Override token endpoint. If unset, the client tries common tenant endpoints then `https://auth.brightspace.com/core/connect/token`.
- `BS_LP_VERSION`, `BS_LE_VERSION`: Default LP/LE versions (defaults: `1.46` and `1.74`).
- `BS_LP_VERSION_CANDIDATES`, `BS_LE_VERSION_CANDIDATES`: Comma‑separated fallback lists for version‑aware helpers.

See `.env.example` for a template.

**OAuth: End‑to‑End Guide**
- **1) Register an OAuth app in Brightspace**
  - Set a friendly name (e.g., “Brightspace MCP”).
  - Add scopes needed by your tools. For demos, broad scopes like `core:*:* data:*:*` are simplest; in production, prefer least privilege per tool.
  - Set a Redirect URI for the local consent flow. Use either:
    - `https://localhost:<port>/callback` (self‑signed TLS), or
    - A public HTTPS tunnel (e.g., ngrok) `https://<random>.ngrok.io/callback`.
  - Record the Client ID and Client Secret.

- **2) Mint a refresh token locally (self‑signed TLS)**
  - The repo includes `brightspace_mcp_launcher.py`, which can:
    - Start a local HTTPS callback on `https://localhost:53682/callback` (self‑signed cert generated automatically).
    - Open the Brightspace consent page.
    - Exchange the code for tokens and write `tokens.json` (mode `0600`).
  - Steps:
    - Ensure `CLIENT_ID`, `CLIENT_SECRET`, `BS_BASE_URL`, and `REDIRECT_URI` inside `brightspace_mcp_launcher.py` match your Brightspace app settings. For security, move secrets to environment variables in your local shell rather than hardcoding.
    - Run: `python3 brightspace_mcp_launcher.py` and complete the browser consent.
    - Verify `tokens.json` exists and contains `refresh_token`.

- **3) Alternative token mint (ngrok)**
  - `auth_only_brightspace.py` starts an HTTP callback and uses ngrok to expose a public HTTPS redirect.
  - Steps:
    - Start: `python3 auth_only_brightspace.py` (requires `ngrok` in PATH).
    - Set the printed `Redirect URI` in Brightspace, Save, then approve in the browser.
    - `tokens.json` is created with restricted file permissions.

- **4) Configure the MCP to use your refresh token**
  - Copy `refresh_token` from `tokens.json` into `BS_REFRESH_TOKEN` (via `.env` during development or secrets in AWS for production).
  - Set `BS_BASE_URL`, `BS_CLIENT_ID`, `BS_CLIENT_SECRET` accordingly.
  - Optional: set `BS_TOKEN_URL` to pin a specific token endpoint for your tenant.

- **5) How access/refresh flow works in code**
  - `BrightspaceClient` exchanges `BS_REFRESH_TOKEN` for short‑lived access tokens and caches them in memory.
  - On 401, it refreshes once and retries the request.
  - It backs off on 429 using `Retry-After` when provided.
  - No long‑term token state is persisted by the MCP itself; persistence is your responsibility (e.g., AWS Secrets Manager, SSM Parameter Store).

- **6) Security best practices**
  - Don’t commit tokens or secrets. Keep `.env` local; use `.gitignore`.
  - Rotate client secrets and refresh tokens regularly. Store them in a secrets manager.
  - Scope OAuth permissions to only the tools you run in production.
  - Ensure HTTPS is used end‑to‑end for any remote callback or service exposure.

**Local Run (stdio)**
- Create `.env` from `.env.example` and fill all `BS_*` values.
- Install and run the MCP:
  - `python -m venv .venv && source .venv/bin/activate`
  - `pip install -e .`
  - `brightspace-mcp --stdio` (or `python -m brightspace_mcp.main` depending on your entry point).
- Optionally use `brightspace_mcp_launcher.py` to refresh tokens and launch MCP with a lock to avoid parallel runs.

**AWS Deployment (Containers + Secrets + MCP Transport)**
- **Transport reality check:** This server runs MCP over stdio by default. For cloud use, you have two practical options:
  - Run behind an MCP‑aware gateway that supports HTTP/WebSocket and talks stdio to the containerized MCP process.
  - Or adapt the server to expose an HTTP/WS transport if your MCP client supports it (e.g., an HTTP server mode for `FastMCP`, or a minimal HTTP shim that invokes the same tool functions). Keep auth/protection in front of it.

- **Dockerfile (example)**
  - Build a minimal image that installs your dependencies and sets the entrypoint to the MCP process.

  ```dockerfile
  FROM python:3.11-slim
  WORKDIR /app
  # System deps (add any CA certs, tzdata, etc. as needed)
  RUN pip install --no-cache-dir --upgrade pip
  COPY pyproject.toml .
  RUN pip wheel --no-cache-dir --no-deps -w /wheels . || true
  COPY . .
  RUN pip install --no-cache-dir -e .

  # Security: set non-root user if your base image supports it
  # RUN useradd -m app && chown -R app:app /app && USER app

  ENV PYTHONUNBUFFERED=1
  # Stdio mode by default
  CMD ["brightspace-mcp", "--stdio"]
  ```

- **ECS Fargate (reference architecture)**
  - **Runtime:** 1 ECS task in a private subnet, behind an ALB or internal gateway that speaks MCP to the task (via your chosen gateway/shim).
  - **Secrets:** Store `BS_CLIENT_ID`, `BS_CLIENT_SECRET`, `BS_REFRESH_TOKEN` in AWS Secrets Manager. Inject as environment variables.
  - **Config:** Set `BS_BASE_URL`, versions, and any `BS_TOKEN_URL` override as plain env vars or SSM parameters.
  - **Logging:** Send stdout/stderr to CloudWatch Logs (`awslogs` driver). Redact tokens in logs.
  - **Health:** Add a simple health check to the shim/gateway (e.g., `/healthz`). The MCP process itself is long‑lived and state‑light.
  - **Scaling:** Stateless; scale tasks horizontally if needed. Each task refreshes its own access token on demand.
  - **IAM:** The task role should allow `secretsmanager:GetSecretValue` and `ssm:GetParameter` for the specific paths you use, and no broader.

- **Task definition env (example)**
  - `BS_BASE_URL=...`
  - `BS_LP_VERSION=1.46`, `BS_LE_VERSION=1.74`
  - Secrets from Secrets Manager:
    - `BS_CLIENT_ID` → `arn:aws:secretsmanager:...:secret:brightspace/client`
    - `BS_CLIENT_SECRET` → `arn:aws:secretsmanager:...:secret:brightspace/secret`
    - `BS_REFRESH_TOKEN` → `arn:aws:secretsmanager:...:secret:brightspace/refresh`

- **Network protection**
  - Keep the service internal (VPC‑only) unless you must expose it. If exposed, require an authenticating gateway in front.
  - Enforce TLS in transit and restrict source IPs/security groups.
  - Consider mTLS between gateway and service if crossing trust boundaries.

- **Alternative runtimes**
  - **EKS:** Same container; use a Service + Ingress + mTLS and Secret mounts.
  - **Lambda:** Not ideal for long‑lived stdio MCP. If you add an HTTP transport, ensure cold‑start and concurrency constraints are handled.

**Testing: How to Add and Run Tests**
- **Philosophy:** Favor fast, deterministic unit tests that mock Brightspace HTTP. Gate “live” integration tests behind explicit env vars.

- **Run tests locally**
  - `pytest -q` runs unit tests.
  - Set live env to include integration tests: `export BS_BASE_URL=... BS_CLIENT_ID=... BS_CLIENT_SECRET=... BS_REFRESH_TOKEN=... && pytest -q`.

- **Existing patterns in this repo**
  - Unit tests (`tests/unit/test_brightspace_client.py`) use `monkeypatch` to stub network calls and verify:
    - `build_path` correctness and versioning.
    - Version fallback order for `le()`/`lp()` helpers.
    - Bookmark pagination merge behavior.
  - Integration tests (`tests/integration/`) are skipped unless the required env vars are set and simply smoke the most common flows.
  - New unit coverage includes enrollments, assignments, content creation, and announcement maintenance in `tests/unit/test_wrappers_new.py`.

- **When adding a new MCP tool**
  - Add a focused unit test that:
    - Mocks `BrightspaceClient.request()` or the specific helper used.
    - Asserts request method/path/params/body are constructed correctly.
    - Validates error handling and edge cases (404/410 version handling, 401 refresh, 429 backoff if relevant).
  - If the tool wraps a raw endpoint, prefer testing through the high‑level helper you add in `brightspace_mcp/brightspace.py` so both layers are covered.
  - Example outline:

    ```python
    @pytest.mark.asyncio
    async def test_new_tool_builds_correct_path(monkeypatch):
        c = BrightspaceClient(base_url="https://example.com", client_id="x", client_secret="y", refresh_token="z")
        async def fake_request(method, path, **kwargs):
            assert method == "GET"
            assert path.startswith("/d2l/api/le/") and path.endswith("/target")
            return 200, {"ok": True}, {}
        monkeypatch.setattr(c, "request", fake_request)
        code, data, _ = await c.le("GET", "/target")
        assert code == 200 and data["ok"] is True
    ```

- **Integration tests (opt‑in)**
  - Add under `tests/integration/` and guard with a skip unless `BS_*` env vars exist, mirroring `test_live_brightspace.py`.
  - Keep API‑modifying tests disabled by default; prefer read‑only endpoints for CI smoke.

- **GitHub best practices for tests**
  - Use a matrix CI workflow to run unit tests on `push` and `pull_request` for supported Python versions.
  - Fail fast: keep unit tests isolated and fast; put live tests behind a label or a separate job with required secrets.
  - Enforce style/typing if desired (flake8/ruff/mypy) in separate quick jobs.
  - Track flaky tests and quarantine them; never ignore failures silently.

**Contributor Adoption & Repo Best Practices**
- **CONTRIBUTING.md:** How to set up `.venv`, run `pytest`, add tools, write tests, and open PRs.
- **SECURITY.md:** How to report vulnerabilities; how secrets are handled (AWS Secrets Manager) and rotated.
- **CODEOWNERS:** Auto‑assign reviewers for `brightspace_mcp/*`, `tests/*`, infra.
- **Issue/PR templates:** Bug report, feature request, and PR templates to standardize context and validation steps.
- **Conventional Commits + SemVer:** Standardize commit messages and release versioning.
- **CI/CD:** GitHub Actions with jobs for lint, unit tests, and optional integration tests. Protect `main` with required checks.
- **Automation:** Dependabot for Python deps and GitHub Action updates; scheduled security scans.
- **Docs:** Keep this guide and `README.md` in sync; document any new environment variables and tools.

**Enterprise‑Grade Operations**
- **Security & Compliance:**
  - Secrets isolation via AWS Secrets Manager or SSM. No secrets in images or repos; least‑privileged IAM. Quarterly rotation for client secret and refresh token.
  - TLS everywhere; if exposing HTTP/WS, terminate TLS at ALB and use mTLS or signed requests on the internal hop. Strict CORS disabled by default; allow only required origins.
  - Principle of least privilege for OAuth scopes; separate dev/stage/prod OAuth apps.
  - Audit access to secrets and production logs; enable CloudTrail and retention policies.
- **Resiliency & Rate Limits:**
  - Built‑in backoff for 429 with `Retry‑After`. Add jitter at the gateway layer if you expect bursts.
  - Idempotent tool design for create/update paths; return resource IDs to support safe retries.
  - Health, readiness, and graceful shutdown in the shim/gateway so ECS can drain.
- **Observability:**
  - Structured JSON logs with request IDs; propagate a `x-request-id` header to Brightspace where possible and log round‑trip timings.
  - Emit error taxonomy (Auth, Permission, NotFound, Conflict, RateLimit, Network) to speed triage.
  - Optional tracing via OpenTelemetry or AWS X‑Ray when an HTTP/WS shim is added.
- **SLOs & Alerts:**
  - SLI: success rate of MCP tool calls; p95 latency; 5xx/error rate from shim.
  - Alert on sustained 429s, token refresh failures, and increase in 401s.
  - Budget error budgets per environment; protect prod with rate caps.
- **Release Management:**
  - Conventional Commits + SemVer. Tag releases; publish container images with immutable digests.
  - Staged rollouts: dev → stage → prod; canary a small % of traffic if exposed via gateway.
  - CI enforces unit tests, lint, and type checks before merging to `main`.

**Connect to Claude (Desktop) and Claude Code**
- **Claude Desktop (macOS/Windows/Linux):** Configure an MCP server that Claude launches via stdio.
  - Edit your local Claude config (macOS): `~/Library/Application Support/Claude/claude_desktop_config.json`
  - Add an entry:
    ```json
    {
      "mcpServers": {
        "brightspace": {
          "command": "/absolute/path/to/repo/.venv/bin/brightspace-mcp",
          "args": ["--stdio"],
          "env": {
            "BS_BASE_URL": "https://your.brightspace.host",
            "BS_CLIENT_ID": "...",
            "BS_CLIENT_SECRET": "...",
            "BS_REFRESH_TOKEN": "..."
          }
        }
      }
    }
    ```
  - Restart Claude Desktop; look for the “brightspace” MCP server to load.
- **Claude Code (VS Code extension):** In extension settings, add a custom MCP server with:
  - Command: `/absolute/path/to/repo/.venv/bin/brightspace-mcp`
  - Arguments: `--stdio`
  - Env: same `BS_*` variables as above. The UI provides fields to set env vars.
  - Alternatively, use a project-level `.env` to populate env for the spawned process if the extension supports it.

Tip: Use `brightspace_mcp_launcher.py` if you want a one-step token refresh + MCP launch locally during demos.


**Troubleshooting**
- **401 Unauthorized:** Check `BS_REFRESH_TOKEN` validity and whether your token endpoint is correct for your tenant (`BS_TOKEN_URL`). Re‑mint if stale.
- **403 Forbidden:** Scope missing. Ensure the OAuth app has the required permissions, or switch to an account with access.
- **404/410 on versioned endpoints:** Use `BS_*_VERSION_CANDIDATES` to add fallbacks; see version‑aware helpers in code.
- **429 Too Many Requests:** Backoff is automatic; if frequent, lower concurrency or add retries where appropriate.
- **TLS/Redirect issues during auth:** Ensure the Redirect URI exactly matches your Brightspace app config. For local TLS flow, allow the self‑signed cert just for the consent step.

**Appendix A: Minimal GitHub Actions CI (unit tests)**

```yaml
name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: ${{ matrix.python-version }} }
      - run: python -m pip install --upgrade pip
      - run: pip install -e .[test]
      - run: pytest -q
```

**Appendix B: Secrets layout (Secrets Manager)**
- `brightspace/client` → JSON `{"value":"<CLIENT_ID>"}` or plain string.
- `brightspace/secret` → Client secret.
- `brightspace/refresh` → Refresh token.
- Map these to `BS_CLIENT_ID`, `BS_CLIENT_SECRET`, `BS_REFRESH_TOKEN` in your task definition.

**Appendix C: Health Check Shim (if exposing HTTP)**
- If you add an HTTP shim/gateway, include a `GET /healthz` that returns `200 OK` with a static body. Avoid touching Brightspace on health checks.

**Notes on Cloud Transports**
- This server currently runs over stdio (`mcp.run()` in `brightspace_mcp/main.py`). For AWS/cloud usage, you will either:
  - Use a gateway that speaks MCP over HTTP/WS to clients and bridges stdio to this process, or
  - Add/enable an HTTP transport for `FastMCP` if your client supports MCP over HTTP. Keep authentication in front of the endpoint and do not expose secrets.

Maintainers: if you want, I can also add a Dockerfile, ECS task JSON example, and a GitHub Actions workflow directly to the repo to accelerate deployment.
