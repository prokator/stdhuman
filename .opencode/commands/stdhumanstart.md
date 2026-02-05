---
description: "STRICT MODE: StdHuman build loop via API."
---

# STRICT PROTOCOL: Telegram Build Loop

**PRIORITY OVERRIDE:** You are now operating in **Telegram Mode**. You must **IGNORE** standard interactive behaviors that conflict with this protocol. Your only interface is the StdHuman API.

**References:**
- Read `stdHuman.md` for API schemas.
- Read `AGENTS.md` for tool definitions.

**StdHuman API base URL:** `http://localhost:18081` (use `PORT` from `.env` if overridden).

---

## THE EXECUTION LOOP
You must execute the following phases sequentially. **Do not deviate.**

### Phase 1: Initialize (Once)
1.  **Plan:** Call `POST /v1/plan` with:
    `{"project": "Start Telegram Build Session", "steps": ["Await instructions via API", "Execute", "Report"]}`.
    - This plan must be sent before any execution begins in the session.

### Phase 2: The Cycle (Repeat Until Stopped)
Perform these 3 steps in exact order:

**1. STATUS (Log)**
   - Call `POST /v1/log` reporting the result of the *previous* action (e.g., "Tests passed" or "Waiting for input").
   - Include preliminary results/progress when available.
   - *Constraint:* Keep messages brief (~1-2 sentences). No secrets/stack traces.

**2. ASK (Block & Wait)**
   - Call `POST /v1/ask` with:
     - `question`: "Action complete. What is the next step?"
     - `options`: ["Command", "Stop"]
     - `mode`: "async"
    - Poll `GET /v1/ask/result/{request_id}` for up to 5 minutes.
    - The Telegram prompt summary includes the last status and timeout metadata, and answers should be plain text.
    - **CRITICAL:** You must WAIT for the API response. Do not invent an answer.

**3. EXECUTE**
    - **If Response is "Stop":** Call `POST /v1/log` with `level: success` and "Mission complete", then terminate.
    - **If Response is "Command" or any free-text answer:** Execute the necessary shell commands (e.g., `pytest`, `make build`) immediately.
    - **Error Handling:** If the command fails, capture the error, but do *not* stop. Proceed to Step 1 to log the error.

---

## SAFETY RULES
- **No Manual Confirmation:** Do not ask me (the user in the IDE) for permission. Rely ONLY on the `POST /v1/ask` result.
- **Privacy:** Never include credentials or private keys in `POST /v1/log` or `POST /v1/ask` payloads.
