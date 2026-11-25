"""
Customer Service Bot — 多 Agent 客服系统入口
════════════════════════════════════════════════

启动方式：
    python -m src.main                    # 默认配置启动
    python -m src.main --config config.json  # 指定配置文件

架构概览：
    Channel → MessageBus → Classifier → Agent (Presales/Aftersales)
                                       → Guardrail → Channel
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys

from loguru import logger

from .channels import DewuAdapter, JdAdapter, PinduoduoAdapter, TaobaoAdapter
from .config import AppConfig, Message, Platform, load_config
from .core.loop import CustomerServiceLoop

# ─── 日志配置 ──────────────────────────────────────────────────────────────

def setup_logging(level: str = "INFO") -> None:
    """配置日志输出。"""
    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
        colorize=True,
    )
    logger.add(
        "logs/customer_service_{time:YYYY-MM-DD}.log",
        level="DEBUG",
        rotation="00:00",
        retention="30 days",
        encoding="utf-8",
    )


# ─── 应用类 ────────────────────────────────────────────────────────────────

class CustomerServiceApp:
    """多 Agent 客服系统应用。"""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.loop = CustomerServiceLoop(config)
        self.channels: list = []

    async def setup(self) -> None:
        """初始化系统组件。"""
        logger.info("=" * 60)
        logger.info(f"  {self.config.shop_name} - 多 Agent 客服系统")
        logger.info("=" * 60)

        # 启动主循环
        await self.loop.start()

        # 启动渠道适配器
        channel_map = {
            "taobao": TaobaoAdapter,
            "pinduoduo": PinduoduoAdapter,
            "jd": JdAdapter,
            "dewu": DewuAdapter,
        }
        for channel_config in self.config.channels:
            if not channel_config.enabled:
                continue
            adapter_cls = channel_map.get(channel_config.type)
            if adapter_cls:
                adapter = adapter_cls(channel_config.config)
                await adapter.start()
                self.channels.append(adapter)
                logger.info(f"  ✓ {channel_config.type} 渠道已启动")

        logger.info("-" * 60)
        logger.info("  系统就绪，等待客户消息...")
        logger.info("-" * 60)

    async def run(self) -> None:
        """运行主循环。"""
        await self.setup()

        # 处理来自各渠道的消息
        tasks = []
        for channel in self.channels:
            tasks.append(asyncio.create_task(self._process_channel(channel)))

        # 等待所有任务（实际场景中会一直运行）
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass

    async def _process_channel(self, channel) -> None:
        """处理单个渠道的消息流。"""
        logger.info(f"[App] 开始监听渠道: {channel.channel_type}")
        async for message in channel.receive():
            try:
                response = await self.loop.handle_message(message)
                await channel.send(response)
            except Exception:
                logger.exception(f"[App] 处理消息失败: {message.id}")

    async def shutdown(self) -> None:
        """优雅关闭系统。"""
        logger.info("[App] 正在关闭系统...")

        for channel in self.channels:
            await channel.stop()

        await self.loop.shutdown()

        logger.info("[App] 系统已关闭")


# ─── CLI 入口 ──────────────────────────────────────────────────────────────

def main() -> None:
    """CLI 入口函数。"""
    parser = argparse.ArgumentParser(
        description="Customer Service Bot - 多 Agent 客服系统",
        prog="customer-service-bot",
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        default=None,
        help="配置文件路径 (JSON)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="运行演示模式",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="启动 Web 服务器（前端聊天界面，legacy）",
    )
    parser.add_argument(
        "--api",
        action="store_true",
        help="启动企业 API 服务（JWT/RBAC/审批/健康检查）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Web 服务器端口（默认 8000）",
    )
    args = parser.parse_args()

    setup_logging(args.log_level)

    # 加载配置
    config = load_config(args.config)

    # 创建应用
    app = CustomerServiceApp(config)

    # 注册信号处理
    def signal_handler(sig, frame):
        logger.info("收到退出信号")
        try:
            asyncio.run(app.shutdown())
        except Exception as e:
            logger.error(f"[Main] 关闭过程出错: {e}")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 运行
    if args.demo:
        asyncio.run(run_demo(config))
    elif args.api:
        asyncio.run(run_api(config, args.port))
    elif args.web:
        asyncio.run(run_web(config, args.port))
    else:
        try:
            asyncio.run(app.run())
        except KeyboardInterrupt:
            logger.info("用户中断")
        finally:
            asyncio.run(app.shutdown())


# ─── 演示模式 ──────────────────────────────────────────────────────────────

async def run_demo(config: AppConfig) -> None:
    """运行演示 —— 模拟几条客服消息的处理流程。"""
    logger.info("=" * 60)
    logger.info("  演示模式 - 模拟客服消息处理")
    logger.info("=" * 60)

    app = CustomerServiceApp(config)
    await app.setup()

    # 模拟消息
    demo_messages = [
        {
            "customer_id": "cust_001",
            "customer_name": "小明",
            "content": "你好，我想买一件红色的连衣裙，有什么推荐吗？",
            "content_type": "text",
        },
        {
            "customer_id": "cust_001",
            "customer_name": "小明",
            "content": "价格在300-500之间，适合日常穿的",
            "content_type": "text",
        },
        {
            "customer_id": "cust_002",
            "customer_name": "小红",
            "content": "我前天买的订单 ORD-20240101-001，怎么还没发货？",
            "content_type": "text",
        },
        {
            "customer_id": "cust_002",
            "customer_name": "小红",
            "content": "能帮我查一下物流吗？",
            "content_type": "text",
        },
        {
            "customer_id": "cust_003",
            "customer_name": "小刚",
            "content": "在吗",
            "content_type": "text",
        },
    ]

    for i, raw in enumerate(demo_messages):
        logger.info(f"\n{'─' * 40}")
        logger.info(f"📩 消息 {i+1}: [{raw['customer_name']}] {raw['content']}")
        logger.info(f"{'─' * 40}")

        message = Message(
            id=f"demo_{i}",
            platform=Platform.TAOBAO,
            customer_id=raw["customer_id"],
            customer_name=raw.get("customer_name", ""),
            content=raw["content"],
            content_type=raw.get("content_type", "text"),
            thread_id=raw.get("thread_id", raw["customer_id"]),
        )
        response = await app.loop.handle_message(message)

        logger.info(f"📤 意图: {response.intent} | Agent: {response.agent}")
        logger.info(f"📤 回复: {response.content[:200]}")

    logger.info(f"\n{'=' * 60}")
    logger.info("  演示完成")
    logger.info("=" * 60)

    await app.shutdown()


async def run_web(config: AppConfig, port: int = 8000) -> None:
    """启动 Web 服务器。"""
    from .web_server import WebServer

    app = CustomerServiceApp(config)
    await app.setup()

    web = WebServer(config, app.loop)
    try:
        await web.run(port=port)
    except KeyboardInterrupt:
        logger.info("用户中断")
    finally:
        await app.shutdown()


async def run_api(config: AppConfig, port: int = 8000) -> None:
    """启动企业 API 服务（JWT/RBAC/审批/健康检查）。

    生产用 Alembic 迁移建表（Docker CMD 已执行）；开发可用 init_db 兜底。
    """
    import uvicorn

    from .api.server import create_app
    from .auth import ensure_super_user
    from .database.db import init_db

    try:
        from .config.validate import assert_valid_config

        assert_valid_config()
    except Exception as e:  # noqa: BLE001
        if config.app_env == "production":
            raise
        logger.warning(f"[Main] 配置校验跳过（开发）：{e}")
    try:
        await init_db()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[Main] 开发建表跳过（生产请用 Alembic）：{e}")
    await ensure_super_user()

    app = create_app()
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info"))
    try:
        await server.serve()
    except KeyboardInterrupt:
        logger.info("用户中断")


if __name__ == "__main__":
    main()
