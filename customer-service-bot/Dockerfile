# ── builder stage ────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# 构建期编译依赖（ChromaDB / bcrypt / asyncpg 可能需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir --user --no-warn-script-location .

# ── runtime stage ────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# 非root用户
RUN useradd -m -u 1001 appuser

WORKDIR /app

# 从 builder 拷贝已安装的依赖
COPY --from=builder /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --chown=appuser:appuser src/ ./src/
COPY --chown=appuser:appuser prompts/ ./prompts/
COPY --chown=appuser:appuser templates/ ./templates/
COPY --chown=appuser:appuser static/ ./static/
COPY --chown=appuser:appuser data/ ./data/
COPY --chown=appuser:appuser alembic.ini ./alembic.ini
COPY --chown=appuser:appuser alembic/ ./alembic/

RUN mkdir -p data/memory data/chroma_rag data/tickets logs && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=5 --start-period=20s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=3).status==200 else 1)" || exit 1

# 启动前执行迁移，随后启动企业 API 服务
CMD ["sh", "-c", "alembic upgrade head && python -m src.main --api --port 8000"]
