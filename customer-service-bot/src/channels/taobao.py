"""
淘宝渠道适配器
─────────────
淘宝开放平台（TOP）消息适配器 —— 完整 API 对接。

API 文档：https://open.taobao.com/api.htm
认证方式：HMAC-SHA1 签名
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from collections.abc import AsyncIterator

import httpx
from loguru import logger

from ..config.schema import Message, Platform, Response
from .base import ChannelAdapter


class TaobaoAdapter(ChannelAdapter):
    """淘宝/天猫开放平台渠道适配器。"""

    TAOBAO_API_URL = "https://eco.taobao.com/router/rest"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self._message_queue: asyncio.Queue[Message] = asyncio.Queue()
        self._app_key = config.get("app_key", "")
        self._app_secret = config.get("app_secret", "")
        self._session_key = config.get("session_key", "")
        self._http_client: httpx.AsyncClient | None = None

    @property
    def channel_type(self) -> str:
        return "taobao"

    async def start(self) -> None:
        self._http_client = httpx.AsyncClient(timeout=30.0)

        if self._app_key and self._app_secret:
            # 有真实凭证，尝试连接淘宝 API
            try:
                await self._verify_auth()
                self._running = True
                logger.info("[Taobao] 淘宝渠道已连接 TOP API")
            except Exception as e:
                logger.error(f"[Taobao] 淘宝 API 连接失败: {e}")
                self._running = True
                logger.info("[Taobao] 将在模拟模式下运行，等待真实消息")
        else:
            self._running = True
            logger.info("[Taobao] 淘宝渠道已启动（等待 API 凭证）")

    async def stop(self) -> None:
        self._running = False
        if self._http_client:
            await self._http_client.aclose()
        logger.info("[Taobao] 淘宝渠道已停止")

    async def receive(self) -> AsyncIterator[Message]:
        while self._running:
            try:
                # 优先从模拟队列获取（测试用）
                message = await asyncio.wait_for(self._message_queue.get(), timeout=1.0)
                yield message
            except TimeoutError:
                # 轮询真实 API 获取新消息
                if self._app_key and self._session_key:
                    messages = await self._poll_messages()
                    for msg in messages:
                        yield msg
            except asyncio.CancelledError:
                break

    async def send(self, response: Response) -> bool:
        """发送回复给淘宝买家。"""
        if not self._app_key or not self._session_key:
            logger.debug(f"[Taobao] 模拟发送: {response.content[:80]}...")
            return True

        # 调用淘宝客服消息发送 API
        try:
            params = {
                "method": "taobao.openim.messages.send",
                "app_key": self._app_key,
                "session": self._session_key,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "format": "json",
                "v": "2.0",
                "sign_method": "hmac",
                "to_user_id": response.metadata.get("buyer_nick", ""),
                "content": response.content,
                "msg_type": "text",
            }
            params["sign"] = self._sign(params)
            resp = await self._http_client.post(self.TAOBAO_API_URL, data=params)
            data = resp.json()
            if "error_response" in data:
                logger.error(f"[Taobao] 发送失败: {data['error_response'].get('msg')}")
                return False
            logger.info("[Taobao] 消息发送成功")
            return True
        except Exception as e:
            logger.error(f"[Taobao] 发送异常: {e}")
            return False

    def _sign(self, params: dict) -> str:
        """生成 TOP API 签名。"""
        sorted_keys = sorted(params.keys())
        sign_str = self._app_secret
        for k in sorted_keys:
            if k not in ("sign",) and params[k] is not None:
                sign_str += f"{k}{params[k]}"
        sign_str += self._app_secret
        return hmac.new(
            self._app_secret.encode("utf-8"),
            sign_str.encode("utf-8"),
            hashlib.md5,
        ).hexdigest().upper()

    async def _verify_auth(self) -> None:
        """验证 API 凭证。"""
        params = {
            "method": "taobao.shop.get",
            "app_key": self._app_key,
            "session": self._session_key,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "format": "json",
            "v": "2.0",
            "sign_method": "hmac",
            "fields": "sid,cid,title,nick",
            "nick": self._session_key,
        }
        params["sign"] = self._sign(params)
        resp = await self._http_client.post(self.TAOBAO_API_URL, data=params)
        data = resp.json()
        if "error_response" in data:
            raise Exception(data["error_response"].get("msg", "认证失败"))

    async def _poll_messages(self) -> list[Message]:
        """轮询获取新消息。"""
        try:
            params = {
                "method": "taobao.openim.messages.get",
                "app_key": self._app_key,
                "session": self._session_key,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "format": "json",
                "v": "2.0",
                "sign_method": "hmac",
            }
            params["sign"] = self._sign(params)
            resp = await self._http_client.post(self.TAOBAO_API_URL, data=params)
            data = resp.json()

            if "error_response" in data:
                return []

            messages = []
            raw_msgs = data.get("openim_messages_get_response", {}).get("messages", {}).get("open_im_message", [])
            for raw in (raw_msgs if isinstance(raw_msgs, list) else [raw_msgs]):
                messages.append(Message(
                    id=str(raw.get("msg_id", "")),
                    platform=Platform.TAOBAO,
                    channel="taobao",
                    customer_id=raw.get("from_id", ""),
                    customer_name=raw.get("from_id", ""),
                    content=raw.get("content", ""),
                    content_type=raw.get("msg_type", "text"),
                    metadata={"buyer_nick": raw.get("from_id", ""), "platform": "taobao"},
                ))
            return messages
        except Exception as e:
            logger.warning(f"[Taobao] 轮询消息失败: {e}")
            return []

    def simulate_incoming_message(
        self, tid: str, buyer_nick: str, content: str, msg_type: str = "text"
    ) -> None:
        """模拟接收消息（测试用）。"""
        message = Message(
            id=tid,
            platform=Platform.TAOBAO,
            channel="taobao",
            customer_id=buyer_nick,
            customer_name=buyer_nick,
            content=content,
            content_type=msg_type,
            metadata={"buyer_nick": buyer_nick, "platform": "taobao"},
        )
        self._message_queue.put_nowait(message)
