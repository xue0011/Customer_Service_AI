"""
语音转文字工具
─────────────
支持两种模式：

1. 浏览器端 Web Speech API（推荐，实时转写，无需 API Key）
2. 服务端 OpenAI Whisper API（备选，更准确）

当前实现：
- 浏览器端：通过 Web Speech API 转写后，前端直接发送文字给 Agent
- 服务端：接收 base64 音频，调用 Whisper API 转写
"""

from __future__ import annotations

import base64
import tempfile
from typing import Any

from loguru import logger

from .base import BaseTool


class SpeechToTextTool(BaseTool):
    """语音转文字工具 —— 支持浏览器端和服务端两种模式。"""

    @property
    def name(self) -> str:
        return "speech_to_text"

    @property
    def description(self) -> str:
        return (
            "将顾客的语音消息转为文字。支持普通话识别。"
            "当顾客发送语音消息时，先调用此工具转文字，再发送给 Agent 处理。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "audio_base64": {
                    "type": "string",
                    "description": "Base64 编码的音频数据（不含 data:xxx;base64, 前缀）",
                },
                "audio_format": {
                    "type": "string",
                    "enum": ["wav", "mp3", "webm", "ogg", "m4a"],
                    "description": "音频格式",
                    "default": "webm",
                },
                "language": {
                    "type": "string",
                    "description": "识别语言，默认 zh（普通话）",
                    "default": "zh",
                },
            },
            "required": ["audio_base64"],
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        """执行语音转文字。

        流程：
        1. 如果 audio_base64 已经是文字 → 直接返回（浏览器端已转写）
        2. 如果是真正的音频数据 → 调用 Whisper API 转写
        """
        audio_base64 = kwargs.get("audio_base64", "")
        language = kwargs.get("language", "zh")

        # 浏览器端已转写，直接透传
        if not self._is_audio_data(audio_base64):
            return {
                "success": True,
                "data": {
                    "text": audio_base64,
                    "language": language,
                    "method": "browser_pre_transcribed",
                },
            }

        # 服务端 Whisper 转写
        return await self._whisper_transcribe(audio_base64, language)

    def _is_audio_data(self, data: str) -> bool:
        """判断是否是真正的音频数据（base64）。"""
        if len(data) < 100:
            return False
        # 音频 base64 通常以特定字符开头
        audio_prefixes = ["//", "SUQz", "UklG", "T2dn", "AAA", "GkXf", "data:"]
        for prefix in audio_prefixes:
            if data.startswith(prefix):
                return True
        return False

    async def _whisper_transcribe(self, audio_base64: str, language: str) -> dict[str, Any]:
        """调用 OpenAI Whisper API 进行语音转文字。"""
        try:
            import os

            from openai import OpenAI

            api_key = os.getenv("OPENAI_API_KEY", "")
            api_base = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")

            if not api_key:
                return {
                    "success": False,
                    "error": "未配置 OPENAI_API_KEY，无法使用 Whisper API。请使用浏览器端语音转写。",
                }

            # 解码音频
            audio_bytes = base64.b64decode(audio_base64)

            # 写入临时文件
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
                f.write(audio_bytes)
                temp_path = f.name

            try:
                client = OpenAI(api_key=api_key, base_url=api_base)
                with open(temp_path, "rb") as audio_file:
                    transcript = client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file,
                        language=language,
                        response_format="json",
                    )

                text = transcript.text if hasattr(transcript, 'text') else str(transcript)
                logger.info(f"[SpeechToText] Whisper 转写完成: {text[:50]}...")

                return {
                    "success": True,
                    "data": {
                        "text": text,
                        "language": language,
                        "method": "whisper_api",
                    },
                }
            finally:
                import os as _os
                try:
                    _os.unlink(temp_path)
                except Exception:
                    pass

        except ImportError:
            return {
                "success": False,
                "error": "请安装 openai: pip install openai",
            }
        except Exception as e:
            logger.error(f"[SpeechToText] Whisper 转写失败: {e}")
            return {
                "success": False,
                "error": f"语音转写失败: {str(e)}",
            }
