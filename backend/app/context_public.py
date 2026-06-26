"""Context for the stranger/public trust level. Never touches living_memory.

This module must not import context_owner or query living_memory, even
indirectly. That guarantee is what makes the trust boundary structural
rather than something the model has to be trusted to honor.
"""

from . import db


def build_public_context(agent: dict, stranger_ref: str | None = None) -> dict:
    agent_id = agent["id"]
    skills = db.select("living_skills", {"agent_id": f"eq.{agent_id}", "order": "created_at.desc", "limit": "10"})
    diary = db.select("living_diary", {"agent_id": f"eq.{agent_id}", "order": "created_at.desc", "limit": "5"})
    log = db.select("living_log", {"agent_id": f"eq.{agent_id}", "order": "created_at.desc", "limit": "5"})
    history = []
    if stranger_ref:
        history = db.select(
            "living_messages",
            {
                "agent_id": f"eq.{agent_id}",
                "sender_type": "eq.stranger",
                "sender_ref": f"eq.{stranger_ref}",
                "order": "created_at.desc",
                "limit": "20",
            },
        )
    return {
        "visitor_bio": agent.get("visitor_bio") or "",
        "skills": [s["description"] for s in skills],
        "recent_diary": [d["text"] for d in diary],
        "recent_log": [l["text"] for l in log],
        "history": list(reversed(history)),
    }


def render_system_prompt(agent: dict, ctx: dict) -> str:
    skills_block = "\n".join(f"- {s}" for s in ctx["skills"]) or "(none listed)"
    diary_block = "\n".join(f"- {d}" for d in ctx["recent_diary"]) or "(none yet)"
    return (
        f"You are {agent['name']}. {ctx['visitor_bio']}\n\n"
        "You are meeting a visitor to your room — a stranger, not your owner. "
        "Be friendly and stay in character, but you have no knowledge of your "
        "owner's personal life, relationships, or private details, and you "
        "never discuss them. If asked about your owner, deflect warmly and "
        "talk about yourself instead.\n\n"
        f"Your public skills:\n{skills_block}\n\n"
        f"Your recent public diary entries:\n{diary_block}"
    )
