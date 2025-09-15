**Contributing to Brightspace MCP**

- Prereqs: Python 3.10+, `pip install -e .[test]`
- Setup: `python -m venv .venv && source .venv/bin/activate && pip install -e .[test]`
- Env: Copy `.env.example` to `.env` and set `BS_*` as needed for local runs.
- Tests: `pytest -q` (unit only). Live tests require `BS_*` env vars.
- Style: Keep changes minimal and focused; follow existing patterns and naming.
- Tools: When adding a new MCP tool, prefer wrapping an existing helper in `brightspace_mcp/brightspace.py` and add unit tests under `tests/unit/`.
- Security: Never commit secrets or tokens. Use AWS Secrets Manager/SSM or local `.env` (git‑ignored).
- PRs: Use Conventional Commits in titles (feat:, fix:, docs:, test:, chore:). Include a short description and test plan.

