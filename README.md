# 筑维AI - 基于「一房一码」数字档案的住宅智能运维助手

## 项目概述

基于中国建筑国际集团 MiC 模块化建筑体系中「一房一码」数字档案概念，构建一套 AI 辅助住宅维修报修系统。公司已解决「房屋数据在哪里」的问题（数字身份码 → 房屋数字档案），本系统解决「普通住户/物业如何高效使用这些数据进行维修」的问题。

## 核心流程

```
MiC模块数字身份码 → 房屋交付 → 一房一码数字档案
                                        ↓
                               住户扫码进入
                                        ↓
                          AI对话理解自然语言报修
                                        ↓
                     调用房屋数字档案（设备/管线/历史）
                                        ↓
                     RAG检索运维知识库
                                        ↓
                     AI生成结构化工单（附置信度）
                                        ↓
                     物业人工审核纠偏 → 人类决策
                                        ↓
                     维修人员现场处理 → 填写实际故障
                                        ↓
                     数据自动回写至一房一码档案
```

## 技术架构

### 后端 (Python FastAPI)
- **路径**: `backend/`
- **AI Agent**: `app/services/agent.py` - 状态机驱动的报修对话Agent
- **RAG知识库**: `app/services/rag.py` - 关键词匹配的运维知识检索
- **房屋档案**: `app/services/archive.py` - 一房一码模拟数据管理
- **数据库**: SQLite (工单 + 维修记录 + 对话)
- **模拟数据**: `app/data/houses.json` - 3套房数字档案
- **知识库**: `app/data/knowledge/` - 给排水/电气/空调/综合维修手册

### 前端 (Vue 3 + Vite + Element Plus)
- **路径**: `frontend/`
- **居民端**: 扫码进入 → AI对话报修 → 工单确认
- **物业端**: 工单审核面板 → 修改AI建议 → 派单
- **维修端**: 任务列表 → 现场处理 → 填写实际故障 → 数据回写

## 快速启动

```bash
# 后端
cd backend
python -m venv venv
./venv/Scripts/pip install fastapi uvicorn pydantic
./venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 前端
cd frontend
npm install
npx vite --host 0.0.0.0 --port 5173
```

## API文档

- Swagger UI: http://localhost:8000/docs
- 核心接口:
  - `GET /api/houses` - 房屋列表
  - `GET /api/houses/{id}` - 房屋完整数字档案
  - `POST /api/chat/init` - 初始化AI对话
  - `POST /api/chat/message` - 发送消息给AI Agent
  - `POST /api/chat/action` - 确认/修改工单
  - `GET /api/workorders` - 工单列表
  - `PUT /api/workorders/{id}/review` - 物业审核
  - `PUT /api/workorders/{id}/complete` - 完成维修（自动回写档案）
  - `GET /api/maintenance/history/{houseId}` - 维修历史（含重复维修预警）

## AI Agent设计

### 一个主Agent + 四个Tool
1. **房屋档案Tool** - 查询具体房屋的设备型号、管线位置、维修历史
2. **RAG Tool** - 检索运维知识库，匹配故障原因和维修方案
3. **工单Tool** - 生成结构化工单，附带置信度评分
4. **历史Tool** - 查询维修历史，检测重复维修

### Agent状态机
```
START → COLLECTING_INFO → INFO_COMPLETE → QUERYING_ARCHIVE
→ SEARCHING_KB → GENERATING_ORDER → ORDER_PENDING → COMPLETE
```

### 关键设计原则
- AI辅助，人类决策（工单需人工确认，物业可修改AI建议）
- 基于房屋真实数字档案（不是泛泛的维修聊天机器人）
- 维修数据回写档案（数字档案持续增长）

## 模拟数据说明

为验证方案，依据公开的一房一码业务概念构建模拟数字档案。实际部署时可通过API接入企业房屋数字档案（BIM/C-SMART等系统），AI Agent不关心数据来源，只需能通过Tool调用拿到房屋信息。
