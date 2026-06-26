import httpx

from . import config

_HEADERS = {
    "apikey": config.SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json",
}

_client = httpx.Client(base_url=f"{config.SUPABASE_URL}/rest/v1", headers=_HEADERS, timeout=10)


def select(table: str, params: dict | None = None) -> list[dict]:
    r = _client.get(f"/{table}", params={"select": "*", **(params or {})})
    r.raise_for_status()
    return r.json()


def insert(table: str, data: dict) -> dict:
    r = _client.post(f"/{table}", json=data, headers={"Prefer": "return=representation"})
    r.raise_for_status()
    rows = r.json()
    return rows[0] if rows else {}


def latest(table: str, agent_id: str, extra_params: dict | None = None) -> dict | None:
    rows = select(
        table,
        {
            "agent_id": f"eq.{agent_id}",
            "order": "created_at.desc",
            "limit": "1",
            **(extra_params or {}),
        },
    )
    return rows[0] if rows else None
