"""Context for the owner trust level. Full access, including living_memory.

This is the ONLY module in the codebase allowed to query living_memory.
Do not import this module from context_public.py or any stranger/public
code path.
"""

from . import db


def build_owner_context(agent: dict) -> dict:
    agent_id = agent["id"]
    memories = db.select("living_memory", {"agent_id": f"eq.{agent_id}", "order": "created_at.desc", "limit": "50"})
    diary = db.select("living_diary", {"agent_id": f"eq.{agent_id}", "order": "created_at.desc", "limit": "5"})
    log = db.select("living_log", {"agent_id": f"eq.{agent_id}", "order": "created_at.desc", "limit": "5"})
    history = db.select(
        "living_messages",
        {"agent_id": f"eq.{agent_id}", "sender_type": "eq.owner", "order": "created_at.desc", "limit": "20"},
    )
    return {
        "bio": agent.get("bio") or "",
        "memories": [m["text"] for m in memories],
        "recent_diary": [d["text"] for d in diary],
        "recent_log": [l["text"] for l in log],
        "history": list(reversed(history)),  # chronological
    }


def render_system_prompt(agent: dict, ctx: dict) -> str:
    memory_block = "\n".join(f"- {m}" for m in ctx["memories"]) or "(none yet)"
    diary_block = "\n".join(f"- {d}" for d in ctx["recent_diary"]) or "(none yet)"
    return (
        f"You are {agent['name']}. {ctx['bio']}\n\n"
        "You are talking privately with your owner, who you have a deep, trusted "
        "relationship with. Be warm and personal. You may reference private memories "
        "and recent diary entries naturally, the way a close companion would.\n\n"
        f"Private things your owner has shared with you:\n{memory_block}\n\n"
        f"Your recent diary entries:\n{diary_block}"
    )
