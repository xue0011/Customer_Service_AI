#!/usr/bin/env bash
# Customer Service Bot —— API 调用示例（验收4）
# 用法：BASE=http://localhost:8000 ADMIN_PASSWORD=testpass123 ./scripts/api_demo.sh
# 首次运行前先 seed：python -m src.database.seed_db
set -euo pipefail

BASE=${BASE:-http://localhost:8000}
ADMIN_USERNAME=${ADMIN_USERNAME:-admin}
ADMIN_PASSWORD=${ADMIN_PASSWORD:-testpass123}

echo "► 1) 健康检查"
curl -fsS "$BASE/health"; echo

echo "► 2) 登录（$ADMIN_USERNAME）"
LOGIN=$(curl -fsS -XPOST "$BASE/api/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"$ADMIN_USERNAME\",\"password\":\"$ADMIN_PASSWORD\"}")
TOKEN=$(python -c "import sys,json;print(json.loads(sys.argv[1])['access_token'])" "$LOGIN")
echo "  token=${TOKEN:0:24}..."
AUTH="Authorization: Bearer $TOKEN"

echo "► 3) 当前用户"
curl -fsS "$BASE/api/auth/me" -H "$AUTH"; echo

echo "► 4) 上传知识库文档（切分+向量化）"
curl -fsS -XPOST "$BASE/api/admin/rag/documents" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"source":"demo","content":"7天无理由退货，商品需保持完好，标签完整，不影响二次销售。","category":"policy","title":"退货政策"}'; echo

echo "► 5) 列出知识库文档"
curl -fsS "$BASE/api/admin/rag/documents" -H "$AUTH"; echo

echo "► 6) 查询订单（需先 seed）"
curl -fsS "$BASE/api/orders/ORD-20260715-001" -H "$AUTH" || echo "  (订单未 seed，请运行: python -m src.database.seed_db)"; echo

echo "► 7) 待审批列表"
curl -fsS "$BASE/api/admin/approvals" -H "$AUTH"; echo

echo "✓ 示例完成"
