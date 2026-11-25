"""
拼多多渠道适配器
───────────────
拼多多开放平台消息适配器 —— 完整 API 对接。

API 文档：https://open.pinduoduo.com/application/document/api
认证方式：client_id + client_secret → access_token
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

import httpx
from loguru import logger

from ..config.schema import Message, Platform, Response
from .base import ChannelAdapter


class PinduoduoAdapter(ChannelAdapter):
    """拼多多开放平台渠道适配器。"""

    PDD_API_URL = "https://gw-api.pinduoduo.com/api/router"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self._message_queue: asyncio.Queue[Message] = asyncio.Queue()
        self._client_id = config.get("client_id", "")
        self._client_secret = config.get("client_secret", "")
        self._mall_id = config.get("mall_id", "")
        self._access_token = config.get("access_token", "")
        self._http_client: httpx.AsyncClient | None = None

    @property
    def channel_type(self) -> str:
        return "pinduoduo"

    async def start(self) -> None:
        self._http_client = httpx.AsyncClient(timeout=30.0)

        if self._client_id and self._client_secret:
            try:
                if not self._access_token:
                    self._access_token = await self._get_access_token()
                await self._verify_auth()
                self._running = True
                logger.info("[Pinduoduo] 拼多多渠道已连接 API")
            except Exception as e:
                logger.error(f"[Pinduoduo] API 连接失败: {e}")
                self._running = True
        else:
            self._running = True
            logger.info("[Pinduoduo] 拼多多渠道已启动（等待 API 凭证）")

    async def stop(self) -> None:
        self._running = False
        if self._http_client:
            await self._http_client.aclose()

    async def receive(self) -> AsyncIterator[Message]:
        while self._running:
            try:
                message = await asyncio.wait_for(self._message_queue.get(), timeout=1.0)
                yield message
            except TimeoutError:
                if self._access_token:
                    messages = await self._poll_messages()
                    for msg in messages:
                        yield msg
            except asyncio.CancelledError:
                break

    async def send(self, response: Response) -> bool:
        if not self._access_token:
            logger.debug(f"[Pinduoduo] 模拟发送: {response.content[:80]}...")
            return True

        try:
            params = {
                "type": "pdd.im.message.send",
                "client_id": self._client_id,
                "access_token": self._access_token,
                "timestamp": int(time.time()),
                "data_type": "JSON",
                "to_user_id": response.metadata.get("customer_id", ""),
                "content": response.content,
                "msg_type": 0,  # 文本消息
            }
            resp = await self._http_client.post(self.PDD_API_URL, json=params)
            data = resp.json()
            if "error_response" in data:
                logger.error(f"[Pinduoduo] 发送失败: {data['error_response'].get('error_msg')}")
                return False
            return True
        except Exception as e:
            logger.error(f"[Pinduoduo] 发送异常: {e}")
            return False

    async def _get_access_token(self) -> str:
        """获取 access_token。"""
        resp = await self._http_client.post(
            "https://gw-api.pinduoduo.com/api/router",
            json={
                "type": "pdd.pop.auth.token.create",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "client_credentials",
                "timestamp": int(time.time()),
                "data_type": "JSON",
            },
        )
        data = resp.json()
        if "error_response" in data:
            raise Exception(data["error_response"].get("error_msg", "获取 token 失败"))
        return data.get("access_token", "")

    async def _verify_auth(self) -> None:
        resp = await self._http_client.post(
            self.PDD_API_URL,
            json={
                "type": "pdd.mall.info.get",
                "client_id": self._client_id,
                "access_token": self._access_token,
                "timestamp": int(time.time()),
                "data_type": "JSON",
            },
        )
        data = resp.json()
        if "error_response" in data:
            raise Exception(data["error_response"].get("error_msg", "认证失败"))

    async def _poll_messages(self) -> list[Message]:
        try:
            resp = await self._http_client.post(
                self.PDD_API_URL,
                json={
                    "type": "pdd.im.message.list.get",
                    "client_id": self._client_id,
                    "access_token": self._access_token,
                    "timestamp": int(time.time()),
                    "data_type": "JSON",
                },
            )
            data = resp.json()
            if "error_response" in data:
                return []

            messages = []
            raw_msgs = data.get("im_message_list_get_response", {}).get("message_list", [])
            for raw in raw_msgs:
                if raw.get("msg_type") == "auto_reply":
                    continue
                messages.append(Message(
                    id=str(raw.get("msg_id", "")),
                    platform=Platform.PINDUODUO,
                    channel="pinduoduo",
                    customer_id=raw.get("from_user", ""),
                    customer_name=raw.get("from_user", ""),
                    content=raw.get("content", ""),
                    content_type="text",
                    metadata={"mall_id": self._mall_id, "platform": "pinduoduo"},
                ))
            return messages
        except Exception as e:
            logger.warning(f"[Pinduoduo] 轮询消息失败: {e}")
            return []

    def simulate_incoming_message(
        self, msg_id: str, from_user: str, content: str, msg_type: str = "text"
    ) -> None:
        if msg_type == "auto_reply":
            return
        message = Message(
            id=msg_id,
            platform=Platform.PINDUODUO,
            channel="pinduoduo",
            customer_id=from_user,
            customer_name=from_user,
            content=content,
            content_type="text",
            metadata={"mall_id": self._mall_id, "platform": "pinduoduo"},
        )
        self._message_queue.put_nowait(message)
