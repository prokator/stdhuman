# StdHuman Communication Guide

This service exists so automated agents and humans can coordinate missions via four primary actions.
Base URL: `http://localhost:18081` (use `PORT` from `.env` if overridden).

For non-OpenCode agents, also review `AGENTS.md` for local tooling and workflow rules.

## Availability check

Before entering the plan/status/ask loop, call `GET /v1/health`. If the service is unavailable, skip the StdHuman API and proceed in normal mode (no Telegram-backed logging).
Hard rule: never call `/v1/plan`, `/v1/log`, or `/v1/ask` unless `/v1/health` succeeded in the same cycle.

1. **Plan** – call `POST /v1/plan` before work starts for every session, passing the human-readable project name and an ordered list of objectives/steps.
2. **Status** – call `POST /v1/log` continually with concise updates (`level` + `message`). These become the shared running log and should describe observable progress, preliminary results, blockers, or errors. When replying to a human question, send the response via `/v1/log` (not `/v1/ask`).
3. **Ask** – call `POST /v1/ask` whenever a decision requires a human. The service always uses the fixed options `Command` and `Stop` in the Telegram prompt (any supplied `options` are accepted but ignored).
   - New `/v1/ask` calls cancel any currently pending decision before creating the next prompt.
   - If you need a non-blocking flow, set `mode: "async"` and poll `GET /v1/ask/result/{request_id}` until it returns an answer.

## MCP option (fallback to REST)

If your client supports MCP, treat `POST /mcp` (tools: `plan`, `log`, `ask`) as the primary path for plan/log/ask actions. When MCP is unavailable, fall back to `POST /v1/plan`, `POST /v1/log`, and `POST /v1/ask`.

MCP clients must call `initialize` first and then send `notifications/initialized` before invoking `tools/list` or `tools/call`.

### Async polling recipe

Use a short loop with JSON parsing so you do not depend on `grep` or other shell utilities:

```bash
request_id="..."
for i in {1..60}; do
  resp=$(curl -s "http://localhost:18081/v1/ask/result/${request_id}")
  echo "$resp"
  status=$(printf '%s' "$resp" | python -c "import sys,json; print('pending' if json.load(sys.stdin).get('status')=='pending' else 'done')")
  if [ "$status" != "pending" ]; then break; fi
  sleep 5
done
```
4. **Finish** – when the mission is done, report it through `POST /v1/log` (e.g., `level: success`, `message: "Mission complete"`) and optionally post a final Telegram message through `/telegram/webhook` or the poller.

## End-of-run sync check

If the agent needs to hand control back to the human for follow-up work, send a **final blocking** `/v1/ask` with a large timeout (e.g., `TIMEOUT=3600`) so the human can respond via Telegram when ready. Keep the question short and provide explicit options (e.g., `"Continue"`, `"Stop"`).

## Telegram answers

When a question is sent, reply in Telegram with plain text to resolve the pending decision. Prompts now include a summary line (no separate question block) with last-status + timeout metadata and the fixed options `Command` and `Stop`.

## Telegram authorization

Telegram access is restricted to a single user. Set `DEV_TELEGRAM_USERNAME` (must start with `@`) in `.env` and ensure the account has a public Telegram username. Generate a start code via `get_code.sh`/`get_code.bat` (it writes `.telegram_start_code`); the code is 12 characters (letters, numbers, `-`, `_`). If the start code file is missing or invalid, the service will generate a new code on startup. Authorize with `/start <code>` to seed `.telegram_user_id`.

Always keep communications brief (~1-2 sentences) and **never** include private data like credentials, code listings, stack traces, or other secrets. Treat this document as the single source for communication etiquette.

`/v1/log` always notifies Telegram, so every status update is delivered to the authorized user ID. Include `step_index` to append a step-complete line.
`/v1/plan` always notifies Telegram, sending the numbered steps to the authorized user ID.
If the plan is not visible in Telegram, retry the call and confirm you are using the correct `PORT` from `.env`.
Use `/v1/health` for container health checks to avoid emitting Telegram notifications.
Telegram inbound updates are restricted to the configured chat ID so only one authorized user can interact with the bot.

## Required usage

Agents must use this API for all mission communications: start with `/v1/plan`, report progress via `/v1/log`, and use `/v1/ask` for blocking decisions or end-of-run sync. This avoids missing updates and keeps a single source of truth for the human.
