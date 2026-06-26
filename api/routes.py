"""FastAPI route definitions — invoke, SSE streaming, and HITL resume."""

import asyncio
import json
from uuid import uuid4
from typing import AsyncGenerator, Any

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage
from langgraph.types import Command as LangGraphCommand

from agents.graph import graph

router = APIRouter(prefix="/api/v1", tags=["analyst"])


# ═══════════════════════════════════════════════════════════════════════
#  Schemas
# ═══════════════════════════════════════════════════════════════════════

class InvokeRequest(BaseModel):
    question: str = Field(..., min_length=1, description="自然语言运维问题")
    thread_id: str | None = Field(None, description="可选线程 ID，不传则自动生成 UUID")


class ResumeRequest(BaseModel):
    command: str = Field(..., min_length=1, description="人工修正指令")


# ═══════════════════════════════════════════════════════════════════════
#  Thread session manager (in-memory)
# ═══════════════════════════════════════════════════════════════════════

class ThreadSession:
    """Orchestrates a single graph execution with SSE event streaming + HITL."""

    def __init__(self, question: str, thread_id: str):
        self.question = question
        self.thread_id = thread_id
        self.event_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=500)
        self.resume_queue: asyncio.Queue[str] = asyncio.Queue()
        self.final_result: dict[str, Any] | None = None
        self.error: str | None = None
        self.is_done: bool = False
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start the graph execution in a background asyncio task."""
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        """Internal loop: run astream_events, handle interrupts, collect results."""
        config: dict[str, Any] = {"configurable": {"thread_id": self.thread_id}}
        input_data: dict[str, Any] | LangGraphCommand = {
            "messages": [HumanMessage(content=self.question)]
        }

        try:
            while True:
                # Stream events from the graph
                async for event in graph.astream_events(
                    input_data, config, version="v2"
                ):
                    await self.event_queue.put(event)

                # Check whether the graph paused (interrupt) or finished
                snap = await graph.aget_state(config)
                if not snap.next:
                    # Normal completion
                    self.final_result = snap.values
                    break

                # Graph is waiting for human input via interrupt()
                await self.event_queue.put({"__type__": "interrupt"})
                resume_value: str = await self.resume_queue.get()
                input_data = LangGraphCommand(resume=resume_value)

        except Exception as exc:
            self.error = str(exc)
            await self.event_queue.put({"__type__": "error", "data": str(exc)})
        finally:
            self.is_done = True
            await self.event_queue.put({"__type__": "done"})

    async def resume(self, command: str) -> None:
        """Provide human feedback to resume an interrupted graph."""
        await self.resume_queue.put(command)


# In-memory sessions (lost on restart — suitable for development)
_sessions: dict[str, ThreadSession] = {}


def _get_session(thread_id: str) -> ThreadSession:
    if thread_id not in _sessions:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
    return _sessions[thread_id]


# ═══════════════════════════════════════════════════════════════════════
#  SSE event formatter
# ═══════════════════════════════════════════════════════════════════════

_NODE_LABELS: dict[str, str] = {
    "Router":     "🔍 路由分析",
    "Executor":   "⚙️ 执行查询",
    "Validator":  "✅ 校验结果",
    "Summarizer": "📊 生成报告",
}


def _format_langgraph_event(raw: dict[str, Any]) -> dict | None:
    """Map a LangGraph astream_events event to a user-friendly SSE payload.

    Returns a dict with keys ``event`` and ``data``, or ``None`` to skip.
    """
    kind: str = raw.get("event", "")
    name: str = raw.get("name", "")
    data: Any = raw.get("data", {})

    # Node lifecycle
    if kind == "on_chain_start" and name in _NODE_LABELS:
        return {"event": "status", "data": f"{_NODE_LABELS[name]}..."}
    if kind == "on_chain_end" and name in _NODE_LABELS:
        return {"event": "status", "data": f"  ✔ {_NODE_LABELS[name]} 完成"}

    # LLM calls
    if kind == "on_chat_model_start":
        return {"event": "status", "data": "🧠 LLM 推理中..."}
    if kind == "on_chat_model_end":
        return {"event": "status", "data": "  ✔ LLM 推理完成"}

    # Tool calls
    if kind == "on_tool_start":
        tool: str = name or "未知工具"
        return {"event": "status", "data": f"🔧 调用工具: {tool}"}
    if kind == "on_tool_end":
        tool = name or "未知工具"
        return {"event": "status", "data": f"  ✔ 工具返回: {tool}"}

    return None  # skip uninteresting events


def _build_sse_event(
    internal: dict[str, Any],
) -> dict[str, str] | None:
    """Convert an internal queue item into an SSE-compatible dict."""
    type_ = internal.get("__type__")

    # Control signals
    if type_ == "done":
        result_json: str = json.dumps(
            _sessions.get("", {}),  # placeholder — actual result below
            ensure_ascii=False,
            default=str,
        )
        return {
            "event": "done",
            "data": "报告生成完成",
        }
    if type_ == "error":
        return {"event": "error", "data": internal.get("data", "未知错误")}
    if type_ == "interrupt":
        return {"event": "interrupt", "data": "✋ 需要人工干预，请调用 POST /resume 提供指令"}

    # Normal LangGraph event
    formatted = _format_langgraph_event(internal)
    return formatted


# ═══════════════════════════════════════════════════════════════════════
#  Endpoints
# ═══════════════════════════════════════════════════════════════════════

@router.post("/invoke")
async def invoke(req: InvokeRequest):
    """Start a graph execution in the background.

    Returns immediately with ``thread_id``.  Client should then open
    a SSE connection to ``GET /stream/{thread_id}``.
    """
    thread_id: str = req.thread_id or str(uuid4())
    session = ThreadSession(question=req.question, thread_id=thread_id)
    _sessions[thread_id] = session
    session.start()
    return {"thread_id": thread_id, "status": "processing"}


@router.get("/stream/{thread_id}")
async def stream_events(thread_id: str):
    """SSE endpoint that streams graph execution events in real time."""
    session: ThreadSession = _get_session(thread_id)

    async def _event_stream() -> AsyncGenerator[dict[str, str], None]:
        try:
            while True:
                internal: dict[str, Any] = await session.event_queue.get()

                # ── done → yield final result then exit ──
                if internal.get("__type__") == "done":
                    final = session.final_result or {}
                    # Extract the last AIMessage (analysis report)
                    messages = final.get("messages", [])
                    report: str = ""
                    for msg in reversed(messages):
                        if hasattr(msg, "type") and msg.type == "ai":
                            report = getattr(msg, "content", "")
                            break
                    yield {
                        "event": "result",
                        "data": json.dumps(
                            {"report": report, "sql_used": final.get("sql_query", ""),"sql_result": final.get("sql_result", []),"retrieved_docs": final.get("retrieved_docs", [])},
                            ensure_ascii=False,
                            default=str,
                        ),
                    }
                    break

                # ── error ──
                if internal.get("__type__") == "error":
                    yield {"event": "error", "data": internal.get("data", "Unknown error")}
                    break

                # ── interrupt ──
                if internal.get("__type__") == "interrupt":
                    yield {"event": "interrupt", "data": "✋ 等待人工干预..."}
                    # Keep the connection open; new events will arrive after resume
                    continue

                # ── Regular LangGraph event ──
                formatted = _format_langgraph_event(internal)
                if formatted:
                    yield formatted

        except asyncio.CancelledError:
            pass

    return EventSourceResponse(_event_stream())


@router.post("/resume/{thread_id}")
async def resume(thread_id: str, req: ResumeRequest):
    """Resume an interrupted graph execution with a human command."""
    session: ThreadSession = _get_session(thread_id)
    if session.is_done:
        raise HTTPException(status_code=400, detail="Thread already finished")
    await session.resume(req.command)
    return {"thread_id": thread_id, "status": "resumed"}


@router.get("/health")
async def health():
    """Simple health check."""
    return {"status": "ok"}
