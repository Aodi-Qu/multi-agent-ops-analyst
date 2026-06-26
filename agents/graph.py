"""LangGraph state graph for the multi-agent ops analyst.

Flow:
  Router -> Executor -> Validator (loop back to Executor if invalid,
                                  interrupt to human if retries exhausted)
                    -> Summarizer -> END

Checkpoint is persisted via SqliteSaver with thread_id.
Supports Human-in-the-loop (HITL) via interrupt().
"""

import json
import asyncio
from typing import TypedDict, List, Literal, Optional, Any

from langgraph.graph import StateGraph, END
from langgraph.types import Command, interrupt
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from config import settings
from tools.sql_tool import execute_sql_query
from tools.rag_tool import retrieve_docs


# ===== 1. State =====

class AnalystState(TypedDict):
    """Shared state flowing through the graph."""
    messages: List[BaseMessage]      # 完整对话历史
    intent: str                      # "sql" | "rag" | "both"
    sql_query: str                   # 生成的 SQL 语句
    rag_query: str                   # RAG 检索问题
    sql_result: List[dict]           # 查询结果
    retrieved_docs: List[str]        # RAG 检索到的文档内容
    retry_count: int                 # 当前重试次数（初始 0）
    is_valid: bool                   # 校验结果


# ===== 2. Router 结构化输出 Schema =====

class IntentOutput(BaseModel):
    """Pydantic schema for structured LLM output in the Router node."""
    intent: Literal["sql", "rag", "both"] = Field(
        description="intent classification: sql=query data, rag=ask knowledge, both=both"
    )
    explanation: str = Field(description="classification reason")
    sql_query: str = Field(
        default="",
        description="complete SQLite SELECT for operation_metrics table "
                    "(SQLite syntax only, date is TEXT).",
    )
    rag_query: str = Field(
        default="",
        description="search question for knowledge base retrieval",
    )


# ===== 3. LLM & Parser =====

_llm_kwargs: dict[str, Any] = {
    "model": settings.LLM_MODEL,
    "temperature": 0,
    "openai_api_key": settings.OPENAI_API_KEY,
}
if settings.OPENAI_API_BASE:
    _llm_kwargs["openai_api_base"] = settings.OPENAI_API_BASE

llm = ChatOpenAI(**_llm_kwargs)
parser = PydanticOutputParser(pydantic_object=IntentOutput)


# ===== 4. Nodes =====

# -- 4a. Router Node --

ROUTER_SYSTEM_PROMPT: str = (
    "You are an intelligent ops analyst. Classify the user question into one of:\n"
    "- sql: user wants to query data from the database\n"
    "- rag: user asks about rules, standards, procedures\n"
    "- both: both data and knowledge are needed\n\n"
    "Database table: operation_metrics (SQLite, columns: id, date, product_line, revenue, cost, active_users)\n"
    "Use SQLite syntax only: date is TEXT (YYYY-MM-DD), use strftime() for date functions, no INTERVAL.\n"
    "Knowledge base covers: KPI standards, anomaly alert rules, product line ops details, runbooks.\n\n"
    "Output the structured format exactly as specified."
)


def router_node(state: AnalystState) -> dict:
    """Classify user intent with LLM + PydanticOutputParser."""
    last_user_msg: str = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            last_user_msg = msg.content
            break

    prompt_messages: List[BaseMessage] = [
        SystemMessage(content=ROUTER_SYSTEM_PROMPT),
        HumanMessage(
            content=f"User question: {last_user_msg}\n\n{parser.get_format_instructions()}"
        ),
    ]
    response: AIMessage = llm.invoke(prompt_messages)  # type: ignore[arg-type]
    parsed: IntentOutput = parser.invoke(response.content)

    sql_query: str = parsed.sql_query if parsed.intent in ("sql", "both") else ""
    rag_query: str = parsed.rag_query if parsed.intent in ("rag", "both") else last_user_msg

    return {
        "intent": parsed.intent,
        "sql_query": sql_query,
        "rag_query": rag_query,
        "sql_result": [],
        "retrieved_docs": [],
        "retry_count": 0,
        "is_valid": False,
        "messages": state["messages"] + [
            AIMessage(content=f"[Router] intent={parsed.intent}, reason={parsed.explanation}")
        ],
    }


