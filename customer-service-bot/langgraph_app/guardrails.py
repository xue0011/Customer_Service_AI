"""输入/输出护栏：旧版 src/guardrail 的精简版，够 demo 用。"""

from __future__ import annotations

import re

# 提示注入 / 越权诱导
_INJECTION = [
    re.compile(r"忽略(之前|以上|前面|你)的?(所有)?(指令|规则|设定)"),
    re.compile(r"ignore\s+(all\s+)?(previous|above)\s+instructions", re.I),
    re.compile(r"(系统|system)\s*(提示词|prompt)", re.I),
    re.compile(r"开发者模式|developer\s*mode", re.I),
    re.compile(r"你现在(是|扮演)"),
]

# 客服不该说死的承诺
_FORBIDDEN_OUTPUT = [
    "保证全额赔付",
    "百分百退款",
    "100%退款",
    "绝对没问题",
    "无条件赔偿",
]

_PHONE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
_ID_CARD = re.compile(r"(?<!\d)(\d{6})\d{8}(\d{3}[\dXx])(?!\d)")


def mask_pii(text: str) -> str:
    """手机号 / 身份证脱敏，便于写审计日志。"""
    text = _PHONE.sub(lambda m: m.group(1)[:3] + "****" + m.group(1)[-4:], text)
    text = _ID_CARD.sub(lambda m: m.group(1) + "********" + m.group(2), text)
    return text


def check_input(text: str, max_chars: int = 2000) -> tuple[bool, str]:
    """返回 (是否放行, 拒绝原因)。"""
    if not text.strip():
        return False, "空消息"
    if len(text) > max_chars:
        return False, f"消息超过 {max_chars} 字"
    for pattern in _INJECTION:
        if pattern.search(text):
            return False, "疑似提示注入，已拦截"
    return True, ""


def check_output(text: str) -> tuple[bool, str, str]:
    """返回 (是否合规, 原因, 处理后的文本)。"""
    sanitized = text
    hit = ""
    for phrase in _FORBIDDEN_OUTPUT:
        if phrase in sanitized:
            hit = hit or phrase
            sanitized = sanitized.replace(phrase, "按售后政策处理")
    # 涉及赔付但没提人工 → 补一句兜底
    if "赔" in sanitized and "人工" not in sanitized:
        sanitized += "\n\n（涉及赔付的方案需人工客服复核后生效。）"
    return (hit == ""), (f"命中禁用话术: {hit}" if hit else ""), sanitized
