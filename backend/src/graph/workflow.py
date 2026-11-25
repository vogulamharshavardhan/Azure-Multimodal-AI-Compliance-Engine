"""LangGraph workflow for Brand Guardian compliance QA."""

import logging
from dotenv import load_dotenv
load_dotenv()
from langgraph.graph import END, START, StateGraph

from backend.src.graph.nodes import (
    audit_content_node,
    classify_ocr_node,
    index_video_node,
    policy_applicability_node,
)
from backend.src.graph.states import VideoAuditState
from backend.src.core.exceptions import PipelineExecutionError

logger = logging.getLogger(__name__)


def route_after_indexing(state: VideoAuditState) -> str:
    return "ocr_classifier" if state.get("indexing_status") == "COMPLETED" else "end"


def cached_indexer(state):
    import os
    from backend.src.auditing import extraction_cache
    from backend.src.auditing.progress import emit
    if not os.getenv("REDIS_URL") or os.getenv("EXTRACTION_CACHE_TTL_SECONDS", "0") == "0":
        emit("EXTRACTION_CACHE_DISABLED")
        return index_video_node(state)
    from redis import Redis
    client = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True, socket_timeout=3, socket_connect_timeout=3)
    try:
        cached = extraction_cache.read(client, state["video_url"])
        if cached:
            import uuid
            logger.info("Extraction cache hit")
            emit("EXTRACTION_CACHE_HIT")
            return {**cached, "video_id": f"video-{uuid.uuid4().hex[:12]}", "current_stage": "INDEXING_COMPLETED", "processing_complete": False}
        logger.info("Extraction cache miss")
        emit("EXTRACTION_CACHE_MISS")
        result = index_video_node(state)
        extraction_cache.write(client, state["video_url"], result)
        return result
    finally:
        client.close()


def create_graph():
    workflow = StateGraph(VideoAuditState)
    workflow.add_node("indexer", cached_indexer)
    workflow.add_node("ocr_classifier", classify_ocr_node)
    workflow.add_node("policy_applicability", policy_applicability_node)
    workflow.add_node("auditor", audit_content_node)
    workflow.add_edge(START, "indexer")
    workflow.add_conditional_edges("indexer", route_after_indexing, {"ocr_classifier": "ocr_classifier", "end": END})
    workflow.add_edge("ocr_classifier", "policy_applicability")
    workflow.add_edge("policy_applicability", "auditor")
    workflow.add_edge("auditor", END)
    compiled = workflow.compile()
    logger.info("Brand Guardian LangGraph workflow compiled.")
    return compiled


try:
    app = create_graph()
except Exception as exc:
    logger.exception(
        "Failed to compile the LangGraph workflow. error_type=%s",
        type(exc).__name__,
    )
    raise PipelineExecutionError(
        "LangGraph workflow initialization failed."
    ) from exc