# -- 4b. Executor Node --

def _parallel_execute(
    sql_query: str, rag_query: str
) -> tuple[List[dict], List[str]]:
    """Execute SQL and RAG in parallel via asyncio.gather."""
    async def _gather() -> tuple[Any, Any]:
        sql_coro = asyncio.to_thread(
            lambda: json.loads(execute_sql_query.invoke({"query": sql_query}))
        )
        rag_coro = asyncio.to_thread(
            lambda: retrieve_docs.invoke({"query": rag_query, "top_k": 3})
        )
        return await asyncio.gather(sql_coro, rag_coro)

    sql_result: Any = []
    rag_result: Any = []
    try:
        sql_result, rag_result = asyncio.run(_gather())
        if isinstance(sql_result, dict) and "error" in sql_result:
            sql_result = [sql_result]
        if not isinstance(sql_result, list):
            sql_result = [{"error": f"Unexpected type: {type(sql_result)}"}]
        if not isinstance(rag_result, list):
            rag_result = []
    except Exception as exc:
        sql_result = [{"error": str(exc)}]
        rag_result = []
    return sql_result, rag_result


def executor_node(state: AnalystState) -> dict:
    """Execute tools based on intent. On retry, regenerate queries via LLM."""
    intent: str = state["intent"]
    sql_query: str = state.get("sql_query", "")
    rag_query: str = state.get("rag_query", "")
    last_user_msg: str = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage) and "correction" not in msg.content.lower():
            last_user_msg = msg.content
            break

    # On retry, use LLM to regenerate queries with correction context
    if state["retry_count"] > 0:
        correction_prompt: str = (
            "Previous query results were invalid. Regenerate based on correction hints.\n"
            "Database: operation_metrics (id, date, product_line, revenue, cost, active_users).\n"
            f"Original question: {last_user_msg}\n"
            f"{parser.get_format_instructions()}"
        )
        prompt: List[BaseMessage] = [
            SystemMessage(content=ROUTER_SYSTEM_PROMPT),
            *state["messages"],
            HumanMessage(content=correction_prompt),
        ]
        response: AIMessage = llm.invoke(prompt)  # type: ignore[arg-type]
        parsed: IntentOutput = parser.invoke(response.content)
        sql_query = parsed.sql_query if intent in ("sql", "both") else ""
        rag_query = parsed.rag_query if intent in ("rag", "both") else last_user_msg

    # Execute tools
    sql_result: List[dict] = []
    retrieved_docs_list: List[str] = []

    if intent == "sql":
        raw = execute_sql_query.invoke({"query": sql_query})
        data = json.loads(raw)
        if isinstance(data, dict) and "error" in data:
            sql_result = [data]
        elif isinstance(data, list):
            sql_result = data
        else:
            sql_result = [{"error": f"Unexpected result type: {type(data)}"}]

    elif intent == "rag":
        docs = retrieve_docs.invoke({"query": rag_query, "top_k": 3})
        retrieved_docs_list = [d.get("content", "") for d in docs]

    elif intent == "both":
        sql_result, raw_docs = _parallel_execute(sql_query, rag_query)
        retrieved_docs_list = [d.get("content", "") for d in raw_docs]

    return {
        "sql_query": sql_query,
        "rag_query": rag_query,
        "sql_result": sql_result,
        "retrieved_docs": retrieved_docs_list,
    }


# -- 4c. Validator Node --

