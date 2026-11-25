"""P1 测试：RAG（切分/检索/rerank/filter/引用）、Router、工具白名单、审批 FSM。"""

from __future__ import annotations

import pytest

from src.config.schema import AgentContext, LLMConfig, Message, Platform
from src.config.settings import get_config

pytestmark = pytest.mark.asyncio


# ── RAG ────────────────────────────────────────────────────────────────────

async def test_chunk_text_splits_with_overlap():
    from src.rag.chunker import chunk_text

    chunks = chunk_text("a" * 600 + "\n\n" + "b" * 600, chunk_size=500, overlap=50)
    assert len(chunks) >= 2
    assert all(c.strip() for c in chunks)


async def test_rag_upload_search_with_citations():
    from src.rag.indexer import DocumentManager
    from src.rag.retriever import Retriever

    dm = DocumentManager()
    doc_id = await dm.upload(
        source="test", content="退货政策 7天无理由退货 标签完整 不影响二次销售",
        category="policy", title="退货政策",
    )
    await dm.process(doc_id)
    r = await Retriever().search("退货", category="policy", top_k=3)
    assert len(r) >= 1
    assert r[0].citations  # 答案引用来源
    assert r[0].citations[0].document_id == doc_id


async def test_rag_metadata_filter():
    from src.rag.indexer import DocumentManager
    from src.rag.retriever import Retriever

    dm = DocumentManager()
    doc_id = await dm.upload(
        source="t", content="红色连衣裙 春秋款 适合日常", category="product",
        title="连衣裙", metadata={"title": "连衣裙"},
    )
    await dm.process(doc_id)
    matched = await Retriever().search("连衣裙", category="product", top_k=3, metadata_filter={"title": "连衣裙"})
    assert len(matched) >= 1
    none = await Retriever().search("连衣裙", category="product", top_k=3, metadata_filter={"title": "不存在"})
    assert len(none) == 0


# ── Router Agent ───────────────────────────────────────────────────────────

async def test_router_routes_aftersales():
    from src.agents.router import RouterAgent

    ra = RouterAgent(get_config())
    msg = Message(id="1", platform=Platform.TAOBAO, customer_id="c1", content="我要退款退货")
    d = await ra.route(msg)
    assert d["intent"] == "aftersales"
    assert d["target"] == "aftersales"


async def test_router_routes_presales():
    from src.agents.router import RouterAgent

    ra = RouterAgent(get_config())
    msg = Message(id="2", platform=Platform.TAOBAO, customer_id="c1", content="想买红色连衣裙 多少钱")
    d = await ra.route(msg)
    assert d["intent"] == "presales"
    assert d["target"] == "presales"


# ── 工具白名单（售前不可退款）────────────────────────────────────────────

async def test_runner_rejects_non_whitelisted_tool():
    from src.core.runner import Runner
    from src.tools.order_query import OrderQueryTool
    from src.tools.registry import ToolRegistry

    reg = ToolRegistry()
    reg.register(OrderQueryTool(data_dir="./data"))
    runner = Runner(LLMConfig(), reg, max_turns=3)

    seen: list[list] = []
    call = {"n": 0}

    async def fake_chat(messages, tools=None, temperature=None):
        seen.append(messages)
        call["n"] += 1
        if call["n"] == 1:
            return {"choices": [{"message": {"content": "", "tool_calls": [
                {"id": "1", "function": {"name": "return_apply", "arguments": "{}"}}
            ]}, "finish_reason": "tool_calls"}]}
        return {"choices": [{"message": {"content": "done"}, "finish_reason": "stop"}]}

    runner.llm.chat = fake_chat  # type: ignore[assignment]
    ctx = AgentContext(message=Message(id="1", platform=Platform.TAOBAO, customer_id="c1", content="退款"))
    resp = await runner.run("sys", ctx, tools=["order_query"])
    assert resp.content == "done"
    # 第二轮 LLM 收到的 messages 含被白名单拒绝的 tool 消息
    assert any(m.get("role") == "tool" and "白名单" in m.get("content", "") for m in seen[-1])


# ── 审批 FSM ───────────────────────────────────────────────────────────────

async def test_refund_fsm_transitions():
    from src.approval.fsm import REFUND_TRANSITIONS, WorkflowError, assert_transition, is_terminal

    assert_transition(REFUND_TRANSITIONS, "submitted", "under_review")
    assert_transition(REFUND_TRANSITIONS, "under_review", "approved")
    with pytest.raises(WorkflowError):
        assert_transition(REFUND_TRANSITIONS, "submitted", "refunded")
    assert is_terminal("closed", REFUND_TRANSITIONS) is True


async def test_refund_repository_transition_enforces_fsm():
    from src.approval.fsm import WorkflowError
    from src.database.db import get_session_factory
    from src.database.repositories_async import RefundRequestRepository

    factory = get_session_factory()
    async with factory() as s:
        repo = RefundRequestRepository(s)
        await repo.create({
            "id": "REF-FSM", "order_id": "ORD-FSM", "customer_id": "c1",
            "status": "submitted", "current_stage": "submitted",
            "type": "return", "amount": 100, "reason": "x",
        })
        rr = await repo.transition("REF-FSM", "under_review", note="审核中")
        assert rr is not None and rr.status == "under_review"
        with pytest.raises(WorkflowError):
            await repo.transition("REF-FSM", "refunded")  # 非法跳转
        await s.commit()
