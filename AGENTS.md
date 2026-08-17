# AGENTS.md - t-api

## Deploy behavior
- Deploy = `git pull --ff-only && systemctl restart t-api`.
- Env vars change = `systemctl edit t-api` (Environment= lines) + restart.
- No docker for t-api (systemd service, venv).
