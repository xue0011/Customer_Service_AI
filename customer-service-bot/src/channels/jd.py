"""
京东渠道适配器
─────────────
京东开放平台（JOS）消息适配器 —— 完整 API 对接。

API 文档：https://open.jd.com/home/home#/doc
认证方式：app_key + access_token
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


class JdAdapter(ChannelAdapter):
    """京东开放平台渠道适配器。"""

    JD_API_URL = "https://api.jd.com/routerjson"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self._message_queue: asyncio.Queue[Message] = asyncio.Queue()
        self._app_key = config.get("app_key", "")
        self._app_secret = config.get("app_secret", "")
        self._access_token = config.get("access_token", "")
        self._vender_id = config.get("vender_id", "")
        self._http_client: httpx.AsyncClient | None = None

    @property
    def channel_type(self) -> str:
        return "jd"

    async def start(self) -> None:
        self._http_client = httpx.AsyncClient(timeout=30.0)

        if self._app_key and self._access_token:
            try:
                await self._verify_auth()
                self._running = True
                logger.info("[JD] 京东渠道已连接 JOS API")
            except Exception as e:
                logger.error(f"[JD] API 连接失败: {e}")
                self._running = True
        else:
            self._running = True
            logger.info("[JD] 京东渠道已启动（等待 API 凭证）")

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
            logger.debug(f"[JD] 模拟发送: {response.content[:80]}...")
            return True

        try:
            params = {
                "method": "jingdong.im.sendMessage",
                "app_key": self._app_key,
                "access_token": self._access_token,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "format": "json",
                "v": "2.0",
                "param_json": str({
                    "fromId": self._vender_id,
                    "toId": response.metadata.get("customer_id", ""),
                    "content": response.content,
                    "msgType": 1,
                }),
            }
            params["sign"] = self._sign(params)
            resp = await self._http_client.post(self.JD_API_URL, data=params)
            data = resp.json()
            if "error_response" in data:
                logger.error(f"[JD] 发送失败: {data['error_response'].get('zh_desc')}")
                return False
            return True
        except Exception as e:
            logger.error(f"[JD] 发送异常: {e}")
            return False

    def _sign(self, params: dict) -> str:
        sorted_keys = sorted(params.keys())
        sign_str = self._app_secret
        for k in sorted_keys:
            if k != "sign":
                sign_str += f"{k}{params[k]}"
        sign_str += self._app_secret
        return hashlib.md5(sign_str.encode("utf-8")).hexdigest().upper()

    async def _verify_auth(self) -> None:
        params = {
            "method": "jingdong.vender.info.query",
            "app_key": self._app_key,
            "access_token": self._access_token,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "format": "json",
            "v": "2.0",
        }
        params["sign"] = self._sign(params)
        resp = await self._http_client.post(self.JD_API_URL, data=params)
        data = resp.json()
        if "error_response" in data:
            raise Exception(data["error_response"].get("zh_desc", "认证失败"))

    async def _poll_messages(self) -> list[Message]:
        try:
            params = {
                "method": "jingdong.im.getUnreadMessage",
                "app_key": self._app_key,
                "access_token": self._access_token,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "format": "json",
                "v": "2.0",
            }
            params["sign"] = self._sign(params)
            resp = await self._http_client.post(self.JD_API_URL, data=params)
            data = resp.json()
            if "error_response" in data:
                return []

            messages = []
            raw_msgs = data.get("jingdong_im_getUnreadMessage_responce", {}).get("result", [])
            for raw in (raw_msgs if isinstance(raw_msgs, list) else [raw_msgs]):
                messages.append(Message(
                    id=str(raw.get("msgId", "")),
                    platform=Platform.JD,
                    channel="jd",
                    customer_id=raw.get("fromId", ""),
                    customer_name=raw.get("fromId", ""),
                    content=raw.get("content", ""),
                    content_type="text",
                    metadata={
                        "vender_id": self._vender_id,
                        "platform": "jd",
                        "is_plus_member": raw.get("isPlus", False),
                    },
                ))
            return messages
        except Exception as e:
            logger.warning(f"[Jd] 轮询消息失败: {e}")
            return []

    def simulate_incoming_message(
        self, msg_id: str, from_id: str, content: str, is_plus: bool = False
    ) -> None:
        message = Message(
            id=msg_id,
            platform=Platform.JD,
            channel="jd",
            customer_id=from_id,
            customer_name=from_id,
            content=content,
            content_type="text",
            metadata={
                "vender_id": self._vender_id,
                "platform": "jd",
                "is_plus_member": is_plus,
            },
        )
        self._message_queue.put_nowait(message)
