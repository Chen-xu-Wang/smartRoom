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
                     物业人工审核纠偏 → AI智能派单（技能/负载/疲劳保护）
                                        ↓
                     维修人员现场处理 → 填写实际故障
                                        ↓
                     数据自动回写至一房一码档案
```

## 技术架构

### 后端 (Python FastAPI)
- **路径**: `backend/`
- **AI Agent**: `app/services/agent.py` - 状态机驱动的报修对话Agent（已接入真实大模型，支持规则回退）
- **RAG知识库**: `app/services/rag.py` - 运维知识检索（结合真实 LLM 分析）
- **房屋档案**: `app/services/archive.py` - 一房一码数字档案管理（MySQL + 静态档案）
- **数据库**: MySQL (工单 + 维修记录 + 对话 + 维修人员能力画像)
- **初始化数据**: `app/data/houses.json` - 房屋档案与设备清单初始导入
- **知识库**: `app/data/knowledge/` - 给排水/电气/空调/综合维修手册

### 前端 (Vue 3 + Vite + Element Plus)
- **路径**: `frontend/`
- **居民端**: 扫码进入 → AI对话报修 → 工单确认
- **物业端**: 工单审核面板 → 修改AI建议 → 派单
- **维修端**: 任务列表 → 现场处理 → 填写实际故障 → 数据回写

## 智能调度与主动运维

- **可解释智能派单**：先过滤停用、休班、技能不匹配、并发满载和当日容量耗尽人员，再综合技能、剩余容量、同类经验、楼栋熟悉度与公平性排序。
- **疲劳保护**：自动派单和普通手动派单共用容量红线；全员不满足安全条件时保留待派单，不会为了“必须分出去”而继续压单。管理员强制越权必须显式提交原因并写入审计流水。
- **批量负载均衡**：按紧急度和等待时间逐单派发，每派一单重新计算团队负载，避免批量工单集中到同一个人。
- **SLA 风险中心**：按优先级识别即将超时或已超时工单，帮助物业先处理真正紧急的问题。
- **预测性维护**：结合设备安装年限、近 180 天重复维修、未闭环记录和当前高优工单计算设备健康分，提前生成巡检建议，减少“坏了再修”。

## 快速启动

```bash
# 后端（请先创建 MySQL 数据库并执行 backend/local_schema.sql）
cd backend
python -m venv venv
source venv/bin/activate              # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

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
  - `GET /api/workorders/{id}/dispatch-plan` - 预览可解释派单方案
  - `POST /api/workorders/{id}/auto-assign` - AI 安全派单
  - `POST /api/workorders/dispatch/auto-assign-batch` - 批量负载均衡派单
  - `GET /api/workorders/dispatch/overview` - 团队负载、疲劳与 SLA 风险
  - `PUT /api/workorders/{id}/complete` - 完成维修（自动回写档案）
  - `GET /api/maintenance/history/{houseId}` - 维修历史（含重复维修预警）
  - `GET /api/maintenance/risks` - 预测性维护健康风险中心

## 测试

调度与预测性维护核心规则均为不依赖数据库的纯函数，可直接运行：

```bash
cd backend
python -m unittest discover -s tests -v
```

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

## 数据说明

系统基于「一房一码」业务概念构建房屋数字档案，当前通过 `houses.json` 导入初始房屋与设备数据并持久化至 MySQL。实际部署时可通过 API 接入企业房屋数字档案（BIM / C-SMART 等系统），AI Agent 通过统一的 Tool 调用获取房屋信息，不依赖具体数据源。
