from pydantic import BaseModel


class BootstrapRequest(BaseModel):
    seed: str  # e.g. "a moody jazz musician who collects vinyl"


class OwnerChatRequest(BaseModel):
    message: str


class StrangerChatRequest(BaseModel):
    message: str
    stranger_ref: str  # caller-supplied handle, no auth — just keys conversation threads
