"""工具层安全辅助：订单归属校验（IDOR 防护）。"""

from __future__ import annotations

from typing import Any

from ..infra.context import get_actor


class OwnershipError(PermissionError):
    """订单/资源归属校验失败。"""


def check_order_ownership(order: dict[str, Any] | None, actor=None) -> None:
    """校验当前 actor 是否有权访问该订单。

    - staff（agent/lead/admin）：放行
    - customer：订单 customer_id 必须等于 actor.customer_id
    - 无 actor：拒绝（要求 loop 在调用前注入身份）
    """
    if order is None:
        return
    a = actor or get_actor()
    if a is None:
        raise OwnershipError("无调用者身份上下文，拒绝访问订单。")
    if a.is_staff():
        return
    if not a.customer_id:
        raise OwnershipError("顾客身份未绑定，无法核实订单归属。")
    if order.get("customer_id") != a.customer_id:
        raise OwnershipError("订单不属于当前顾客，拒绝访问。")


def assert_customer_matches(customer_id: str, actor=None) -> None:
    """顾客按 customer_id 查询时，必须只查自己。"""
    a = actor or get_actor()
    if a is None:
        raise OwnershipError("无调用者身份上下文。")
    if a.is_staff():
        return
    if not a.customer_id or a.customer_id != customer_id:
        raise OwnershipError("仅可查询本人订单。")
