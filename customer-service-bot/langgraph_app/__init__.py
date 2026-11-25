"""Customer Service Bot —— LangGraph 重构版核心。

与旧 ``src/`` 实现并行存在、互不依赖：
旧版是手写 Agent/Runner/工具注册表；本版把同样的业务拆成
LangGraph 状态图 + LangChain 工具 + Skill 渐进式披露 + MCP 设备工具。
"""

__version__ = "0.1.0"
