#!/bin/bash
# ============================================================
# 筑维AI - 一房一码住宅智能运维助手 一键启动脚本
# 作用：同时启动后端(FastAPI @ 8000)和前端(Vite @ 5173)
#
# 前置条件（首次运行前只需做一次）：
#   1. 后端依赖：cd backend && python -m venv venv && venv/Scripts/pip install -r requirements.txt
#   2. 前端依赖：cd frontend && npm install
#   3. 数据库配置：复制 backend/.env.example 为 backend/.env 并填好 MySQL 连接信息
#
# 运行方式（在项目根目录）：
#   bash start.sh
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
# 后端用项目虚拟环境里的 Python（依赖都装在里面）
PYTHON="$BACKEND_DIR/venv/Scripts/python.exe"
# 前端用系统 PATH 里的 node（npm install 时装的 vite 在 node_modules 里）
NODE="node"

echo "=========================================="
echo "  筑维AI - 一房一码住宅智能运维助手"
echo "=========================================="
echo ""

# ---------- 启动后端 ----------
echo "[1/2] 启动后端服务 (FastAPI @ :8000)..."
cd "$BACKEND_DIR"
"$PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!
echo "  后端PID: $BACKEND_PID"

sleep 3

# ---------- 启动前端 ----------
echo "[2/2] 启动前端服务 (Vite @ :5173)..."
cd "$FRONTEND_DIR"
"$NODE" node_modules/vite/bin/vite.js --host 0.0.0.0 --port 5173 &
FRONTEND_PID=$!
echo "  前端PID: $FRONTEND_PID"

echo ""
echo "=========================================="
echo "  服务已启动！"
echo "  前端页面:   http://localhost:5173"
echo "  后端API:    http://localhost:8000"
echo "  接口文档:   http://localhost:8000/docs"
echo "=========================================="
echo ""
echo "按 Ctrl+C 停止所有服务"

# Ctrl+C 时同时杀掉两个子进程
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM

wait
