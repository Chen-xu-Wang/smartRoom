# Smart Room Project Memory

## Project: 筑维AI - 一房一码住宅智能运维助手

### Overview
基于中国建筑国际「一房一码」数字档案概念，构建AI辅助住宅维修报修系统。用户提交的完整方案设计，分前后端实现。

### Tech Stack
- Backend: Python FastAPI + 远程MySQL 8.0（8张表：user/house/user_house/house_device/repair_order/repair_message/repair_attachment/repair_record）
- Frontend: Vue 3 + Vite + Element Plus
- **AI: 状态机 + 真实大模型（tokenhub.tencentmaas.com / hy3，2026-08-27接入成功）；LLM不可用时关键词/规则兜底**
- RAG: 本地知识库Markdown + 关键词检索（作为 LLM 分析的事实依据）

### Architecture
- Backend: `backend/app/` with services (agent.py, llm.py, rag.py, archive.py), api routes, MySQL DB
- Frontend: `frontend/src/` with Vue views, Pinia stores, Element Plus components
- Mock Data: 3 houses (1302, 805, 503) with full digital archives
- Knowledge Base: 4 markdown files (plumbing, electrical, hvac, general)
- **LLM Client: `backend/app/services/llm.py`（urllib 标准库，无额外依赖；JSON容错；90s超时；异常抛出让调用方 fallback）**

### Key Design Decisions
1. AI Agent 用自研状态机（不引 LangGraph），降低部署复杂度
2. **意图理解(extract_info)与工单分析(_generate_work_order)已接入真实大模型（tokenhub hy3）；关键词匹配/规则作兜底，保证 LLM 不可用时流程不中断、A/B 契约不变；AI回复标注（大模型）/（规则）**
3. **LLM 配置在 backend/.env（LLM_API_KEY / LLM_BASE_URL / LLM_MODEL）；当前用 tokenhub + hy3 模型（2026-08-27验证通过）；备用 qnaigc（chat接口502不可用）**
4. 工单需人工确认（AI辅助，人类决策）
5. 维修结果自动回写（数字档案持续增长）
6. 不做 BIM/3D/ERP，企业数据抽象为 REST API

### Endpoints
- Backend: localhost:8000（run.py, uvicorn 单进程启动避免多进程reload混乱）
- Frontend: localhost:5173
- API Docs: localhost:8000/docs

### Files Structure
```
smartRoom/
├── backend/
│   ├── app/
│   │   ├── main.py, config.py, database.py
│   │   ├── api/ (houses, chat, workorders, maintenance)
│   │   ├── services/ (agent.py, llm.py, rag.py, archive.py)
│   │   └── data/ (houses.json, knowledge/*.md)
│   ├── venv/
│   ├── .env (gitignored: DB + LLM 配置)
│   ├── requirements.txt, run.py, test_ab_integration.py, test_e2e.py
├── frontend/
│   ├── src/
│   │   ├── views/ (Home, ScanCode, ChatRepair, WorkOrderDetail, HouseArchive, PropertyDashboard, RepairTasks)
│   │   ├── components/ (ChatMessage, WorkOrderCard)
│   │   ├── stores/ (chat.js)
│   │   ├── api/, router/, styles/
│   ├── package.json, vite.config.js
├── start.sh, README.md
```

### 调试记录
- 2026-08-27：成功接入 tokenhub.tencentmaas.com（hy3模型），extract_info + _generate_work_order 均已走真实LLM，_by_llm=True，32/32 A→B联调通过
- qnaigc：models端点正常但chat/completions所有模型均502 upstream_error，非代码问题
- Windows进程管理：uvicorn --reload 多进程时父子进程互相拉起，单进程启动（`python -m uvicorn app.main:app --port 8000` 无--reload）更稳定
- LLM超时：真实payload（7设备+5知识条目）下hy3响应约30-60s，超时设为90s
- Windows路径：不能用 `/tmp`，用 `os.path.join(os.path.dirname(__file__), "..", "filename")` 构造相对路径
- 代码改动后必须重启单进程后端，uvicorn reload 在此环境不可靠
