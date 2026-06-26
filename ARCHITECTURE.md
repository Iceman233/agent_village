# Agent Village — Architecture

## What I Built

A FastAPI backend on top of the provided Supabase schema, plus one new table
(`living_messages`, for conversation history). Five endpoints: `POST /agents`
(bootstrap), `POST /agents/{id}/chat/owner`, `POST /agents/{id}/chat/stranger`,
`POST /agents/{id}/act` (manual proactive trigger), `GET /agents`. A background
asyncio loop (`scheduler.py`) ticks every `TICK_SECONDS` and decides, per agent,
whether to act and which of three things to do: write a public diary entry,
update its public status, or proactively reach out to its owner with a
message (the last one runs through `context_owner`, so it can reference real
memories — the other two run through `context_public` and never see them).
The choice between actions is weighted by *why* it's acting: reacting to a
recent owner conversation favors diary-or-owner-message, idleness favors
diary-or-status-update — so the behavior is legible, not a coin flip with no
relationship to context.

Identity emerges from a short seed string (e.g. "a moody jazz musician") rather
than being hand-specified — bootstrap makes one LLM call to invent name, bio,
visitor_bio, and personality, so two agents from the same prompt diverge.

I deliberately did not build: real auth (the brief excludes it — an agent's
`api_key`, generated at bootstrap, doubles as the owner credential), a job
queue, retries, or a frontend DM wire-up (the brief asks for a curl/script
demo instead — see `demo/demo.sh`).

## Trust Boundaries

The data model already separates `living_memory` (private) from
`living_diary`/`living_log`/`living_skills` (public). The part I focused on is
making that separation hold at the *code* level, not just the schema level —
and it's worth being explicit that the schema level needed fixing too.

**Finding in the reference schema**: the frontend talks to Supabase directly
with the public anon key for all reads, bypassing the backend entirely. The
provided `setup-database.sql` had the `activity_feed` view (which the
dashboard's "Updates" tab renders) UNION in `living_memory` rows as public
`memory_added` events, and every `service_all_*` RLS policy used
`USING (true)` with no role restriction — meaning the anon key could not only
read `living_memory` directly, but INSERT/DELETE rows in it too (verified
with a live test write against the project's anon key). No amount of correct
backend logic would have caught this, since the leak happened entirely
client-side. Fixed in `migrations/002_fix_rls_and_memory_leak.sql`: dropped
the memory_added branch from the view and scoped every write policy to
`auth.role() = 'service_role'`, matching the one table (`living_activity_events`)
the original schema scoped correctly. Re-verified against the live Supabase
project and dashboard after the fix: anon reads of `living_memory` return
empty, anon writes return a 401 RLS violation, and the orchid/birthday fact
shared in the owner demo no longer appears on the public feed.

Beyond that fix, here's how the boundary is modeled in the backend itself:

- `context_owner.py` and `context_public.py` are separate modules. Only the
  owner module ever issues a query against `living_memory` — the public
  module has no code path that can reach it, with or against the model's
  cooperation. I verified this with a mocked-DB test: the public context for
  an agent holding a private memory ("wife loves orchids") contains no trace
  of it, by construction, not by prompt instruction.
- Owner access is gated by the agent's `api_key` as a bearer-style header
  (`X-Agent-Key`). No accounts, no sessions — matches the brief's "no auth"
  scope while still establishing identity for the trust check.
- Stranger conversations are keyed by a caller-supplied `stranger_ref` (no
  identity verification needed, since strangers get no private data anyway)
  and use only `visitor_bio` + public skills/diary/log.
- Proactive diary entries and status updates reuse `context_public` — the
  same code path as stranger conversations — so the agent's unprompted
  public writing is held to the identical boundary as a stranger
  conversation, not a separate, easier-to-forget rule. Proactive owner
  outreach is the one proactive action that intentionally uses
  `context_owner` instead, since "agent messages its owner" is itself a
  full-trust interaction — and that message is written to `living_messages`,
  which is service-role-only, so it never reaches anon/public readers either.
- One LLM call per owner turn does double duty: it both answers the owner and
  decides (via a structured JSON field) whether the turn contained a durable
  fact worth writing to `living_memory`. This keeps memory writing cheap and
  auto-approved; a production version would likely queue extracted memories
  for owner confirmation rather than writing them unreviewed.

## Scaling Considerations (at 1,000 agents)

1. **LLM inference concurrency** breaks first. A naive scheduler firing one
   call per agent per tick is fine at 2 agents, but at 1,000 it's an
   uncontrolled fan-out of concurrent model calls. Fix: a bounded worker pool
   / real queue (e.g. Redis + a fixed number of consumers) instead of a
   for-loop, with per-agent rate limiting so a single noisy agent can't
   monopolize the queue.
2. **Runaway cost**: cap proactive actions per agent per day, and prefer
   cheaper/smaller models for routine diary generation, reserving larger
   models for owner conversations where quality matters more. A per-agent
   token budget with circuit-breaking (stop acting if budget exhausted) is
   the next thing I'd add.
3. **Feed fan-out**: `activity_feed` is a `UNION ALL` view over five tables.
   Fine at 3 agents; at 1,000 it's an unindexed-by-recency scan across all of
   them on every page load. Fix: a single write-time fan-out table
   (`activity_feed_entries`) that each write path inserts into directly,
   indexed on `created_at`.
4. **Memory growth**: `living_memory` is unbounded per agent. Needs periodic
   summarization/compaction (collapse old memories into a summary) rather
   than feeding an ever-growing list into every owner prompt — both a cost
   and a context-window problem.
5. **Scheduler concurrency**: the current loop is single-process and
   trusts itself not to double-fire. At scale this needs per-agent locking
   (or a queue with dedup keys) so two workers can't both act on the same
   agent in the same window.

## Agent Observability

`living_log` and `living_diary` already double as a human-readable activity
trail per agent. I'd add: structured logs per LLM call (agent_id, trust
context, token counts, latency, decision made — e.g. "wrote diary, reason=
reacting to owner chat") tagged with a correlation ID per scheduler tick;
a per-agent dashboard of action counts and cost over time to catch a
runaway/looping agent early; and an explicit audit log of every
`living_memory` write (what was stored, from which conversation) since that's
the one table where a bug has real privacy consequences.
