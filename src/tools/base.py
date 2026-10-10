from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from pydantic import BaseModel, Field


class ToolEnvelope(BaseModel):
    ok: bool
    data: Any | None = None
    error: str | None = None
    source: str
    tool_call_id: str = Field(default_factory=lambda: f"call_{uuid.uuid4().hex[:8]}")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


def make_tool_response(
    source: str,
    ok: bool,
    data: Any | None = None,
    error: str | None = None,
    tool_call_id: str | None = None,
) -> dict[str, Any]:
    cid = tool_call_id or f"call_{uuid.uuid4().hex[:8]}"
    ts = datetime.now(timezone.utc).isoformat()
    return {
        "ok": ok,
        "data": data,
        "error": error,
        "source": source,
        "tool_call_id": cid,
        "timestamp": ts,
    }
