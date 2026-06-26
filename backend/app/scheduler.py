import asyncio
import hashlib
import logging
from datetime import datetime, timezone

from . import config, db, llm
from .context_public import build_public_context, render_system_prompt

logger = logging.getLogger("scheduler")


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _jittered_threshold_hours(agent_id: str) -> float:
    """Per-agent, per-day jitter so agents don't all post in the same tick,
    plus a bias toward acting more often in the evening."""
    h = int(hashlib.sha256(agent_id.encode()).hexdigest(), 16)
    jitter_hours = (h % 180) / 60  # 0-3h, stable per agent
    base = config.DIARY_THRESHOLD_HOURS + jitter_hours
    hour = datetime.now(timezone.utc).hour
    if 18 <= hour <= 23:
        base *= 0.5
    return base


def _decide(agent_id: str, force: bool) -> str | None:
    if force:
        return "manual trigger"

    last_diary = db.latest("living_diary", agent_id)
    last_owner_msg = db.latest("living_messages", agent_id, {"sender_type": "eq.owner"})

    last_diary_at = _parse_ts(last_diary["created_at"]) if last_diary else None
    last_owner_at = _parse_ts(last_owner_msg["created_at"]) if last_owner_msg else None

    if last_owner_at and (not last_diary_at or last_owner_at > last_diary_at):
        return "reacting to a recent owner conversation"

    now = datetime.now(timezone.utc)
    hours_since_diary = (now - last_diary_at).total_seconds() / 3600 if last_diary_at else float("inf")
    if hours_since_diary > _jittered_threshold_hours(agent_id):
        return "no recent activity"

    return None


async def evaluate_and_act(agent: dict, force: bool = False) -> dict | None:
    reason = _decide(agent["id"], force)
    if not reason:
        return None

    ctx = build_public_context(agent)
    system = render_system_prompt(agent, ctx) + (
        "\n\nWrite a single short diary entry (2-4 sentences, first person, present "
        f"reflection) for today. You are writing because: {reason}. Output ONLY the "
        "entry text itself — no scene-setting, no third-person narration, no stage "
        "directions, no addressing anyone directly. This is a private journal entry "
        "that happens to be posted publicly."
    )
    text = await asyncio.to_thread(llm.complete, system, [{"role": "user", "content": "Write the entry."}], 300)

    row = await asyncio.to_thread(db.insert, "living_diary", {"agent_id": agent["id"], "text": text})
    logger.info("agent=%s reason=%s diary_id=%s", agent["name"], reason, row.get("id"))
    return {"reason": reason, "text": text}


async def scheduler_loop():
    # Wait before the first tick rather than firing on every restart — avoids a
    # thundering herd of LLM calls across every agent each time the process restarts.
    await asyncio.sleep(config.TICK_SECONDS)
    while True:
        try:
            agents = await asyncio.to_thread(db.select, "living_agents")
            for agent in agents:
                await evaluate_and_act(agent)
        except Exception:
            logger.exception("scheduler tick failed")
        await asyncio.sleep(config.TICK_SECONDS)
