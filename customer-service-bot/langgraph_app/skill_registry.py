"""Skill 注册表 —— 渐进式披露（Progressive Disclosure）。

理念：启动时只加载每个 skill 的 name/description（catalog，很小），
真正需要时才读取 SKILL.md 正文注入上下文（load），避免把全部提示词塞进 system prompt。

SKILL.md 采用 frontmatter：
    ---
    name: aftersales
    description: 售后：订单/物流/退款/退货
    triggers: 退款,退货,物流,订单
    ---
    # 正文（流程、话术、边界）
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import SKILLS_DIR


def _parse(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text.strip()
    _, front, body = text.split("---", 2)
    meta: dict[str, str] = {}
    for line in front.strip().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    return meta, body.strip()


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    triggers: tuple[str, ...]
    body: str
    path: Path


class SkillRegistry:
    def __init__(self, root: Path = SKILLS_DIR) -> None:
        self.root = Path(root)
        self._skills: dict[str, Skill] = {}
        self.reload()

    def reload(self) -> None:
        self._skills.clear()
        for file in sorted(self.root.glob("*/SKILL.md")):
            meta, body = _parse(file.read_text(encoding="utf-8"))
            name = meta.get("name") or file.parent.name
            triggers = tuple(t.strip() for t in meta.get("triggers", "").split(",") if t.strip())
            self._skills[name] = Skill(name, meta.get("description", ""), triggers, body, file)

    # ── 两级读取 ──────────────────────────────────────────────────────────

    def catalog(self) -> list[dict]:
        """第一级：只给模型看目录（名称 + 一句描述）。"""
        return [{"name": s.name, "description": s.description} for s in self._skills.values()]

    def load(self, name: str) -> str:
        """第二级：真正用到时才读全文。"""
        skill = self._skills.get(name)
        if skill is None:
            raise KeyError(f"未知 skill: {name}；可选: {', '.join(self._skills) or '无'}")
        return skill.body

    # ── 兜底路由（无 LLM 时用关键词） ──────────────────────────────────────

    def match(self, text: str) -> tuple[str | None, int]:
        best: str | None = None
        best_hits = 0
        for skill in self._skills.values():
            hits = sum(1 for trigger in skill.triggers if trigger in text)
            if hits > best_hits:
                best, best_hits = skill.name, hits
        return best, best_hits


_registry: SkillRegistry | None = None


def get_registry() -> SkillRegistry:
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry
