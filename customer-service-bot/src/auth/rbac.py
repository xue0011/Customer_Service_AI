"""基于角色的访问控制（RBAC）。

角色：customer / agent / lead / admin
权限以 `资源:动作[:范围]` 表示，admin 拥有通配符 `*`。
"""

from __future__ import annotations

from typing import Any

PERMISSIONS: dict[str, set[str]] = {
    "customer": {
        "order:read:own",
        "logistics:read:own",
        "refund:read:own",
        "refund:create:own",
        "message:send",
        "session:read:own",
    },
    "agent": {
        "order:read:any",
        "order:write:any",
        "logistics:read:any",
        "refund:read:any",
        "refund:review",
        "approval:resolve",
        "session:takeover",
        "session:read:any",
        "message:send",
    },
    "lead": {
        # 继承 agent
        "order:read:any",
        "order:write:any",
        "logistics:read:any",
        "refund:read:any",
        "refund:review",
        "approval:resolve",
        "approval:escalate",
        "session:takeover",
        "session:read:any",
        "message:send",
    },
    "admin": {"*"},
}


def can(role: str, permission: str) -> bool:
    perms = PERMISSIONS.get(role, set())
    return "*" in perms or permission in perms


# ─── FastAPI 依赖工厂 ──────────────────────────────────────────────────────

try:
    from fastapi import Depends, HTTPException

    from .deps import get_current_user

    def require_role(*roles: str):
        async def _dep(user=Depends(get_current_user)) -> Any:
            if user.role not in roles:
                raise HTTPException(status_code=403, detail="权限不足")
            return user

        return _dep

    def require_permission(permission: str):
        async def _dep(user=Depends(get_current_user)) -> Any:
            if not can(user.role, permission):
                raise HTTPException(status_code=403, detail="权限不足")
            return user

        return _dep

except ImportError:  # fastapi 未安装
    def require_role(*roles: str):  # type: ignore[override]
        raise RuntimeError("fastapi 未安装")

    def require_permission(permission: str):  # type: ignore[override]
        raise RuntimeError("fastapi 未安装")
