"""文档切分：递归字符切分（段落 → 句子 → 长度），带重叠。

不引入 langchain，保持依赖轻量。
"""

from __future__ import annotations

import re


def chunk_text(content: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """将长文本切分为带重叠的块。

    策略：先按空行分段；超长段落按句号切；最后相邻块叠加尾部重叠。
    """
    if not content or not content.strip():
        return []
    content = content.strip()
    chunks: list[str] = []
    current = ""

    for para in re.split(r"\n\s*\n", content):
        para = para.strip()
        if not para:
            continue
        if len(current) + len(para) <= chunk_size:
            current = f"{current}\n\n{para}" if current else para
        else:
            if current:
                chunks.append(current)
            if len(para) > chunk_size:
                current = _split_long(para, chunk_size)
            else:
                current = para
    if current:
        chunks.append(current)

    # 叠加重叠
    if overlap > 0 and len(chunks) > 1:
        result = [chunks[0]]
        for i in range(1, len(chunks)):
            prev = chunks[i - 1]
            tail = prev[-overlap:] if len(prev) > overlap else prev
            result.append(f"{tail}{chunks[i]}")
        chunks = result

    return [c for c in chunks if c.strip()]


def _split_long(text: str, chunk_size: int) -> str:
    """超长段落按句号切分，返回首块（其余由外层循环处理）。"""
    sentences = re.split(r"(?<=[。.!?；;])\s*", text)
    cur = ""
    for s in sentences:
        if len(cur) + len(s) <= chunk_size:
            cur = f"{cur}{s}" if cur else s
        else:
            return cur or s[:chunk_size]
    return cur
