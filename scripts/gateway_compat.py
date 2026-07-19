"""EverMe Gateway API compatibility routes for local EverOS.

Maps Gateway paths (/api/v1/mem/*) to local EverOS (/api/v1/memory/*)
and translates BOTH request payloads AND response envelopes.

Gateway expects:  {"status": 0, "requestId": "...", "result": {...}}
EverOS returns:   {"request_id": "...", "data": {...}}
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from everos.entrypoints.api.routes.memorize import (
    MemorizeAddRequest,
    MessageItemDTO,
)
from everos.entrypoints.api.routes.search import SearchRequest
from everos.entrypoints.api.utils import extract_request_id
from everos.memory.get import GetRequest
from everos.service import memorize, search, get as get_service

router = APIRouter(prefix="/api/v1/mem", tags=["gateway-compat"])

DEFAULT_APP_ID = "opencode"
DEFAULT_PROJECT_ID = "noctua"
DEFAULT_USER_ID = "mengzhilu"


class GatewayMessage(BaseModel):
    role: str = "user"
    content: str = ""
    timestamp: int = 0


class GatewayPersonalRequest(BaseModel):
    conversationId: str = "default"
    messages: list[GatewayMessage] = Field(default_factory=list)
    flush: bool = True


class GatewayAgentMemoryRequest(BaseModel):
    conversationId: str = "default"
    messages: list[GatewayMessage] = Field(default_factory=list)
    flush: bool = True


def _gw_ok(request_id: str, result: Any = None) -> JSONResponse:
    """Return a Gateway-compatible success envelope."""
    return JSONResponse({"status": 0, "requestId": request_id, "result": result})


@router.post("/search")
async def mem_search(req: SearchRequest, request: Request):
    result = await search(req)
    inner = result.model_dump()
    return _gw_ok(result.request_id, inner.get("data", {}))


@router.post("/context")
async def mem_context(req: GetRequest, request: Request):
    result = await get_service(req)
    inner = result.model_dump()
    return _gw_ok(result.request_id, inner.get("data", {}))


@router.post("/personal")
async def mem_personal(req: GatewayPersonalRequest, request: Request):
    request_id = extract_request_id(request)
    everos_req = MemorizeAddRequest(
        session_id=req.conversationId or "default",
        app_id=DEFAULT_APP_ID,
        project_id=DEFAULT_PROJECT_ID,
        messages=[
            MessageItemDTO(
                sender_id=DEFAULT_USER_ID,
                role=m.role,
                timestamp=m.timestamp or 0,
                content=m.content,
            )
            for m in req.messages
        ],
    )
    result = await memorize(everos_req.model_dump())
    return _gw_ok(request_id, {
        "messageCount": result.message_count,
        "flushed": req.flush,
        "status": result.status,
    })


@router.post("/agent-memory")
async def mem_agent_memory(req: GatewayAgentMemoryRequest, request: Request):
    request_id = extract_request_id(request)
    everos_req = MemorizeAddRequest(
        session_id=req.conversationId or "default",
        app_id=DEFAULT_APP_ID,
        project_id=DEFAULT_PROJECT_ID,
        messages=[
            MessageItemDTO(
                sender_id=DEFAULT_USER_ID,
                role=m.role,
                timestamp=m.timestamp or 0,
                content=m.content,
            )
            for m in req.messages
        ],
    )
    result = await memorize(everos_req.model_dump())
    return _gw_ok(request_id, {
        "messageCount": result.message_count,
        "flushed": req.flush,
        "status": result.status,
    })
