"""ALAS-style versioned WebSocket request envelope."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class RequestEnvelope(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    v: Literal[1] = 1
    type: Literal['request'] = 'request'
    id: int | str
    method: str = Field(min_length=1, max_length=80)
    params: dict = Field(default_factory=dict)
