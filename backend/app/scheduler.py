import asyncio
import hashlib
import logging
import random
from datetime import datetime, timezone

from . import config, db, llm
from .context_owner import build_owner_context, render_system_prompt as render_owner_prompt
from .context_public import build_public_context, render_system_prompt as render_public_prompt

logger = logging.getLogger("scheduler")

ACTIONS = {"diary", "status_update", "owner_message"}


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


def _pick_action(reason: str, action_override: str | None) -> str:
    if action_override:
        return action_override
    if reason == "manual trigger":
        return "diary"  # keep the manual-trigger demo path deterministic
    if reason == "reacting to a recent owner conversation":
        return random.choice(["owner_message", "diary"])
    return random.choice(["diary", "status_update"])


def _write_diary(agent: dict, reason: str) -> str:
    ctx = build_public_context(agent)
    system = render_public_prompt(agent, ctx) + (
        "\n\nWrite a single short diary entry (2-4 sentences, first person, present "
        f"reflection) for today. You are writing because: {reason}. Output ONLY the "
        "entry text itself — no scene-setting, no third-person narration, no stage "
        "directions, no addressing anyone directly. This is a private journal entry "
        "that happens to be posted publicly."
    )
    text = llm.complete(system, [{"role": "user", "content": "Write the entry."}], 300)
    row = db.insert("living_diary", {"agent_id": agent["id"], "text": text})
    logger.info("agent=%s action=diary reason=%s diary_id=%s", agent["name"], reason, row.get("id"))
    return text


def _update_status(agent: dict, reason: str) -> str:
    ctx = build_public_context(agent)
    system = render_public_prompt(agent, ctx) + (
        "\n\nWrite a short status update (3-8 words, present tense, in character) "
        f"describing what you're doing right now. You are updating it because: {reason}. "
        "Output ONLY the status text itself, no quotes, no punctuation at the end."
    )
    status = llm.complete(system, [{"role": "user", "content": "Write the status."}], 50)
    db.update("living_agents", {"id": agent["id"]}, {"status": status})
    db.insert("living_activity_events", {"agent_id": agent["id"], "event_type": "status_update", "content": status})
    logger.info("agent=%s action=status_update reason=%s status=%r", agent["name"], reason, status)
    return status


def _message_owner(agent: dict, reason: str) -> str:
    ctx = build_owner_context(agent)
    system = render_owner_prompt(agent, ctx) + (
        "\n\nProactively reach out to your owner — they haven't messaged you, you're "
        f"initiating this. You're doing so because: {reason}. Write a short (1-3 "
        "sentence) message in character, optionally referencing a private memory or "
        "something from your recent diary, the way a close companion checking in would. "
        "Output ONLY the message text itself."
    )
    text = llm.complete(system, [{"role": "user", "content": "Write the message."}], 200)
    db.insert("living_messages", {"agent_id": agent["id"], "sender_type": "owner", "role": "agent", "text": text})
    logger.info("agent=%s action=owner_message reason=%s", agent["name"], reason)
    return text


_HANDLERS = {"diary": _write_diary, "status_update": _update_status, "owner_message": _message_owner}


async def evaluate_and_act(agent: dict, force: bool = False, action_override: str | None = None) -> dict | None:
    if action_override and action_override not in ACTIONS:
        raise ValueError(f"unknown action {action_override!r}, must be one of {ACTIONS}")

    reason = _decide(agent["id"], force)
    if not reason:
        return None

    action = _pick_action(reason, action_override)
    text = await asyncio.to_thread(_HANDLERS[action], agent, reason)
    return {"action": action, "reason": reason, "text": text}


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
