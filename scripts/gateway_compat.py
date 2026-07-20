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


class GatewayToolCall(BaseModel):
    id: str = ""
    name: str = ""       # MCP plugin sends "name" in toolCalls
    arguments: str = ""  # MCP plugin sends "arguments" as a string
    type: str = "function"


class GatewayMessage(BaseModel):
    role: str = "user"
    content: str = ""
    timestamp: int = 0
    toolCalls: list[GatewayToolCall] | None = None
    toolCallId: str | None = None


def _map_gateway_message(m: GatewayMessage, sender_id: str) -> MessageItemDTO:
    """Map Gateway camelCase message format to EverOS MessageItemDTO."""
    tool_calls = None
    if m.toolCalls:
        tool_calls = [
            {"id": tc.id, "type": tc.type or "function",
             "function": {"name": tc.name, "arguments": tc.arguments}}
            for tc in m.toolCalls
        ]
    return MessageItemDTO(
        sender_id=sender_id,
        role=m.role,
        timestamp=m.timestamp or 0,
        content=m.content,
        tool_calls=tool_calls,
        tool_call_id=m.toolCallId,
    )


class GatewayPersonalRequest(BaseModel):
    conversationId: str = "default"
    messages: list[GatewayMessage] = Field(default_factory=list)
    flush: bool = True


class GatewayAgentMemoryRequest(BaseModel):
    conversationId: str = "default"
    messages: list[GatewayMessage] = Field(default_factory=list)
    flush: bool = True


class GatewaySearchRequest(BaseModel):
    query: str = ""
    topK: int = 5
    rankBy: str | None = None
    filter: dict | None = None
    memoryTypes: list[str] | None = None
    forceRefresh: bool = False


class GatewayContextRequest(BaseModel):
    forceRefresh: bool = False


def _gw_ok(request_id: str, result: Any = None) -> JSONResponse:
    """Return a Gateway-compatible success envelope."""
    return JSONResponse({"status": 0, "requestId": request_id, "result": result})


@router.post("/search")
async def mem_search(req: GatewaySearchRequest, request: Request):
    everos_req = SearchRequest(
        user_id=DEFAULT_USER_ID,
        app_id=DEFAULT_APP_ID,
        project_id=DEFAULT_PROJECT_ID,
        query=req.query,
        top_k=req.topK or 5,
    )
    result = await search(everos_req)
    inner = result.model_dump(mode="json")
    data = inner.get("data", {})
    if "episodes" in data:
        data["items"] = data.pop("episodes")
    return _gw_ok(result.request_id, data)


@router.post("/context")
async def mem_context(req: GatewayContextRequest, request: Request):
    everos_req = GetRequest(
        memory_type="profile",
        user_id=DEFAULT_USER_ID,
        app_id=DEFAULT_APP_ID,
        project_id=DEFAULT_PROJECT_ID,
        page=1,
    )
    result = await get_service(everos_req)
    inner = result.model_dump(mode="json")
    return _gw_ok(result.request_id, inner.get("data", {}))


@router.post("/personal")
async def mem_personal(req: GatewayPersonalRequest, request: Request):
    request_id = extract_request_id(request)
    everos_req = MemorizeAddRequest(
        session_id=req.conversationId or "default",
        app_id=DEFAULT_APP_ID,
        project_id=DEFAULT_PROJECT_ID,
        messages=[_map_gateway_message(m, DEFAULT_USER_ID) for m in req.messages],
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
        messages=[_map_gateway_message(m, DEFAULT_USER_ID) for m in req.messages],
    )
    result = await memorize(everos_req.model_dump())
    return _gw_ok(request_id, {
        "messageCount": result.message_count,
        "flushed": req.flush,
        "status": result.status,
    })
