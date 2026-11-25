"""
护栏检查器（Guardrail Checker）
──────────────────────────────
在 Agent 回复发送给顾客之前，进行合规检查：

  1. 关键词/正则规则快速检查（毫秒级）
  2. LLM 语义检查（智能识别违规内容）
  3. 根据规则动作处理：block / warn / rewrite
"""

from __future__ import annotations

from loguru import logger

from ..config.schema import GuardrailConfig
from ..core.runner import LLMClient
from .rules import DEFAULT_RULES, CheckResult, RuleEngine


class GuardrailChecker:
    """护栏检查器 —— 回复安全的最后一道防线。"""

    def __init__(self, config: GuardrailConfig) -> None:
        self.config = config
        self.enabled = config.enabled
        self.llm_check_enabled = config.llm_check_enabled

        # 合并默认规则和自定义规则
        all_rules = list(DEFAULT_RULES) + list(config.rules)
        self.rule_engine = RuleEngine(all_rules)

        # LLM 客户端（用于语义检查）
        self.llm_client = LLMClient(config.llm) if config.llm_check_enabled else None

        self._initialized = False

    async def initialize(self) -> None:
        """初始化护栏检查器。"""
        self._initialized = True
        rule_count = len(self.rule_engine.rules)
        logger.info(f"[Guardrail] 初始化完成，已加载 {rule_count} 条规则")

    # ── 核心检查接口 ──────────────────────────────────────────────────────

    async def check(self, content: str) -> CheckResult:
        """检查回复内容是否合规。

        Args:
            content: Agent 生成的回复内容

        Returns:
            CheckResult: 检查结果
        """
        if not self.enabled:
            return CheckResult(passed=True)

        # ── 第一层：规则引擎（关键词 + 正则）─────────────────────────────
        rule_result = self.rule_engine.check(content)
        if rule_result:
            logger.warning(f"[Guardrail] 规则命中: {rule_result.rule_name}")

            if rule_result.action == "block":
                # 找到对应规则的 message
                for rule in self.rule_engine.rules:
                    if rule.name == rule_result.rule_name:
                        rule_result.modified_content = rule.message
                        break
                return rule_result

            if rule_result.action == "warn":
                logger.warning(f"[Guardrail] 警告: {rule_result.reason}")
                # 警告不拦截，继续检查

        # ── 第二层：LLM 语义检查 ─────────────────────────────────────────
        if self.llm_check_enabled and self.llm_client:
            llm_result = await self._llm_check(content)
            if llm_result:
                return llm_result

        return CheckResult(passed=True)

    async def check_and_rewrite(self, content: str) -> tuple[bool, str]:
        """检查并尝试改写不合规内容。

        Returns:
            (是否通过, 最终内容)
        """
        result = await self.check(content)
        if result.passed:
            return True, content

        if result.action == "block":
            return False, result.modified_content or "此回复已被拦截。"

        if result.action == "rewrite" and self.llm_client:
            rewritten = await self._rewrite(content, result.reason)
            return True, rewritten or content

        if result.action == "warn":
            return True, content  # 警告但放行

        return False, content

    # ── LLM 检查 ──────────────────────────────────────────────────────────

    async def _llm_check(self, content: str) -> CheckResult | None:
        """使用 LLM 进行语义合规检查。"""
        try:
            messages = [
                {
                    "role": "system",
                    "content": """你是一个客服回复合规检查器。检查以下回复是否包含违规内容：

检查项目：
1. 是否包含政治敏感内容
2. 是否泄露商业机密（成本价、供应商信息）
3. 是否做出不实承诺（如"保证""100%""绝对"）
4. 是否包含人身攻击或歧视性语言
5. 是否引导顾客离开平台交易
6. 是否包含私人联系方式

请只输出 JSON：{"passed": true/false, "reason": "违规原因（如果通过则为空）"}""",
                },
                {"role": "user", "content": content},
            ]
            raw = await self.llm_client.chat(messages, temperature=0.0)
            import json
            text = raw["choices"][0]["message"].get("content", "{}")
            result = json.loads(text)

            if not result.get("passed", True):
                return CheckResult(
                    passed=False,
                    reason=result.get("reason", "LLM 合规检查未通过"),
                    rule_name="llm_check",
                    action="block",
                )
        except Exception:
            logger.exception("[Guardrail] LLM 检查异常")

        return None

    async def _rewrite(self, content: str, reason: str) -> str | None:
        """使用 LLM 改写不合规内容。"""
        try:
            messages = [
                {
                    "role": "system",
                    "content": f"""你是一个客服回复改写助手。请根据以下原因改写回复内容：

改写原因：{reason}

改写要求：
1. 保持原意和友好语气
2. 移除或替换不合规的部分
3. 保持专业性
4. 不要添加原内容中没有的信息""",
                },
                {"role": "user", "content": f"原回复：\n{content}\n\n请输出改写后的回复（只输出改写内容，不要解释）："},
            ]
            raw = await self.llm_client.chat(messages, temperature=0.3)
            return raw["choices"][0]["message"].get("content", content)
        except Exception:
            logger.exception("[Guardrail] 改写失败")
            return None