def validator_node(state: AnalystState) -> Command:
    """Validate results; loop back to Executor or interrupt for HITL."""
    intent: str = state["intent"]
    retry: int = state["retry_count"]
    messages: List[BaseMessage] = list(state["messages"])
    sql_valid: bool = True
    rag_valid: bool = True

    # SQL validation
    if intent in ("sql", "both"):
        sql_result = state.get("sql_result", [])
        if not sql_result:
            sql_valid = False
        elif len(sql_result) == 1 and "error" in sql_result[0]:
            sql_valid = False

        if not sql_valid:
            messages.append(
                HumanMessage(
                    content=(
                        "[Validator] SQL result invalid. Correct the statement "
                        "(table: operation_metrics, date format: YYYY-MM-DD)."
                    )
                )
            )

    # RAG validation
    if intent in ("rag", "both"):
        docs = state.get("retrieved_docs", [])
        non_empty = [d for d in docs if d.strip()]
        if not non_empty:
            rag_valid = False
            messages.append(
                HumanMessage(
                    content="[Validator] RAG retrieval returned empty. Rephrase the query."
                )
            )

    # Decide next step
    need_retry: bool = (not sql_valid or not rag_valid) and retry < 2

    if need_retry:
        return Command(
            goto="Executor",
            update={
                "messages": messages,
                "retry_count": retry + 1,
                "is_valid": False,
            },
        )

    # HITL: retries exhausted but still invalid
    if not sql_valid or not rag_valid:
        human_feedback: str = interrupt(
            "Validation failed after 2 retries. Provide correction "
            "(e.g., 'ignore and generate report' or 'modify SQL to 2026-04')."
        )
        messages.append(
            HumanMessage(content=f"[Human override] User command: {human_feedback}")
        )
        is_valid: bool = "ignore" in human_feedback.lower() or human_feedback.strip() == ""
        return Command(
            goto="Summarizer",
            update={"messages": messages, "is_valid": is_valid},
        )

    return Command(
        goto="Summarizer",
        update={"messages": messages, "is_valid": True},
    )


# -- 4d. Summarizer Node --

SUMMARIZER_SYSTEM_PROMPT: str = (
    "You are a senior ops data analyst. Write a clear analysis report in Chinese with:\n"
    "1. Key findings: core trends\n"
    "2. Detailed analysis: SQL data insights, knowledge base context\n"
    "3. Alerts & risks: any trigger conditions met\n"
    "4. Action recommendations\n\n"
    "Keep it professional and concise."
)


def summarizer_node(state: AnalystState) -> dict:
    """Integrate SQL results and RAG docs, generate analysis report."""
    context_parts: List[str] = []

    if state.get("sql_result"):
        context_parts.append("## SQL Query Results")
        context_parts.append(json.dumps(state["sql_result"], ensure_ascii=False, indent=2))

    if state.get("retrieved_docs"):
        context_parts.append("## Knowledge Base References")
        for i, doc in enumerate(state["retrieved_docs"], 1):
            content_preview = doc[:500] if doc else "(empty)"
            context_parts.append(f"### Doc {i}")
            context_parts.append(content_preview)

    context_str: str = "\n\n".join(context_parts) if context_parts else "(no data)"

    prompt: List[BaseMessage] = [
        SystemMessage(content=SUMMARIZER_SYSTEM_PROMPT),
        HumanMessage(content=f"Generate report from:\n\n{context_str}"),
    ]

    response: AIMessage = llm.invoke(prompt)  # type: ignore[arg-type]
    report: str = response.content  # type: ignore[assignment]

    return {
        "messages": state["messages"] + [AIMessage(content=report)],
        "is_valid": True,
    }


# ===== 5. Build & Compile =====

CHECKPOINT_DB: str = "./langgraph_checkpoints.db"


def build_graph() -> StateGraph:
    """Build and compile the LangGraph state graph with SqliteSaver."""
    workflow: StateGraph = StateGraph(AnalystState)

    workflow.add_node("Router",     router_node)
    workflow.add_node("Executor",   executor_node)
    workflow.add_node("Validator",  validator_node)
    workflow.add_node("Summarizer", summarizer_node)

    workflow.set_entry_point("Router")
    workflow.add_edge("Router",    "Executor")
    workflow.add_edge("Summarizer", END)
    workflow.add_edge("Executor",  "Validator")

    saver: MemorySaver = MemorySaver()
    return workflow.compile(checkpointer=saver)


graph: StateGraph = build_graph()




