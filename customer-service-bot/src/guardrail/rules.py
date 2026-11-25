"""
护栏规则定义
────────────
定义回复检查的规则，支持三种类型：

  - keyword：关键词匹配（快速、确定性）
  - regex：正则表达式匹配（灵活、精确）
  - llm：LLM 语义检查（智能、全面但较慢）

规则动作：
  - block：直接拦截，返回预设消息
  - warn：记录警告但放行
  - rewrite：使用 LLM 改写后放行
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..config.schema import GuardrailRule


@dataclass
class CheckResult:
    """护栏检查结果。"""
    passed: bool
    reason: str = ""
    rule_name: str = ""
    action: str = ""
    modified_content: str | None = None


class RuleEngine:
    """规则引擎 —— 执行关键词和正则规则检查。"""

    def __init__(self, rules: list[GuardrailRule]) -> None:
        self.rules = rules
        self._compiled_rules: list[dict[str, Any]] = []

        for rule in rules:
            compiled: dict[str, Any] = {
                "name": rule.name,
                "type": rule.type,
                "action": rule.action,
                "message": rule.message,
            }
            if rule.type == "keyword":
                compiled["keywords"] = [kw.strip() for kw in rule.pattern.split(",")]
            elif rule.type == "regex":
                compiled["regex"] = re.compile(rule.pattern)
            self._compiled_rules.append(compiled)

    def check(self, content: str) -> CheckResult | None:
        """检查内容是否触发规则。

        Returns:
            CheckResult 如果触发，None 如果通过
        """
        for rule in self._compiled_rules:
            if rule["type"] == "keyword":
                if self._check_keyword(content, rule["keywords"]):
                    return CheckResult(
                        passed=False,
                        reason=f"触发关键词规则: {rule['name']}",
                        rule_name=rule["name"],
                        action=rule["action"],
                    )
            elif rule["type"] == "regex":
                if rule["regex"].search(content):
                    return CheckResult(
                        passed=False,
                        reason=f"触发正则规则: {rule['name']}",
                        rule_name=rule["name"],
                        action=rule["action"],
                    )

        return None  # 全部通过

    @staticmethod
    def _check_keyword(content: str, keywords: list[str]) -> bool:
        """检查是否包含关键词。"""
        content_lower = content.lower()
        return any(kw.lower() in content_lower for kw in keywords)


# ─── 预定义规则集 ─────────────────────────────────────────────────────────

DEFAULT_RULES = [
    GuardrailRule(
        name="no_politics",
        type="keyword",
        pattern="政治,敏感,反动,颠覆,暴恐,色情,赌博,毒品",
        action="block",
        message="您的消息包含不合规内容，已被系统拦截。",
    ),
    GuardrailRule(
        name="no_competitor_redirect",
        type="keyword",
        pattern="去别家,去淘宝,去京东,别家便宜,拼多多,其他店",
        action="warn",
        message="检测到引导离开本店的内容，请注意。",
    ),
    GuardrailRule(
        name="no_discount_abuse",
        type="keyword",
        pattern="给差评,投诉你,举报你,媒体曝光,12315",
        action="warn",
        message="检测到威胁性语言，请注意回复方式。",
    ),
    GuardrailRule(
        name="no_private_contact",
        type="regex",
        pattern=r"(微信|QQ|手机号|电话号码)\s*[:：]\s*[0-9a-zA-Z]+",
        action="block",
        message="请勿在回复中包含私人联系方式。",
    ),
    GuardrailRule(
        name="no_price_commitment",
        type="regex",
        pattern=r"最低价|全网最低|保证最低|绝对最低",
        action="rewrite",
        message="请避免使用绝对化价格承诺。",
    ),
]
