"""
企业 API 服务（FastAPI）

提供：健康检查、JWT 登录/刷新、当前用户、订单查询（归属校验）、
      人工审批管理、会话转人工 stub。
认证：Bearer JWT；权限：RBAC（auth.rbac）。
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import text

from ..auth.deps import get_current_user
from ..auth.models import RefreshRequest, TokenRequest, TokenResponse, UserOut
from ..auth.rbac import require_role
from ..auth.service import authenticate, refresh_access
from ..database.db import get_engine, get_session_factory
from ..database.models import User
from ..database.repositories_async import ApprovalRepository, OrderRepository
from ..infra.context import Actor
from ..infra.metrics import setup_metrics
from ..tools.security import check_order_ownership


class ApprovalResolve(BaseModel):
    resolution: str  # approve / reject
    note: str = ""


class RAGUpload(BaseModel):
    content: str
    source: str = "upload"
    category: str = "manual"
    title: str = ""
    metadata: dict[str, Any] | None = None


class TransitionReq(BaseModel):
    to: str
    note: str = ""


class AddressChangeReq(BaseModel):
    order_id: str
    old_address: dict[str, Any] | None = None
    new_address: dict[str, Any] | None = None


def _approval_to_dict(a) -> dict[str, Any]:
    return {
        "id": a.id,
        "request_id": a.request_id,
        "order_id": a.order_id,
        "type": a.type,
        "status": a.status,
        "assignee_id": a.assignee_id,
        "approver_id": a.approver_id,
        "payload": a.payload,
        "sla_due_at": a.sla_due_at.isoformat() if a.sla_due_at else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
    }


def create_app() -> FastAPI:
    app = FastAPI(
        title="Customer Service Bot API",
        version="0.2.0",
        description="企业级多 Agent 智能客服系统 API",
    )

    # ── 健康检查 ──────────────────────────────────────────────────────
    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["ops"])
    async def ready() -> dict[str, str]:
        db_status = "ok"
        try:
            eng = get_engine()
            async with eng.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as e:  # noqa: BLE001
            db_status = f"error: {e}"
        from ..infra.redis_client import get_redis

        r = await get_redis()
        redis_status = "ok" if r is not None else "degraded(memory)"
        if db_status != "ok":
            raise HTTPException(status_code=503, detail=f"db={db_status} redis={redis_status}")
        return {"db": db_status, "redis": redis_status}

    # ── 认证 ──────────────────────────────────────────────────────────
    @app.post("/api/auth/login", response_model=TokenResponse, tags=["auth"])
    async def login(req: TokenRequest) -> TokenResponse:
        t = await authenticate(req.username, req.password)
        if not t:
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        return t

    @app.post("/api/auth/refresh", response_model=TokenResponse, tags=["auth"])
    async def refresh(req: RefreshRequest) -> TokenResponse:
        t = await refresh_access(req.refresh_token)
        if not t:
            raise HTTPException(status_code=401, detail="刷新令牌无效或已过期")
        return t

    @app.get("/api/auth/me", response_model=UserOut, tags=["auth"])
    async def me(user: User = Depends(get_current_user)) -> UserOut:
        return UserOut(
            id=user.id,
            username=user.username,
            role=user.role,
            display_name=user.display_name,
            customer_id=user.customer_id,
            is_active=user.is_active,
        )

    # ── 订单（归属校验）──────────────────────────────────────────────
    @app.get("/api/orders/{order_id}", tags=["orders"])
    async def get_order(order_id: str, user: User = Depends(get_current_user)) -> dict[str, Any]:
        factory = get_session_factory()
        async with factory() as s:
            order = await OrderRepository(s).get_by_id(order_id)
        if not order:
            raise HTTPException(status_code=404, detail="订单不存在")
        # 注入 Actor 做归属校验（与工具层一致）
        check_order_ownership(order, Actor(
            user_id=user.id, role=user.role, customer_id=user.customer_id,
            display_name=user.display_name, is_authenticated=True,
        ))
        return {"success": True, "data": order}

    # ── 人工审批 ─────────────────────────────────────────────────────
    @app.get("/api/admin/approvals", tags=["admin"])
    async def list_approvals(user: User = Depends(require_role("agent", "lead", "admin"))) -> list[dict[str, Any]]:
        factory = get_session_factory()
        async with factory() as s:
            tasks = await ApprovalRepository(s).list_pending()
        return [_approval_to_dict(t) for t in tasks]

    @app.post("/api/admin/approvals/{approval_id}/resolve", tags=["admin"])
    async def resolve_approval(
        approval_id: str,
        body: ApprovalResolve,
        user: User = Depends(require_role("agent", "lead", "admin")),
    ) -> dict[str, Any]:
        if body.resolution not in ("approve", "reject"):
            raise HTTPException(status_code=400, detail="resolution 必须为 approve 或 reject")
        factory = get_session_factory()
        async with factory() as s:
            repo = ApprovalRepository(s)
            status = "approved" if body.resolution == "approve" else "rejected"
            a = await repo.resolve(approval_id, status, user.id, body.note)
            if not a:
                raise HTTPException(status_code=404, detail="审批任务不存在")
            await s.commit()
        from ..infra.audit import audit

        await audit(action="approval", resource=f"approval:{approval_id}", after={"status": status, "by": user.id})
        return {"success": True, "data": _approval_to_dict(a)}

    # ── 会话转人工（stub）─────────────────────────────────────────────
    @app.post("/api/admin/sessions/{session_id}/takeover", tags=["admin"])
    async def takeover_session(
        session_id: str,
        user: User = Depends(require_role("agent", "lead", "admin")),
    ) -> dict[str, Any]:
        # P1：写 sessions.status=handoff + assigned_agent_id；P0 返回确认
        from ..infra.audit import audit

        await audit(action="session_takeover", resource=f"session:{session_id}", after={"by": user.id})
        return {"success": True, "session_id": session_id, "assigned_to": user.id, "status": "handoff"}

    # ── RAG 文档管理（上传/解析/切分/向量化/删除，验收1）──────────────
    @app.post("/api/admin/rag/documents", tags=["rag"])
    async def upload_rag_document(
        payload: RAGUpload,
        user: User = Depends(require_role("lead", "admin")),
    ) -> dict[str, Any]:
        from ..rag.indexer import DocumentManager

        dm = DocumentManager()
        doc_id = await dm.upload(
            source=payload.source, content=payload.content, category=payload.category,
            title=payload.title, metadata=payload.metadata,
        )
        # 异步向量化：ARQ_ASYNC=1 时走 worker，否则同步处理（可测）
        import os

        if os.getenv("ARQ_ASYNC") == "1":
            try:
                from arq import create_pool

                from ..tasks import WorkerSettings

                pool = await create_pool(WorkerSettings.redis_settings())
                await pool.enqueue_job("rag_index_document", doc_id)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[RAG] ARQ enqueue 失败，回退同步：{e}")
                await dm.process(doc_id)
        else:
            await dm.process(doc_id)
        from ..infra.audit import audit

        await audit(
            action="rag_upload", resource=f"doc:{doc_id}", after={"category": payload.category},
            actor=Actor(user_id=user.id, role=user.role, customer_id=user.customer_id,
                        display_name=user.display_name),
        )
        return {"success": True, "document_id": doc_id, "status": "ready"}

    @app.get("/api/admin/rag/documents", tags=["rag"])
    async def list_rag_documents(
        category: str | None = None,
        user: User = Depends(require_role("agent", "lead", "admin")),
    ) -> dict[str, Any]:
        from ..rag.indexer import DocumentManager

        docs = await DocumentManager().list_documents(category)
        return {"success": True, "data": docs, "count": len(docs)}

    @app.delete("/api/admin/rag/documents/{document_id}", tags=["rag"])
    async def delete_rag_document(
        document_id: str,
        user: User = Depends(require_role("lead", "admin")),
    ) -> dict[str, Any]:
        from ..rag.indexer import DocumentManager

        await DocumentManager().delete(document_id)
        return {"success": True, "document_id": document_id}

    # ── 退款状态机 transition（验收6）──────────────────────────────────
    @app.post("/api/admin/refunds/{request_id}/transition", tags=["approval"])
    async def refund_transition(
        request_id: str,
        payload: TransitionReq,
        user: User = Depends(require_role("agent", "lead", "admin")),
    ) -> dict[str, Any]:
        from ..approval.fsm import REFUND_TRANSITIONS, WorkflowError, next_states
        from ..database.repositories_async import RefundRequestRepository

        factory = get_session_factory()
        async with factory() as s:
            repo = RefundRequestRepository(s)
            try:
                rr = await repo.transition(request_id, payload.to, note=payload.note)
            except WorkflowError as e:
                raise HTTPException(status_code=400, detail=str(e)) from None
            if not rr:
                raise HTTPException(status_code=404, detail="退款申请不存在")
            await s.commit()
        from ..infra.audit import audit

        await audit(
            action="refund_transition", resource=f"refund:{request_id}",
            after={"to": payload.to, "by": user.id},
            actor=Actor(user_id=user.id, role=user.role, customer_id=user.customer_id,
                        display_name=user.display_name),
        )
        return {"success": True, "request_id": request_id, "status": payload.to,
                "next_states": next_states(payload.to, REFUND_TRANSITIONS)}

    # ── 改地址审批（ApprovalTask type=address_change，验收6）─────────
    @app.post("/api/admin/address-changes", tags=["approval"])
    async def create_address_change(
        payload: AddressChangeReq,
        user: User = Depends(require_role("agent", "lead", "admin")),
    ) -> dict[str, Any]:
        import uuid

        apr_id = f"APR-ADDR-{uuid.uuid4().hex[:12]}"
        factory = get_session_factory()
        async with factory() as s:
            await ApprovalRepository(s).create({
                "id": apr_id, "order_id": payload.order_id, "type": "address_change",
                "status": "requested",
                "payload": {"old_address": payload.old_address, "new_address": payload.new_address},
            })
            await s.commit()
        return {"success": True, "approval_task_id": apr_id, "status": "requested"}

    # Prometheus 指标（/metrics，验收8）
    setup_metrics(app)
    return app
