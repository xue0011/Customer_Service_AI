"""企业 API 层：FastAPI app、路由、依赖、Pydantic schema。"""

from .server import create_app

__all__ = ["create_app"]
