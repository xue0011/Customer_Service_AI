"""
得物渠道适配器
─────────────
得物（毒）开放平台消息适配器 —— 完整 API 对接。

API 文档：https://open.dewu.com/
认证方式：app_key + app_secret → access_token
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import AsyncIterator

import httpx
from loguru import logger

from ..config.schema import Message, Platform, Response
from .base import ChannelAdapter


class DewuAdapter(ChannelAdapter):
    """得物开放平台渠道适配器。"""

    DEWU_API_URL = "https://openapi.dewu.com/api/v1"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self._message_queue: asyncio.Queue[Message] = asyncio.Queue()
        self._app_key = config.get("app_key", "")
        self._app_secret = config.get("app_secret", "")
        self._access_token = config.get("access_token", "")
        self._http_client: httpx.AsyncClient | None = None

    @property
    def channel_type(self) -> str:
        return "dewu"

    async def start(self) -> None:
        self._http_client = httpx.AsyncClient(timeout=30.0)

        if self._app_key and self._app_secret:
            try:
                if not self._access_token:
                    self._access_token = await self._get_access_token()
                await self._verify_auth()
                self._running = True
                logger.info("[Dewu] 得物渠道已连接 API")
            except Exception as e:
                logger.error(f"[Dewu] API 连接失败: {e}")
                self._running = True
        else:
            self._running = True
            logger.info("[Dewu] 得物渠道已启动（等待 API 凭证）")

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
            logger.debug(f"[Dewu] 模拟发送: {response.content[:80]}...")
            return True

        try:
            headers = self._auth_headers()
            body = {
                "to_user_id": response.metadata.get("customer_id", ""),
                "content": response.content,
                "msg_type": "text",
            }
            resp = await self._http_client.post(
                f"{self.DEWU_API_URL}/im/message/send",
                json=body,
                headers=headers,
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.error(f"[Dewu] 发送失败: {data.get('msg')}")
                return False
            return True
        except Exception as e:
            logger.error(f"[Dewu] 发送异常: {e}")
            return False

    def _auth_headers(self) -> dict:
        ts = str(int(time.time()))
        sign_str = f"{self._app_key}{ts}{self._app_secret}"
        sign = hashlib.sha256(sign_str.encode("utf-8")).hexdigest()
        return {
            "X-App-Key": self._app_key,
            "X-Timestamp": ts,
            "X-Sign": sign,
            "X-Access-Token": self._access_token,
            "Content-Type": "application/json",
        }

    async def _get_access_token(self) -> str:
        ts = str(int(time.time()))
        sign_str = f"{self._app_key}{ts}{self._app_secret}"
        headers = {
            "X-App-Key": self._app_key,
            "X-Timestamp": ts,
            "X-Sign": hashlib.sha256(sign_str.encode("utf-8")).hexdigest(),
        }
        resp = await self._http_client.post(
            f"{self.DEWU_API_URL}/auth/token",
            json={"grant_type": "client_credentials"},
            headers=headers,
        )
        data = resp.json()
        if data.get("code") != 0:
            raise Exception(data.get("msg", "获取 token 失败"))
        return data.get("data", {}).get("access_token", "")

    async def _verify_auth(self) -> None:
        resp = await self._http_client.get(
            f"{self.DEWU_API_URL}/shop/info",
            headers=self._auth_headers(),
        )
        data = resp.json()
        if data.get("code") != 0:
            raise Exception(data.get("msg", "认证失败"))

    async def _poll_messages(self) -> list[Message]:
        try:
            resp = await self._http_client.get(
                f"{self.DEWU_API_URL}/im/message/unread",
                headers=self._auth_headers(),
            )
            data = resp.json()
            if data.get("code") != 0:
                return []

            messages = []
            raw_msgs = data.get("data", {}).get("messages", [])
            for raw in raw_msgs:
                messages.append(Message(
                    id=str(raw.get("msg_id", "")),
                    platform=Platform.DEWU,
                    channel="dewu",
                    customer_id=raw.get("user_id", ""),
                    customer_name=raw.get("user_id", ""),
                    content=raw.get("content", ""),
                    content_type=raw.get("msg_type", "text"),
                    metadata={
                        "platform": "dewu",
                        "platform_style": "young_casual",
                        "item_id": raw.get("item_id", ""),
                        "dewu_appraisal": raw.get("msg_type") == "appraisal",
                    },
                ))
            return messages
        except Exception as e:
            logger.warning(f"[Dewu] 轮询消息失败: {e}")
            return []

    def simulate_incoming_message(
        self, msg_id: str, user_id: str, content: str, msg_type: str = "text",
        item_id: str = "", is_appraisal: bool = False,
    ) -> None:
        message = Message(
            id=msg_id,
            platform=Platform.DEWU,
            channel="dewu",
            customer_id=user_id,
            customer_name=user_id,
            content=content,
            content_type="text",
            metadata={
                "platform": "dewu",
                "platform_style": "young_casual",
                "item_id": item_id,
                "dewu_appraisal": is_appraisal,
            },
        )
        self._message_queue.put_nowait(message)
