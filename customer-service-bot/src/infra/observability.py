"""可观测性：统一 Trace ID + OpenTelemetry span（可选，未装降级 NoOp）（验收7/8）。

设计选择：
  - Trace ID 用 contextvars 贯穿 Router/Agent/检索/工具/审批，并写入 AgentTrace/ToolCallLog。
  - OTel 可选 import，未装则 NoOp span（不强制依赖）。
替代方案 Langfuse（托管，需 SDK+key）——P1 用 OTel 开源标准，可自托管，无外部依赖。
"""

from __future__ import annotations

import uuid
from typing import Any

try:
    from opentelemetry import trace as _otel_trace

    _HAS_OTEL = True
except ImportError:
    _HAS_OTEL = False
    _otel_trace = None  # type: ignore[assignment]


class NoOpSpan:
    """OTel 未安装时的空 span。"""

    def __enter__(self) -> NoOpSpan:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def record_exception(self, exception: BaseException) -> None:
        pass

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        pass


def get_tracer(name: str = "customer-service-bot"):
    if _HAS_OTEL and _otel_trace is not None:
        return _otel_trace.get_tracer(name)
    return None


def span(name: str, **attrs: Any):
    """返回 span 上下文管理器（OTel 或 NoOp）。"""
    tracer = get_tracer()
    if tracer is not None:
        try:
            cm = tracer.start_as_current_span(name)
            # 附加属性
            active = cm.__enter__() if hasattr(cm, "__enter__") else None
            for k, v in attrs.items():
                try:
                    if active is not None and hasattr(active, "set_attribute"):
                        active.set_attribute(k, str(v))
                except Exception:  # noqa: BLE001
                    pass
            return cm
        except Exception:  # noqa: BLE001
            return NoOpSpan()
    return NoOpSpan()


def new_trace_id() -> str:
    return uuid.uuid4().hex
