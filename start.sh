#!/bin/bash
# Smart Room - 一房一码住宅智能运维助手
# 启动脚本：同时启动后端(FastAPI)和前端(Vite)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
PYTHON="$BACKEND_DIR/venv/Scripts/python.exe"
NODE="C:/Users/energ/.workbuddy/binaries/node/versions/22.22.2/node.exe"

echo "=========================================="
echo "  筑维AI - 一房一码住宅智能运维助手"
echo "=========================================="
echo ""

# Start backend
echo "[1/2] 启动后端服务 (FastAPI @ :8000)..."
cd "$BACKEND_DIR"
$PYTHON -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!
echo "  后端PID: $BACKEND_PID"

sleep 2

# Start frontend
echo "[2/2] 启动前端服务 (Vite @ :5173)..."
cd "$FRONTEND_DIR"
$NODE node_modules/vite/bin/vite.js --host 0.0.0.0 --port 5173 &
FRONTEND_PID=$!
echo "  前端PID: $FRONTEND_PID"

echo ""
echo "=========================================="
echo "  服务已启动！"
echo "  前端: http://localhost:5173"
echo "  后端API: http://localhost:8000"
echo "  API文档: http://localhost:8000/docs"
echo "=========================================="
echo ""
echo "按 Ctrl+C 停止所有服务"

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM

wait
