# StdHuman Communication Guide

This service exists so automated agents and humans can coordinate missions via four primary actions.
Base URL: `http://localhost:18081` (use `PORT` from `.env` if overridden). MCP endpoint: `POST /mcp`.

For non-OpenCode agents, also review `AGENTS.md` for local tooling and workflow rules.

## Availability check

If MCP is connected and `stdhuman.*` tools are available, do not call REST endpoints or `/v1/health`.
Only call `GET /v1/health` when MCP is unavailable and you need to confirm the REST fallback path.
If the service is unavailable, skip StdHuman and proceed in normal mode (no Telegram-backed logging).

### Availability decision flow

Use this order when you need to confirm StdHuman availability:

1. Call MCP `tools/list` and check whether any `stdhuman.*` tools are present.
2. If `stdhuman.*` tools are present, use MCP and do not call REST or `/v1/health`.
3. If `stdhuman.*` tools are missing, call `GET /v1/health` to confirm the service.
4. If `/v1/health` succeeds, use REST fallback (`/v1/plan`, `/v1/log`, `/v1/ask`).
5. If `/v1/health` fails, do not use StdHuman API unless a task explicitly requires it.

Explicit recheck options: run the `/stdhumanstart` command, or ask for a text recheck such as "recheck StdHuman API availability".

1. **Plan** – use MCP `stdhuman.plan` before work starts for every session, passing the human-readable project name and an ordered list of objectives/steps. Fall back to `POST /v1/plan` only if MCP is not connected.
2. **Status** – use MCP `stdhuman.log` continually with concise updates (`level` + `message`). These become the shared running log and should describe observable progress, preliminary results, blockers, or errors. When replying to a human question, send the response via MCP `stdhuman.log` (not `stdhuman.ask`). Fall back to `POST /v1/log` only if MCP is not connected.
3. **Ask** – use MCP `stdhuman.ask` whenever a decision requires a human. The service always uses the fixed options `Command` and `Stop` in the Telegram prompt (any supplied `options` are accepted but ignored). Fall back to `POST /v1/ask` only if MCP is not connected.
   - New `stdhuman.ask` calls cancel any currently pending decision before creating the next prompt (REST `/v1/ask` behaves the same in fallback mode).

## MCP primary (REST fallback)

Use MCP (`POST /mcp`, tools: `stdhuman.plan`, `stdhuman.log`, `stdhuman.ask`) as the primary path for plan/log/ask actions. Fall back to REST (`/v1/plan`, `/v1/log`, `/v1/ask`) only if MCP is not connected.

MCP clients must call `initialize` first and then send `notifications/initialized` before invoking `tools/list` or `tools/call`.

### Ask is synchronous

- `stdhuman.ask` is blocking and completes in a single tool call. Wait for the response (answer or timeout) and do not issue a follow-up query.

### Validating availability

- Use actual MCP or REST responses (HTTP status + JSON body) as the primary validation of availability.
- Do not call `/v1/health` when MCP is connected; only use it when MCP is unavailable and you need REST fallback validation.

4. **Finish** – when the mission is done, report it through MCP `stdhuman.log` (e.g., `level: success`, `message: "Mission complete"`) and optionally post a final Telegram message through `/telegram/webhook` or the poller. Fall back to `POST /v1/log` only if MCP is not connected.

## End-of-run sync check

If the agent needs to hand control back to the human for follow-up work, send a **final blocking** MCP `stdhuman.ask` with a large timeout (e.g., `TIMEOUT=3600`) so the human can respond via Telegram when ready. Keep the question short and provide explicit options (e.g., `"Continue"`, `"Stop"`). Fall back to `/v1/ask` only if MCP is not connected.

## Telegram answers

When a question is sent, reply in Telegram with plain text to resolve the pending decision. Prompts now include a summary line (no separate question block) with last-status + timeout metadata and the fixed options `Command` and `Stop`.

## Telegram authorization

Telegram access is restricted to a single user. Set `DEV_TELEGRAM_USERNAME` (must start with `@`) in `.env` and ensure the account has a public Telegram username. Generate a start code via `get_code.sh`/`get_code.bat` (it writes `.telegram_start_code`); the code is 12 characters (letters, numbers, `-`, `_`). If the start code file is missing or invalid, the service will generate a new code on startup. Authorize with `/start <code>` to seed `.telegram_user_id`.

Always keep communications brief (~1-2 sentences) and **never** include private data like credentials, code listings, stack traces, or other secrets. Treat this document as the single source for communication etiquette.

MCP `stdhuman.log` always notifies Telegram, so every status update is delivered to the authorized user ID. Include `step_index` to append a step-complete line. (REST `/v1/log` is fallback.)
MCP `stdhuman.plan` always notifies Telegram, sending the numbered steps to the authorized user ID. (REST `/v1/plan` is fallback.)
If the plan is not visible in Telegram, retry the call and confirm you are using the correct `PORT` from `.env`.
Use `/v1/health` for container health checks to avoid emitting Telegram notifications.
Telegram inbound updates are restricted to the configured chat ID so only one authorized user can interact with the bot.

## Required usage

Agents must use MCP for all mission communications: start with `stdhuman.plan`, report progress via `stdhuman.log`, and use `stdhuman.ask` for blocking decisions or end-of-run sync. Fall back to `/v1/plan`, `/v1/log`, and `/v1/ask` only when MCP is not connected. This avoids missing updates and keeps a single source of truth for the human.
