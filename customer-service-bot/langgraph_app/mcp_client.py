"""MCP 客户端：通过 stdio 连接 MiDeviceController 仓库里的设备 MCP Server。

约定配置写在 customer-service-bot/mcp_servers.json，格式与 Claude Desktop 的
`mcpServers` 兼容，可直接复制到 Cursor / Claude Desktop 使用。

加载失败（未安装 langchain-mcp-adapters、设备服务没启动等）时返回空列表，
图会退化为「纯客服」模式并在回复里说明原因。
"""

from __future__ import annotations

import json
import logging

from .config import BASE_DIR, MCP_CONFIG

logger = logging.getLogger(__name__)


def _resolve(servers: dict) -> dict:
    """把配置里的相对 cwd 解析成绝对路径。"""
    resolved = {}
    for name, conn in servers.items():
        conn = dict(conn)
        cwd = conn.get("cwd")
        if cwd:
            conn["cwd"] = str((BASE_DIR / cwd).resolve())
        args = conn.get("args") or []
        conn["args"] = [str((BASE_DIR / a).resolve()) if a.startswith("./") else a for a in args]
        resolved[name] = conn
    return resolved


async def load_device_tools() -> list:
    """返回 LangChain Tool 列表（来自 MCP Server）。"""
    if not MCP_CONFIG.exists():
        return []
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        logger.warning("[mcp] 未安装 langchain-mcp-adapters，跳过设备工具")
        return []

    config = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
    servers = config.get("mcpServers", config)
    if not servers:
        return []
    try:
        client = MultiServerMCPClient(_resolve(servers))
        tools = await client.get_tools()
        logger.info("[mcp] 已加载设备工具: %s", [t.name for t in tools])
        return tools
    except Exception as exc:  # noqa: BLE001 - MCP 失败不应阻断客服主流程
        logger.warning("[mcp] 设备工具加载失败: %s", exc)
        return []
