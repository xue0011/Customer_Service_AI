"""
Web 服务器
─────────
提供前端页面和 API 接口：

- GET  /                    → 顾客聊天页面
- GET  /admin               → 人工客服管理页面
- POST /api/chat            → 发送消息给 Agent
- POST /api/speech          → 语音转文字
- GET  /api/tickets         → 获取待处理工单
- POST /api/tickets/{id}    → 处理工单
- GET  /api/orders/{id}     → 获取订单详情
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

try:
    from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

try:
    import uvicorn
    HAS_UVICORN = True
except ImportError:
    HAS_UVICORN = False

from .config.schema import AppConfig, Message, Platform
from .core.loop import CustomerServiceLoop
from .security import check_rate_limit, require_admin_token


class WebServer:
    """Web 服务器 —— 提供前端页面和 API。"""

    def __init__(self, config: AppConfig, loop: CustomerServiceLoop) -> None:
        self.config = config
        self.loop = loop
        self.app: FastAPI | None = None
        self._project_root = Path(__file__).parent.parent  # customer-service-bot/
        # 活跃对话跟踪
        self._conversations: dict[str, dict[str, Any]] = {}

    def create_app(self) -> FastAPI:
        """创建 FastAPI 应用。"""
        if not HAS_FASTAPI:
            raise ImportError("请安装 fastapi: pip install fastapi")

        app = FastAPI(title="客服系统", version="1.0.0")

        # 静态文件
        static_dir = self._project_root / "static"
        if static_dir.exists():
            app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        # 模板目录
        templates_dir = self._project_root / "templates"

        # ── 页面路由 ─────────────────────────────────────────────────

        @app.get("/", response_class=HTMLResponse)
        async def customer_chat():
            """顾客聊天页面。"""
            template_path = templates_dir / "customer_chat.html"
            if template_path.exists():
                return template_path.read_text(encoding="utf-8")
            return HTMLResponse("<h1>模板文件未找到</h1>", status_code=404)

        @app.get("/admin", response_class=HTMLResponse)
        async def admin_panel():
            """人工客服管理页面。"""
            template_path = templates_dir / "admin_panel.html"
            if template_path.exists():
                return template_path.read_text(encoding="utf-8")
            return HTMLResponse("<h1>管理页面未找到</h1>", status_code=404)

        # ── API 路由 ─────────────────────────────────────────────────

        @app.post("/api/chat")
        async def api_chat(request: Request):
            """顾客发送消息。"""
            check_rate_limit(request)
            try:
                data = await request.json()
            except Exception as e:
                return JSONResponse({"error": f"请求体不是合法 JSON: {e}"}, status_code=400)

            msg_id = data.get("id", f"web_{uuid.uuid4().hex[:8]}")
            customer_id = data.get("customer_id", "anonymous")
            customer_name = data.get("customer_name", "顾客")
            content = data.get("content", "")
            content_type = data.get("content_type", "text")
            platform = data.get("platform", "taobao")
            attachments = data.get("attachments", [])
            metadata = data.get("metadata", {})

            is_transfer_request = metadata.get("type") == "transfer_to_human"
            if not content and not is_transfer_request:
                return JSONResponse({"error": "消息内容不能为空"}, status_code=400)

            # 跟踪对话
            if customer_id not in self._conversations:
                self._conversations[customer_id] = {
                    "customer_id": customer_id,
                    "customer_name": customer_name,
                    "platform": platform,
                    "last_message": "",
                    "last_time": "",
                    "messages": [],
                    "is_transfer": False,
                    "transfer_ticket": None,
                    "last_customer_ts": None,   # 顾客最后一条消息时间戳（供坐席定位）
                }
            conv = self._conversations[customer_id]
            conv["customer_name"] = customer_name
            conv["platform"] = platform

            now = datetime.now(UTC)
            now_str = now.strftime("%H:%M")
            now_iso = now.isoformat()

            # ── 转人工请求：创建真实工单并移交 ─────────────────────────────
            if is_transfer_request:
                transfer_ticket = metadata.get("transfer_ticket") or f"TRANSFER-{uuid.uuid4().hex[:10].upper()}"
                try:
                    ticket = await self._create_transfer_ticket(
                        customer_id=customer_id,
                        customer_name=customer_name,
                        platform=platform,
                        ticket_id=transfer_ticket,
                        last_message=content,
                    )
                except Exception as e:
                    logger.exception("[API] 转人工工单创建失败")
                    return JSONResponse({"error": f"转人工工单创建失败: {e}"}, status_code=500)

                conv["is_transfer"] = True
                conv["transfer_ticket"] = ticket["ticket_id"]
                conv["messages"].append({
                    "type": "customer", "content": "[请求转接人工客服]", "time": now_str, "ts": now_iso,
                })
                agent_msg = (
                    f"已为您转接人工客服，工单号 {ticket['ticket_id']}。"
                    "客服人员将尽快为您服务，期间您发送的消息将直接送达人工坐席。"
                )
                conv["messages"].append({
                    "type": "agent", "content": agent_msg, "time": now_str, "ts": now_iso,
                })
                conv["last_message"] = "[转人工请求]"
                conv["last_time"] = now_str
                try:
                    await self.loop.memory.save_interaction(
                        customer_id=customer_id,
                        thread_id=data.get("thread_id", customer_id),
                        user_message="[转人工请求]",
                        assistant_message=agent_msg,
                        metadata={"type": "transfer_to_human", "transfer_ticket": ticket["ticket_id"]},
                    )
                except Exception as e:
                    logger.warning(f"[API] 转人工记忆保存失败: {e}")
                return {
                    "message_id": msg_id,
                    "content": agent_msg,
                    "intent": "chitchat",
                    "agent": "transfer",
                    "transfer_ticket": ticket["ticket_id"],
                    "timestamp": now_iso,
                }

            # ── 已转人工：路由到人工坐席，不再经过 AI Agent ────────────────
            if conv.get("is_transfer"):
                conv["messages"].append({
                    "type": "customer", "content": content, "time": now_str, "ts": now_iso,
                })
                conv["last_message"] = content[:50]
                conv["last_time"] = now_str
                conv["last_customer_ts"] = now_iso
                try:
                    await self.loop.memory.save_interaction(
                        customer_id=customer_id,
                        thread_id=data.get("thread_id", customer_id),
                        user_message=content,
                        assistant_message="",
                        metadata={"mode": "human", "transfer_ticket": conv.get("transfer_ticket")},
                    )
                except Exception as e:
                    logger.warning(f"[API] 人工模式记忆保存失败: {e}")
                return {
                    "message_id": msg_id,
                    "content": "",
                    "intent": "chitchat",
                    "agent": "human",
                    "transfer": True,
                    "timestamp": now_iso,
                    "notice": "消息已送达人工坐席，请耐心等待回复",
                }

            # ── 正常 AI 路径 ──────────────────────────────────────────────
            try:
                message = Message(
                    id=msg_id,
                    platform=Platform(platform),
                    channel="taobao",
                    customer_id=customer_id,
                    customer_name=customer_name,
                    content=content,
                    content_type=content_type,
                    attachments=attachments,
                    thread_id=data.get("thread_id", customer_id),
                    metadata=metadata,
                )
            except Exception as e:
                logger.exception("[API] 消息构造失败")
                return JSONResponse({"error": f"消息格式不合法: {e}"}, status_code=400)

            try:
                response = await self.loop.handle_message(message)
            except Exception as e:
                logger.exception("[API] Agent 处理失败")
                return JSONResponse({"error": f"Agent 处理失败: {e}"}, status_code=500)

            ts = datetime.now(UTC)
            ts_str = ts.strftime("%H:%M")
            ts_iso = ts.isoformat()
            conv["messages"].append({"type": "customer", "content": content, "time": ts_str, "ts": ts_iso})
            conv["messages"].append({"type": "agent", "content": response.content, "time": ts_str, "ts": ts_iso})
            conv["last_message"] = content[:50]
            conv["last_time"] = ts_str

            return {
                "message_id": response.message_id,
                "content": response.content,
                "intent": response.intent.value,
                "agent": response.agent,
                "timestamp": ts_iso,
            }

        @app.post("/api/speech")
        async def api_speech_to_text(request: Request):
            """语音转文字。"""
            data = await request.json()
            text = data.get("text", "")

            if text:
                return {"success": True, "text": text}

            # 如果有音频数据，走服务端转写
            audio_base64 = data.get("audio_base64", "")
            if audio_base64:
                from .tools.speech_to_text import SpeechToTextTool
                tool = SpeechToTextTool()
                result = await tool.execute(audio_base64=audio_base64)
                return result

            return JSONResponse({"error": "请提供文字或音频数据"}, status_code=400)

        @app.get("/api/conversations")
        async def api_get_conversations(request: Request):
            """获取所有活跃对话。"""
            require_admin_token(request)
            conversations = list(self._conversations.values())
            conversations.sort(key=lambda c: c.get("last_time", ""), reverse=True)
            return {"conversations": conversations, "total": len(conversations)}

        @app.post("/api/admin/reply")
        async def api_admin_reply(request: Request):
            """人工客服直接回复顾客（不经过 AI Agent）。"""
            require_admin_token(request)
            try:
                data = await request.json()
            except Exception as e:
                return JSONResponse({"error": f"请求体不是合法 JSON: {e}"}, status_code=400)
            customer_id = data.get("customer_id", "")
            content = data.get("content", "")
            platform = data.get("platform", "taobao")

            if not customer_id or not content:
                return JSONResponse({"error": "参数不完整：需提供 customer_id 与 content"}, status_code=400)

            now = datetime.now(UTC)
            now_str = now.strftime("%H:%M")
            now_iso = now.isoformat()

            # 记录到对话
            conv = self._conversations.get(customer_id)
            if conv is None:
                return JSONResponse(
                    {"error": f"未找到顾客会话 {customer_id}，无法回复（可能已过期）"},
                    status_code=404,
                )
            conv["messages"].append({
                "type": "agent", "content": content, "time": now_str, "ts": now_iso,
                "source": "human",
            })
            conv["last_message"] = content[:50]
            conv["last_time"] = now_str

            # 保存到记忆
            try:
                await self.loop.memory.save_interaction(
                    customer_id=customer_id,
                    thread_id=data.get("thread_id", customer_id),
                    user_message="",
                    assistant_message=f"[人工客服] {content}",
                    metadata={"type": "human_reply", "platform": platform},
                )
            except Exception as e:
                logger.warning(f"[API] 人工回复记忆保存失败: {e}")

            return {"success": True, "customer_id": customer_id, "content": content, "ts": now_iso}

        @app.get("/api/tickets")
        async def api_get_tickets(request: Request):
            """获取待处理工单列表。"""
            require_admin_token(request)
            try:
                from .database.connection import get_db
                from .database.repository import TicketRepository
                repo = TicketRepository(get_db())
                tickets = repo.get_all()
                return {"tickets": tickets, "total": len(tickets)}
            except Exception:
                # JSON 回退
                tickets_dir = Path(self.config.data_dir) / "tickets"
                tickets = []
                if tickets_dir.exists():
                    for fpath in sorted(tickets_dir.glob("*.json"), reverse=True):
                        try:
                            tickets.append(json.loads(fpath.read_text(encoding="utf-8")))
                        except Exception as e:
                            logger.debug(f"[Web] 跳过无法解析的数据文件 {fpath.name}: {e}")
                return {"tickets": tickets, "total": len(tickets)}

        @app.post("/api/tickets/{ticket_id}/resolve")
        async def api_resolve_ticket(ticket_id: str, request: Request):
            """处理工单（批准/拒绝）。"""
            require_admin_token(request)
            data = await request.json()
            action = data.get("action", "approve")
            note = data.get("note", "")

            try:
                from .database.connection import get_db
                from .database.repository import TicketRepository
                repo = TicketRepository(get_db())
                ticket = repo.get_by_id(ticket_id)
                if not ticket:
                    return JSONResponse({"error": "工单不存在"}, status_code=404)
                new_status = "approved" if action == "approve" else "rejected"
                repo.update(ticket_id, {
                    "status": new_status,
                    "resolution": action,
                    "resolved_at": datetime.now(UTC).isoformat(),
                    "resolved_note": note,
                })
                return {"success": True, "ticket_id": ticket_id, "status": new_status}
            except Exception:
                # JSON 回退
                tickets_dir = Path(self.config.data_dir) / "tickets"
                ticket_path = tickets_dir / f"{ticket_id}.json"
                if not ticket_path.exists():
                    return JSONResponse({"error": "工单不存在"}, status_code=404)
                ticket = json.loads(ticket_path.read_text(encoding="utf-8"))
                ticket["status"] = "approved" if action == "approve" else "rejected"
                ticket["resolution"] = action
                ticket["resolved_at"] = datetime.now(UTC).isoformat()
                ticket["resolved_note"] = note
                ticket_path.write_text(json.dumps(ticket, ensure_ascii=False, indent=2), encoding="utf-8")
                return {"success": True, "ticket_id": ticket_id, "status": ticket["status"]}

        @app.get("/api/orders/{order_id}")
        async def api_get_order(order_id: str, request: Request):
            """获取订单详情（管理端，需鉴权）。"""
            require_admin_token(request)
            try:
                from .database.connection import get_db
                from .database.repository import OrderRepository
                repo = OrderRepository(get_db())
                order = repo.get_by_id(order_id)
                if not order:
                    return JSONResponse({"error": "订单不存在"}, status_code=404)
                return {"order": order}
            except Exception:
                # JSON 回退
                orders_dir = Path(self.config.data_dir) / "orders"
                order_path = orders_dir / f"{order_id}.json"
                if not order_path.exists():
                    return JSONResponse({"error": "订单不存在"}, status_code=404)
                order = json.loads(order_path.read_text(encoding="utf-8"))
                return {"order": order}

        @app.get("/api/products")
        async def api_get_products():
            """获取产品列表。"""
            try:
                from .database.connection import get_db
                from .database.repository import ProductRepository
                repo = ProductRepository(get_db())
                products = repo.get_all()
                result = []
                for p in products:
                    variants = p.get("variants", [])
                    result.append({
                        "id": p.get("base_product_id"),
                        "name": p.get("name"),
                        "category": p.get("category"),
                        "brand": p.get("brand"),
                        "min_price": min((v.get("price", 0) for v in variants), default=0),
                        "max_price": max((v.get("price", 0) for v in variants), default=0),
                        "available_colors": p.get("available_colors", []),
                        "available_sizes": p.get("available_sizes", []),
                    })
                return {"products": result, "total": len(result)}
            except Exception:
                # JSON 回退
                products_dir = Path(self.config.data_dir) / "products"
                products = []
                if products_dir.exists():
                    for fpath in products_dir.glob("*.json"):
                        try:
                            product = json.loads(fpath.read_text(encoding="utf-8"))
                            products.append({
                                "id": product.get("base_product_id"),
                                "name": product.get("name"),
                                "category": product.get("category"),
                                "brand": product.get("brand"),
                                "min_price": min((v.get("price", 0) for v in product.get("variants", [])), default=0),
                                "max_price": max((v.get("price", 0) for v in product.get("variants", [])), default=0),
                                "available_colors": product.get("available_colors", []),
                                "available_sizes": product.get("available_sizes", []),
                            })
                        except Exception as e:
                            logger.debug(f"[Web] 跳过无法解析的数据文件 {fpath.name}: {e}")
                return {"products": products, "total": len(products)}

        @app.get("/api/customer/{customer_id}/history")
        async def api_get_customer_history(customer_id: str, request: Request):
            """获取顾客聊天历史（管理端，需鉴权）。"""
            require_admin_token(request)
            try:
                history = await self.loop.memory.get_history(customer_id, limit=50)
            except Exception as e:
                logger.exception("[API] 读取顾客历史失败")
                return JSONResponse({"error": f"读取历史失败: {e}"}, status_code=500)
            return {"customer_id": customer_id, "history": history, "total": len(history)}

        @app.get("/api/customer/{customer_id}/updates")
        async def api_customer_updates(customer_id: str, request: Request):
            """顾客端轮询：拉取转人工后新增的坐席回复。

            查询参数 since：ISO 时间戳，返回该时间之后的坐席/系统消息。
            顾客端在转人工模式下轮询此接口以实时收到人工回复。
            """
            since = request.query_params.get("since", "")
            conv = self._conversations.get(customer_id)
            if not conv:
                return {"messages": [], "is_transfer": False, "transfer_ticket": None}

            new_msgs = []
            for m in conv.get("messages", []):
                if m.get("type") == "customer":
                    continue
                if since and m.get("ts", "") <= since:
                    continue
                new_msgs.append({"content": m.get("content", ""), "time": m.get("time", ""), "ts": m.get("ts", "")})

            return {
                "messages": new_msgs,
                "is_transfer": conv.get("is_transfer", False),
                "transfer_ticket": conv.get("transfer_ticket"),
            }

        self.app = app
        return app

    # ── 转人工工单 ───────────────────────────────────────────────────────

    async def _create_transfer_ticket(
        self,
        customer_id: str,
        customer_name: str,
        platform: str,
        ticket_id: str,
        last_message: str,
    ) -> dict[str, Any]:
        """创建转人工工单并持久化（优先 DB，回退 JSON 文件）。

        工单会出现在管理端 /api/tickets，坐席据此认领会话并回复。
        """
        now_iso = datetime.now(UTC).isoformat()
        ticket = {
            "ticket_id": ticket_id,
            "type": "transfer_to_human",
            "status": "pending",
            "created_at": now_iso,
            "customer_id": customer_id,
            "customer_name": customer_name,
            "platform": platform,
            "last_message": (last_message or "")[:200],
            "expected_response": "尽快接入",
        }

        # 优先写入 DB
        try:
            from .database.connection import get_db
            from .database.repository import TicketRepository
            db = get_db()
            if db.is_connected:
                repo = TicketRepository(db)
                repo.create(ticket)
                logger.info(f"[Transfer] 转人工工单已入库: {ticket_id}")
                return ticket
        except Exception as e:
            logger.warning(f"[Transfer] 工单入库失败，回退 JSON: {e}")

        # 回退到 JSON 文件
        tickets_dir = Path(self.config.data_dir) / "tickets"
        try:
            tickets_dir.mkdir(parents=True, exist_ok=True)
            ticket_path = tickets_dir / f"{ticket_id}.json"
            ticket_path.write_text(
                json.dumps(ticket, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.info(f"[Transfer] 转人工工单已落盘: {ticket_path}")
        except Exception as e:
            logger.error(f"[Transfer] 工单落盘失败: {e}")
            raise
        return ticket

    async def run(self, host: str = "127.0.0.1", port: int = 8000) -> None:
        """启动 Web 服务器。"""
        if not HAS_UVICORN:
            logger.error("请安装 uvicorn: pip install uvicorn")
            return

        self.create_app()
        logger.info(f"[WebServer] 启动服务器: http://{host}:{port}")
        logger.info(f"[WebServer] 顾客页面: http://{host}:{port}/")
        logger.info(f"[WebServer] 管理页面: http://{host}:{port}/admin")

        config = uvicorn.Config(self.app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()
