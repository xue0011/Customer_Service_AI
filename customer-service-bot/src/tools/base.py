"""
工具基类
───────
所有 Agent 可调用的工具都继承此基类。

P0 增强统一安全层（验收 7）：
  - 参数校验（required 字段）
  - 权限校验（required_permission + RBAC）
  - 超时（asyncio.wait_for）
  - 异常处理（统一封装为 ToolResult/dict，不冒泡）
  - 审计日志（log_tool_call：入参/结果/耗时/actor）
  - 高风险确认（require_confirmation=True 时未带 confirmed 则返回待确认摘要）
"""

from __future__ import annotations

import asyncio
import inspect
import time
from abc import ABC, abstractmethod
from typing import Any

from loguru import logger


class ToolResult:
    """工具执行结果。"""

    def __init__(self, success: bool, data: Any = None, error: str = "") -> None:
        self.success = success
        self.data = data
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        return {"success": self.success, "data": self.data, "error": self.error}

    def __repr__(self) -> str:
        if self.success:
            return f"ToolResult(ok, data={str(self.data)[:100]})"
        return f"ToolResult(fail, error={self.error})"


class BaseTool(ABC):
    """工具抽象基类。"""

    # ── 可被子类覆写的安全声明 ──────────────────────────────────────────
    required_permission: str | None = None   # RBAC 权限，None 表示不强制
    high_risk: bool = False                   # 高风险（退货/退款/改单）
    require_confirmation: bool = False        # 需要二次确认才执行
    timeout: float = 30.0                     # 单次执行超时（秒）

    # ── 子类必须定义的属性 ──────────────────────────────────────────────

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称 —— 全局唯一，LLM 通过名称调用。"""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述 —— 告诉 LLM 这个工具是做什么的。"""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """参数定义 —— JSON Schema 格式。"""
        ...

    # ── 核心执行方法 ────────────────────────────────────────────────────

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Any:
        """执行工具的核心逻辑。子类必须实现。"""
        ...

    # ── 公共接口 ────────────────────────────────────────────────────────

    def get_definition(self) -> dict[str, Any]:
        """生成 OpenAI function calling 格式的工具定义。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def _validate_required(self, kwargs: dict[str, Any]) -> str | None:
        """校验 required 参数存在且非空。返回错误消息或 None。"""
        required = self.parameters.get("required", []) if isinstance(self.parameters, dict) else []
        for k in required:
            v = kwargs.get(k)
            if v is None or (isinstance(v, str) and not v.strip()):
                return f"缺少必填参数：{k}"
        return None

    async def safe_execute(self, **kwargs: Any) -> dict[str, Any]:
        """安全执行工具 —— 统一参数校验/权限/超时/异常/审计。"""
        from ..auth.rbac import can
        from ..infra.audit import log_tool_call
        from ..infra.context import get_actor

        actor = get_actor()

        # 1) 参数校验
        err = self._validate_required(kwargs)
        if err:
            return {"success": False, "error": err}

        # 2) 权限校验
        if self.required_permission and actor is not None:
            if not can(actor.role, self.required_permission):
                return {
                    "success": False,
                    "error": f"权限不足：需要 {self.required_permission} 权限",
                }

        # 3) 高风险确认
        if self.require_confirmation and not kwargs.get("confirmed"):
            return await self._pending_confirmation(kwargs)

        # 4) 执行（带超时与异常）
        start = time.time()
        success = True
        error: str | None = None
        result: Any = None
        try:
            coro = self.execute(**kwargs)
            result = await asyncio.wait_for(coro, timeout=self.timeout)
            if isinstance(result, ToolResult):
                out = result.to_dict()
            elif isinstance(result, dict) and "success" in result:
                out = result  # execute 已返回标准 {success, data, error} 结构，不再二次包装
            else:
                out = {"success": True, "data": result}
            success = out.get("success", True)
            error = out.get("error")
        except TimeoutError:
            success = False
            error = f"工具 {self.name} 执行超时（{self.timeout}s）"
            out = {"success": False, "error": error}
        except PermissionError as e:
            success = False
            error = f"权限校验失败：{e}"
            out = {"success": False, "error": error}
        except Exception as e:  # noqa: BLE001
            success = False
            error = str(e)
            out = {"success": False, "error": error}
            logger.exception(f"[tool] {self.name} 执行异常")

        duration_ms = (time.time() - start) * 1000

        # 5) 审计
        try:
            await log_tool_call(
                tool_name=self.name,
                arguments=kwargs,
                result=out,
                success=success,
                error=error,
                duration_ms=duration_ms,
                actor=actor,
            )
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[tool] 审计写入失败：{e}")

        return out

    async def _pending_confirmation(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """默认待确认摘要；子类可覆写提供更具体摘要。"""
        return {
            "success": True,
            "data": {
                "requires_confirmation": True,
                "message": (
                    f"操作 {self.name} 为高风险操作，需用户确认。"
                    "确认后请再次调用并设置 confirmed=true。"
                ),
                "preview": kwargs,
            },
        }

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name={self.name})>"


# ─── 函数式工具（快速将普通函数包装为工具） ────────────────────────────────

class FunctionTool(BaseTool):
    """将普通函数包装为工具。"""

    def __init__(
        self,
        name: str,
        description: str,
        func: callable,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        self._name = name
        self._description = description
        self._func = func
        self._parameters = parameters or self._infer_parameters(func)

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    async def execute(self, **kwargs: Any) -> Any:
        result = self._func(**kwargs)
        if inspect.iscoroutine(result):
            result = await result
        return result

    @staticmethod
    def _infer_parameters(func: callable) -> dict[str, Any]:
        sig = inspect.signature(func)
        properties = {}
        required = []

        for name, param in sig.parameters.items():
            if name in ("self", "cls"):
                continue
            param_type = "string"
            if param.annotation is not inspect.Parameter.empty:
                if param.annotation is int:
                    param_type = "integer"
                elif param.annotation is float:
                    param_type = "number"
                elif param.annotation is bool:
                    param_type = "boolean"
                elif param.annotation is list:
                    param_type = "array"

            properties[name] = {"type": param_type, "description": f"{name} 参数"}
            if param.default is inspect.Parameter.empty:
                required.append(name)

        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }
