"""RAG retrieval tool — keyword fallback (Chroma optional, with timeout)."""

from typing import Any
from langchain_core.tools import tool
from config import settings

KNOWLEDGE_DOCS: list[dict[str, str]] = [
    {
        "id": "kpi_overview",
        "title": "KPI Overview",
        "content": "Company product lines are evaluated on 4 KPIs: revenue growth, gross margin, active users (DAU/MAU), and retention rate. Mature products (smartphone, laptop): revenue growth 40%, gross margin 30%, active users 20%, retention 10%. Growth products (tablet): active users 40%, revenue growth 30%, gross margin 20%, retention 10%. Emerging products (wearable, smart home): active users & retention 30% each, revenue growth 25%, gross margin 15%.",
    },
    {
        "id": "anomaly_triggers",
        "title": "Anomaly Alert Triggers",
        "content": "Alerts triggered when: (1) Monthly revenue drops >10% MoM, root cause within 24h. (2) Revenue drops >5% YoY for 2 consecutive months, strategy review. (3) Gross margin falls 5pp below baseline, cost audit. (4) Active users drop >15% MoM, churn analysis. (5) Product line revenue share changes >20%, check data anomalies. Levels: yellow (monitor), orange (respond), red (emergency, respond within 1h).",
    },
    {
        "id": "smartphone_kpi",
        "title": "Smartphone Operations",
        "content": "Mature product. Monthly revenue target >5M, gross margin >35%. Active users: domestic >300K, overseas >150K. Key metrics: new launch sales, channel inventory turnover (<45 days), return rate (<3%), ASP trends. Anomaly: if sales <70% of forecast, channel stimulus; if return rate >5%, halt shipment.",
    },
    {
        "id": "laptop_kpi",
        "title": "Laptop Operations",
        "content": "Mature product. Monthly revenue target >3.5M, gross margin >30%. Active users >200K. Key: B2B order share (>30%), AOV (>6000 CNY). Anomaly: if B2B orders decline for 2 months, key account meeting; if gross margin <25%, review costs.",
    },
    {
        "id": "wearable_kpi",
        "title": "Wearable Operations",
        "content": "Emerging product. User growth >15% MoM, revenue >800K. Key: DAU/MAU stickiness (>25%), device activation (>80%), 30-day retention (>40%). Anomaly: if retention <30%, optimize onboarding; if activation <60%, review inventory.",
    },
    {
        "id": "smart_home_kpi",
        "title": "Smart Home Operations",
        "content": "Emerging product. Revenue >1.2M, devices/user >2.5. Key: cross-sell, app activity, CSAT (>85%). Anomaly: if device offline >10%, check cloud; if CSAT <75%, review support.",
    },
    {
        "id": "runbook_cost_overrun",
        "title": "Cost Overrun Runbook",
        "content": "When cost/revenue >80% (margin <20%): 1. Finance cost breakdown 48h. 2. Procurement renegotiates top-5 components. 3. Product SKU rationalization. 4. Ops optimizes scheduling. 5. Weekly review until margin >25%.",
    },
    {
        "id": "runbook_user_churn",
        "title": "User Churn Runbook",
        "content": "When active users drop >15% MoM: 1. Data churn profile 24h. 2. Growth re-engagement campaign. 3. Product check recent releases. 4. Support complaint hotspots. 5. Improvement plan within 1 week, A/B test.",
    },
]

_chroma_ready: bool = False
_chroma_attempted: bool = False


def _ensure_chroma() -> bool:
    global _chroma_ready, _chroma_attempted
    if _chroma_ready:
        return True
    if _chroma_attempted:
        return False
    _chroma_attempted = True

    import threading
    result = [False]

    def _try_init():
        try:
            import chromadb
            client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
            coll = client.get_or_create_collection(settings.CHROMA_COLLECTION_NAME)
            if coll.count() == 0:
                coll.add(
                    ids=[d["id"] for d in KNOWLEDGE_DOCS],
                    documents=[d["content"] for d in KNOWLEDGE_DOCS],
                    metadatas=[{"title": d["title"]} for d in KNOWLEDGE_DOCS],
                )
            result[0] = True
        except Exception as e:
            print(f"[Chroma] Init failed: {e}")

    t = threading.Thread(target=_try_init, daemon=True)
    t.start()
    t.join(timeout=10)
    _chroma_ready = result[0]
    print(f"[Chroma] {'Ready' if _chroma_ready else 'Unavailable, using keyword fallback'}")
    return _chroma_ready


def _keyword_search(query: str, top_k: int = 3) -> list[dict[str, Any]]:
    q = query.lower()
    scored = [(sum(1 for w in q.split() if w in d["content"].lower()), d) for d in KNOWLEDGE_DOCS]
    scored.sort(key=lambda x: -x[0])
    return [{"id": d["id"], "title": d["title"], "content": d["content"], "score": s / max(1, len(q.split()))}
            for s, d in scored[:top_k]]


@tool
def retrieve_docs(query: str, top_k: int = 3) -> list[dict[str, Any]]:
    """Retrieve operational KPI / runbook docs. Uses Chroma if available, else keyword fallback."""
    if not _ensure_chroma():
        return _keyword_search(query, top_k)

    import chromadb
    coll = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR).get_collection(settings.CHROMA_COLLECTION_NAME)
    results = coll.query(query_texts=[query], n_results=top_k)
    output = []
    for i in range(len((results.get("documents") or [[]])[0])):
        output.append({
            "id": (results.get("ids") or [[]])[0][i],
            "title": ((results.get("metadatas") or [[]])[0] or [{}])[i].get("title", ""),
            "content": (results.get("documents") or [[]])[0][i],
            "score": 1.0 - ((results.get("distances") or [[]])[0][i] if results.get("distances") else 0),
        })
    return output
