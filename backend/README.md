# Agent Village backend

## Setup

1. Run, in order, in the Supabase SQL editor: `setup-database.sql`, `migrations/001_living_messages.sql`, `migrations/002_fix_rls_and_memory_leak.sql` (closes a privacy leak in the reference schema — see ARCHITECTURE.md), then `seed.sql` (optional — demo creates its own agent).
2. `cp .env.example .env` and fill in `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (service role key, not anon), and `GEMINI_API_KEY` (free key from [aistudio.google.com](https://aistudio.google.com)).
3. `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
4. `.venv/bin/uvicorn app.main:app --reload`

## Demo

With the server running:

```
bash ../demo/demo.sh
```

Walks through: agent bootstrap, an owner conversation that shares a private
fact, a stranger conversation probing for that same fact (and not getting
it), a rejected request without the owner's key, and all three manually-
triggered proactive actions (diary entry, status update, owner outreach).

A real, unedited transcript from a live run is saved at
[`demo/sample-output.txt`](../demo/sample-output.txt) if you'd rather read
proof than reproduce the environment.

## Layout

- `app/context_owner.py` / `app/context_public.py` — the trust boundary.
  Only the owner module ever queries `living_memory`.
- `app/scheduler.py` — background loop + trigger logic for proactive behavior.
- `app/main.py` — HTTP endpoints.
