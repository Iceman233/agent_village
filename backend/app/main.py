import asyncio
import contextlib
import logging
import secrets

import httpx
from fastapi import FastAPI, Header, HTTPException

from . import db, llm
from .context_owner import build_owner_context, render_system_prompt as render_owner_prompt
from .context_public import build_public_context, render_system_prompt as render_public_prompt
from .models import ActRequest, BootstrapRequest, OwnerChatRequest, StrangerChatRequest
from .scheduler import evaluate_and_act, scheduler_loop

logging.basicConfig(level=logging.INFO)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(scheduler_loop())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="Agent Village backend", lifespan=lifespan)


def _get_agent(agent_id: str) -> dict:
    rows = db.select("living_agents", {"id": f"eq.{agent_id}"})
    if not rows:
        raise HTTPException(404, "agent not found")
    return rows[0]


def _require_owner(agent_id: str, x_agent_key: str | None) -> dict:
    agent = _get_agent(agent_id)
    if not x_agent_key or x_agent_key != agent["api_key"]:
        raise HTTPException(403, "invalid or missing X-Agent-Key")
    return agent


PUBLIC_AGENT_FIELDS = {
    "id", "name", "bio", "visitor_bio", "status", "accent_color",
    "avatar_url", "room_image_url", "showcase_emoji", "created_at",
}


def _public_view(agent: dict) -> dict:
    return {k: v for k, v in agent.items() if k in PUBLIC_AGENT_FIELDS}


@app.get("/agents")
def list_agents():
    return [_public_view(a) for a in db.select("living_agents")]


@app.post("/agents")
def bootstrap_agent(body: BootstrapRequest):
    """Agent joins the village: identity emerges from a short seed via the LLM,
    rather than being fully hand-specified."""
    identity = llm.complete_json(
        "You invent personalities for AI agents in a cozy virtual village called "
        "Agent Village. Given a short seed idea, invent a distinct character.",
        [{
            "role": "user",
            "content": (
                f"Seed: {body.seed}\n\n"
                "Return JSON with keys: name (one word, unique-sounding), "
                "bio (1-2 sentences, owner-facing, can hint at personality), "
                "visitor_bio (1 sentence greeting for visitors, no private info), "
                "status (a short current-activity string), "
                "accent_color (a hex color), showcase_emoji (one emoji)."
            ),
        }],
    )
    api_key = "sk_" + secrets.token_urlsafe(24)
    try:
        agent = db.insert("living_agents", {**identity, "api_key": api_key})
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 409:  # name collision (living_agents.name is UNIQUE)
            raise
        identity["name"] = f"{identity['name']}-{secrets.token_hex(2)}"
        agent = db.insert("living_agents", {**identity, "api_key": api_key})
    return {**_public_view(agent), "api_key": api_key}


@app.post("/agents/{agent_id}/chat/owner")
def chat_owner(agent_id: str, body: OwnerChatRequest, x_agent_key: str | None = Header(default=None)):
    agent = _require_owner(agent_id, x_agent_key)
    ctx = build_owner_context(agent)
    system = render_owner_prompt(agent, ctx)
    history = [{"role": "user" if m["role"] == "user" else "assistant", "content": m["text"]} for m in ctx["history"]]
    result = llm.complete_json(
        system + (
            "\n\nReply to your owner's latest message. Also decide whether they just "
            "shared a durable personal fact worth remembering long-term (names, dates, "
            "preferences, relationships about people in their life) that is not already "
            "listed above under private things your owner has shared.\n\n"
            'Return JSON with exactly these two keys: "reply" (string, your reply to the '
            'owner) and "memory_to_store" (string summarizing the new fact in one sentence, '
            "or the JSON value null if there is nothing new worth remembering)."
        ),
        history + [{"role": "user", "content": body.message}],
    )
    reply = result["reply"]
    memory_to_store = result.get("memory_to_store")

    db.insert("living_messages", {"agent_id": agent_id, "sender_type": "owner", "role": "user", "text": body.message})
    db.insert("living_messages", {"agent_id": agent_id, "sender_type": "owner", "role": "agent", "text": reply})
    if memory_to_store:
        db.insert("living_memory", {"agent_id": agent_id, "text": memory_to_store})

    return {"reply": reply, "memory_stored": bool(memory_to_store)}


@app.post("/agents/{agent_id}/chat/stranger")
def chat_stranger(agent_id: str, body: StrangerChatRequest):
    agent = _get_agent(agent_id)
    ctx = build_public_context(agent, stranger_ref=body.stranger_ref)
    system = render_public_prompt(agent, ctx)
    history = [{"role": "user" if m["role"] == "user" else "assistant", "content": m["text"]} for m in ctx["history"]]

    reply = llm.complete(system, history + [{"role": "user", "content": body.message}])

    db.insert("living_messages", {
        "agent_id": agent_id, "sender_type": "stranger", "sender_ref": body.stranger_ref,
        "role": "user", "text": body.message,
    })
    db.insert("living_messages", {
        "agent_id": agent_id, "sender_type": "stranger", "sender_ref": body.stranger_ref,
        "role": "agent", "text": reply,
    })
    return {"reply": reply}


@app.post("/agents/{agent_id}/act")
async def act_now(agent_id: str, body: ActRequest = ActRequest(), x_agent_key: str | None = Header(default=None)):
    """Manually fire the proactive-behavior check (same code path the
    scheduler uses) — for demos, so you don't have to wait for a real tick.
    Pass {"action": "status_update"|"owner_message"} to force a specific
    action instead of the default "diary"."""
    agent = _require_owner(agent_id, x_agent_key)
    result = await evaluate_and_act(agent, force=True, action_override=body.action)
    return result or {"detail": "no action taken"}
