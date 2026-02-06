# StdHuman FastAPI Agent

Minimal FastAPI service exposing the StdHuman planning/logging/decision endpoints documented in `stdhuman.md`. The app stays lightweight so it can run on a developer workstation (x86, x64, ARM64, Apple Silicon) and includes guidance for both shell and Docker deployment.

If you want a smoother operator experience, start with OpenCode: it can drive StdHuman directly and also bridge to multiple platforms via MCP integrations (for example JetBrains, Gemini CLI, or Copilot CLI).

## Global step logic

1. Create the Telegram bot in BotFather and copy the token (see [New bot setup](#new-bot-setup)).
2. Set up the repo on the host (clone, pull, or sync as needed).
3. Add `.env` with the bot token and `DEV_TELEGRAM_USERNAME` (see [Setup](#setup)).
4. Run `get_code.sh` or `get_code.bat` to mint/show the start code (recommended; see [Setup](#setup)).
5. Start Docker with `docker compose up --build -d` (see [Setup](#setup)).
6. Send `/start <code>` to the bot in Telegram (not the CLI) so the running service can capture `.telegram_user_id` (see [Setup](#setup)).

## Setup

The deployment flow is ordered: configure `.env`, generate/show a start code (recommended), then start Docker. This keeps the `.telegram_*` files stable as files (not directories) for bind mounts.

1. Ensure you are on Windows 11 (PowerShell) or any shell that can run the provided scripts.
2. Provide required environment variables via `.env` (recommended):
   ```ini
   TELEGRAM_BOT_TOKEN=...
   DEV_TELEGRAM_USERNAME=@your-telegram-username
   PORT=18081
   TIMEOUT=900
   ```

   `DEV_TELEGRAM_USERNAME` is security-critical: it is the only authorized channel for bot communication and must start with `@`. The bot verifies the username from incoming messages, so the account must have a public Telegram username set. The service stores the numeric start code in `.telegram_start_code` once generated.

   Save this file as `.env` (do not commit it) so both the CLI scripts and Docker Compose can pick up the credentials automatically. You can copy the template from `.env.example` before filling in secrets:

   ```bash
   cp .env.example .env
   ```

3. Generate the `/start` code on the host (recommended before starting the container so the code is ready and visible):
   ```bash
   ./get_code.sh
   ```
   ```powershell
   get_code.bat
   ```
   The script prints `/start <code>` where `<code>` is a 12-character string (letters, numbers, `-`, `_`).
   If `.telegram_start_code` is missing or invalid, the service will generate a new code on startup; run the script to print it explicitly before `docker compose up --build -d`.
4. Start Docker so the service can receive Telegram updates:
   ```bash
   docker compose up --build -d
   ```

5. Then send `/start <code>` to your bot in Telegram (not the CLI). This creates `.telegram_user_id` locally.

## Running the API

Use the provided helper scripts or run Uvicorn manually:

```bash
./run-dev.sh
```

```powershell
run-dev.bat
```

Or invoke Uvicorn directly binding only to localhost (the default port is 18081 to minimize collisions). Always use the `PORT` from `.env` for API calls:
```powershell
uvicorn app.main:app --host 127.0.0.1 --port ${PORT:-18081}
```

Once running, use the documented `/v1/plan`, `/v1/log`, and `/v1/ask` endpoints. The human decision endpoint blocks until the decision is resolved or the configured `TIMEOUT` elapses. In this prototype the resolution is triggered programmatically through `app.decision.decision_coordinator.resolve(answer)` (tests hook into it directly), but future integrations can push answers via Telegram or another UX targeting that coordinator.

`/v1/plan` always notifies Telegram and sends the numbered steps to the cached/configured user ID.

## MCP server (plan/log/ask)

StdHuman exposes a JSON-RPC 2.0 MCP endpoint at `POST /mcp` for the same Telegram-backed actions as the REST API. Treat MCP as the primary path for `plan`, `log`, and `ask` when available, and fall back to the REST endpoints otherwise (this does not connect to external MCP servers). The MCP endpoint follows the Streamable HTTP transport: POST requests may return either JSON or an SSE stream, and notifications/responses return 202 Accepted with no body.
The same endpoint also accepts `GET /mcp` with `Accept: text/event-stream` to open a server-to-client SSE stream.
The server accepts MCP protocol versions `2024-11-05`, `2025-03-26`, and `2025-06-18`. Origins are restricted to localhost, but `Origin: null` is allowed for local, non-browser clients.
Use `GET /mcp?once=1` to emit a single keep-alive line for smoke tests without holding an infinite stream open.
Clients should call `initialize` first and then send `notifications/initialized` before invoking tools.

## Telegram integration

- The container polls Telegram's `getUpdates` API every few seconds, so once `.env` contains `TELEGRAM_BOT_TOKEN` and `DEV_TELEGRAM_USERNAME` you can authorize via `/start <code>`—no webhook setup is required.
- Incoming Telegram updates are restricted to the stored `.telegram_user_id`, so only the authorized user can interact with the bot.
- Successful `/start <code>` stores the numeric user ID in `.telegram_user_id`; the Compose file bind-mounts this file so it persists between host and container.
- The service stores the start code in `.telegram_start_code` so it stays stable across restarts.
- The `/telegram/webhook` endpoint remains available for developers who prefer to route updates directly.
- When `/v1/ask` is called, the service posts a Telegram prompt that includes a summary line (no separate question block) with the last status + timeout metadata and the fixed options `Command` and `Stop`. Respond with plain text in Telegram to resolve the pending decision.
- If you want a non-blocking flow, call `/v1/ask` with `mode: "async"` and then poll `/v1/ask/result/{request_id}` until it returns an answer.
- New `/v1/ask` calls cancel any currently pending decision before creating the next prompt.
- For sync questions, you may pass `timeout` (seconds) in the `/v1/ask` body to override the default server timeout.

## OpenCode usage (optional)

If you use OpenCode, the `/stdhumanstart` command in `.opencode/commands/stdhumanstart.md` enforces the Telegram build loop via the StdHuman API. It is designed for short, structured status updates and blocking questions.

### OpenCode MCP integration

If you want OpenCode to drive StdHuman via MCP instead of REST, register this service as an MCP server pointing at `http://localhost:18081/mcp` and use the exposed tools (`plan`, `log`, `ask`). Most OpenCode MCP registries let you add a named server with a base URL; once added, the agent can call these tools directly.

Quick MCP smoke checks:

```bash
curl -X POST http://localhost:18081/mcp \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

```bash
curl -X POST "http://localhost:18081/mcp?transport=sse" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```
```

```bash
curl -X POST http://localhost:18081/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"log","arguments":{"level":"info","message":"Hello from MCP"}}}'
```

### Other MCP clients (JetBrains, Gemini CLI, Copilot CLI)

StdHuman exposes a standard MCP JSON-RPC endpoint at `http://localhost:18081/mcp`, so any MCP-capable client can connect. While the UI labels differ by product, the steps are consistent:

1. Ensure StdHuman is running locally.
2. Add a new MCP server in the client and set the server URL to `http://localhost:18081/mcp`.
3. Refresh tools and use `plan`, `log`, and `ask` from the client.

If a client requires a name or namespace, use something like `stdhuman` and keep the base URL unchanged.

## General agentic usage

Non-OpenCode agents should follow the same plan/status/ask flow documented in `stdhuman.md` to keep communication consistent and auditable.
All agent communication must use the plan/log/ask/finish flow via the StdHuman API as documented in [stdhuman.md](stdhuman.md).
When replying to a human question, send the response via `/v1/log`.
Before entering the plan/status/ask loop, call `GET /v1/health`; if the service is unavailable, proceed in normal mode without StdHuman API calls.
Hard rule: never call `/v1/plan`, `/v1/log`, or `/v1/ask` unless `/v1/health` succeeded in the same cycle.

Copy/paste line for other projects' `AGENTS.md`:

```
All agent communication must use the plan/log/ask/finish flow via the StdHuman API as documented in stdhuman.md.
```

Example message string for non-OpenCode agents:

```
Plan: gather logs; Status: anonymized reports ready; Ask: continue deploy?
```

### Security recommendations

- Keep the bot username private and only share direct links with trusted users.
- Always set `DEV_TELEGRAM_USERNAME` in `.env`; this is the one and only authorized communication channel.
- Use `/start <code>` to authorize the bot. Generate the code locally with `get_code.sh` or `get_code.bat`.
- No default password is shipped; access requires the generated start code plus the authorized Telegram username.

### BotFather command config (optional)

- Set bot commands to:
  - `/start` – authorize with a start code.
- Keep privacy mode enabled (default) so group messages are only seen when mentioned or using commands.

`/v1/log` always notifies Telegram, so every status log is sent to the authorized user ID. If you include `step_index`, the notification appends `Step N/total complete: <step>` so Telegram shows progress. Health checks use `/v1/health` to avoid spamming Telegram:

```bash
curl -X POST http://localhost:18081/v1/log \
  -H "Content-Type: application/json" \
  -d '{"level":"info","message":"Build ready"}'
```

We included `test.sh`/`test.bat` to reproduce this curl call on Linux/macOS or Windows. Run the script inside the repo while the service is running to trigger a status message.

## End-of-run sync check

If you want the agent to pause and wait for human input at the end of a task, send a final `/v1/ask` with a large timeout (e.g., `TIMEOUT=3600`) so the human can answer later via Telegram. This keeps the workflow synchronous without forcing a redeploy.

## Agent messaging example

For consistent, short communication, agents can send strings like:

```
Plan: gather logs; Status: anonymized reports ready; Ask: continue deploy?
```

Keep every message brief and avoid embedding secrets, code, or large multi-line payloads; refer to `stdhuman.md` for the full flow.

## Example usage

Start a mission (sends steps to Telegram):

```bash
curl -X POST http://localhost:18081/v1/plan \
  -H "Content-Type: application/json" \
  -d '{
    "project": "StdHuman",
    "steps": [
      "Collect logs",
      "Fix delivery issue",
      "Verify via tests"
    ]
  }'
```

Send a status update (optionally with step progress):

```bash
curl -X POST http://localhost:18081/v1/log \
  -H "Content-Type: application/json" \
  -d '{"level":"info","message":"Applied fix","step_index":2}'
```

Request a decision (Telegram prompt includes summary + Command/Stop options):

```bash
curl -X POST http://localhost:18081/v1/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"Proceed to deploy?","mode":"async"}'
```

## Testing

Run the pytest suite to cover the FastAPI behavior before finishing any build:
```powershell
pytest
```

Every functional change must be covered by tests and validated with this command per the agent directives.

## Deployment

1. **Shell Script (`run-dev.bat` / `run-dev.sh`)
   - The scripts create/activate `.venv`, install dependencies via `pip install -r requirements.txt`, and launch `uvicorn app.main:app --host 127.0.0.1 --port ${PORT}` so the service stays lean on your developer workstation (x86/ARM64).
   - Keep the session running or wrap the script in a lightweight watchdog if you prefer more automation; the scripts ensure installation and execution happen in a single, repeatable flow.

2. **Docker Compose (multi-arch)**
    - Run `docker compose up --build` (or `docker-compose up --build`). Compose automatically loads `.env`, so make sure it contains `TELEGRAM_BOT_TOKEN`, `DEV_TELEGRAM_USERNAME`, `PORT`, and `TIMEOUT` before you start the service.
   - Docker Buildx can then target `linux/amd64`, `linux/arm64`, `linux/arm/v7`, and `linux/arm64/v8` per the `platforms` stanza in `docker-compose.yml`.
    - Uvicorn runs via `sh -c` inside the container so the `${PORT:-18081}` default applies, and the service exposes that port, consumes the loaded env vars, and restarts via `restart: unless-stopped`. It checks `/v1/health` for its healthcheck, so the Dockerfile installs `curl` ahead of time.
    - The service container is named `stdhuman-bot`, so you can reference it directly when tails logs or running exec commands (e.g., `docker logs -f stdhuman-bot`).

## Maintenance Notes

- All functional code is backed by automated tests, and they must pass before builds are declared complete.
- Security-first mindset: validate inputs (via Pydantic models), avoid default credentials, and never commit secrets.
- Keep the implementation clean and documented for both AI tooling and human maintainers.
- Keep `.gitignore` aligned with tracked content so runtime `.telegram_start_code` and `.telegram_user_id` stay ignored while documentation remains discoverable.
- Update this README whenever functionality or deployment instructions change so it can serve as the GitHub presentation of the repo.
- After code changes, request a container rebuild (`docker compose up --build -d`) so the running service stays aligned with the latest edits.
- When running local commands, prefer the `.venv` Python interpreter if it exists and use `ls -a` to confirm hidden files like `.env` and `.venv` are present.

## New bot setup

When onboarding a new Telegram bot, follow this sequence before you touch Docker:

1. Create a bot in BotFather and copy the token.
2. Set `TELEGRAM_BOT_TOKEN` and `DEV_TELEGRAM_USERNAME` in `.env`.
3. Run `get_code.sh` or `get_code.bat` to mint/show the start code (recommended).
4. Start Docker with `docker compose up --build -d` so the service can receive Telegram updates.
5. Send `/start <code>` to the bot in Telegram so `.telegram_user_id` is created.
