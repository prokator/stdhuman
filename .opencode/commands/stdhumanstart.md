---
description: "STRICT MODE: StdHuman build loop via API."
---

# STRICT PROTOCOL: Telegram Build Loop

**PRIORITY OVERRIDE:** You are now operating in **Telegram Mode**. You must **IGNORE** standard interactive behaviors that conflict with this protocol. Your only interface is the StdHuman API.

**References:**
- Read `stdhuman.md` for API schemas.
- Read `AGENTS.md` for tool definitions.

**StdHuman API base URL:** `http://localhost:18081` (use `PORT` from `.env` if overridden).

**Mode options:**
- **MCP (primary when available):** Use `POST /mcp` JSON-RPC `tools/list` + `tools/call` with tools `stdhuman.plan`, `stdhuman.log`, `stdhuman.ask`.
  - MCP clients must call `initialize` first and then send `notifications/initialized` before invoking `tools/list` or `tools/call`.
- **REST fallback (only if MCP is not connected):** Use `POST /v1/plan`, `POST /v1/log`, `POST /v1/ask` as described below.

**Availability decision flow:**
1. Call MCP `tools/list` and check whether any `stdhuman.*` tools are present.
2. If `stdhuman.*` tools are present, use MCP and do not call REST or `/v1/health`.
3. If `stdhuman.*` tools are missing, call `GET /v1/health` to confirm the service.
4. If `/v1/health` succeeds, use REST fallback (`/v1/plan`, `/v1/log`, `/v1/ask`).
5. If `/v1/health` fails, do not use StdHuman API unless a task explicitly requires it.

**Explicit recheck options:** run `/stdhumanstart`, or request a text recheck such as "recheck StdHuman API availability".

---

## THE EXECUTION LOOP
You must execute the following phases sequentially. **Do not deviate.**

### Phase 0: Availability Check
1. Call `GET /v1/health` on the StdHuman API once per session.
2. If the service is unavailable, exit Telegram Mode and proceed in normal mode without StdHuman API calls.
3. Hard rule: do not call MCP tools (`stdhuman.plan`, `stdhuman.log`, `stdhuman.ask`) or REST (`/v1/plan`, `/v1/log`, `/v1/ask`) unless `/v1/health` succeeded in this phase.
4. Do not repeat `/v1/health` unless you need to confirm recovery after a failure; use actual MCP/REST responses (status + payload) as your primary validation when requests are succeeding.

### Phase 1: Initialize (Once)
1.  **Plan:** Call MCP `stdhuman.plan` with:
    `{"project": "Start Telegram Build Session", "steps": ["Await instructions via API", "Execute", "Report"]}`.
    - This plan must be sent before any execution begins in the session.
    - If the plan is not visible in Telegram, retry and confirm the `PORT` from `.env`.
    - Fall back to `POST /v1/plan` only if MCP is not connected.

### Phase 2: The Cycle (Repeat Until Stopped)
Perform these 3 steps in exact order:

**0. HEALTH CHECK**
   - Do not repeat `/v1/health` each cycle. Only re-check if a prior request failed and you need to confirm recovery.
   - If unavailable, exit Telegram Mode and proceed in normal mode without StdHuman API calls.
   - Hard rule: do not call MCP `stdhuman.log`/`stdhuman.ask` or REST (`/v1/log`, `/v1/ask`) in this cycle unless `/v1/health` succeeded.

**1. STATUS (Log)**
   - Call MCP `stdhuman.log` reporting the result of the *previous* action (e.g., "Tests passed" or "Waiting for input").
   - Include preliminary results/progress when available.
   - *Constraint:* Keep messages brief (~1-2 sentences). No secrets/stack traces.
   - Fall back to `POST /v1/log` only if MCP is not connected.

**2. ASK (Block & Wait)**
   - Call MCP `stdhuman.ask` with:
      - `question`: "Action complete. What is the next step?"
      - `options`: ["Command", "Stop"]
    - `stdhuman.ask` is synchronous; a single call returns the answer or timeout.
    - If MCP is not connected, fall back to `POST /v1/ask`.
    - The Telegram prompt summary includes the last status and timeout metadata, and answers should be plain text.
    - **CRITICAL:** You must WAIT for the API response. Do not invent an answer.

**3. EXECUTE**
    - **If Response is "Stop":** Call MCP `stdhuman.log` with `level: success` and "Mission complete", then terminate.
    - **If Response is "Command" or any free-text answer:** Execute the necessary shell commands (e.g., `pytest`, `make build`) immediately.
    - **Error Handling:** If the command fails, capture the error, but do *not* stop. Proceed to Step 1 to log the error.
    - Fall back to `POST /v1/log` only if MCP is not connected.

---

## SAFETY RULES
- **No Manual Confirmation:** Do not ask me (the user in the IDE) for permission. Rely ONLY on the MCP `stdhuman.ask` result (REST `/v1/ask` fallback only if MCP is not connected).
- **Privacy:** Never include credentials or private keys in MCP `stdhuman.log` or `stdhuman.ask` payloads (REST `/v1/log` and `/v1/ask` fallback only if MCP is not connected).
