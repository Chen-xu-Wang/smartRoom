# Smart Room Project Memory

## Project: 筑维AI - 一房一码住宅智能运维助手

### Overview
基于中国建筑国际「一房一码」数字档案概念，构建AI辅助住宅维修报修系统。用户提交的完整方案设计，分前后端实现。

### Tech Stack
- Backend: Python FastAPI + SQLite
- Frontend: Vue 3 + Vite + Element Plus
- AI Agent: 自研状态机（无需外部LLM API，关键词匹配NLP）
- RAG: 本地知识库文档 + 关键词检索

### Architecture
- Backend: `backend/app/` with services (agent.py, rag.py, archive.py), api routes, SQLite DB
- Frontend: `frontend/src/` with Vue views, Pinia stores, Element Plus components
- Mock Data: 3 houses (1302, 805, 503) with full digital archives
- Knowledge Base: 4 markdown files (plumbing, electrical, hvac, general)

### Key Design Decisions
1. AI Agent用自研状态机而非LangGraph，降低部署复杂度
2. NLP用关键词字典匹配，Demo不需要真实LLM
3. 工单需人工确认（AI辅助，人类决策）
4. 维修结果自动回写houses.json（数字档案持续增长）
5. 不做BIM/3D/ERP，企业数据抽象为REST API

### Endpoints
- Backend: localhost:8000
- Frontend: localhost:5173/5174
- API Docs: localhost:8000/docs

### Files Structure
```
smartRoom/
├── backend/
│   ├── app/
│   │   ├── main.py, config.py, database.py
│   │   ├── api/ (houses, chat, workorders, maintenance)
│   │   ├── services/ (agent, rag, archive)
│   │   └── data/ (houses.json, knowledge/*.md)
│   ├── venv/
│   ├── requirements.txt, run.py, test_e2e.py
├── frontend/
│   ├── src/
│   │   ├── views/ (Home, ScanCode, ChatRepair, WorkOrderDetail, HouseArchive, PropertyDashboard, RepairTasks)
│   │   ├── components/ (ChatMessage, WorkOrderCard)
│   │   ├── stores/ (chat.js)
│   │   ├── api/, router/, styles/
│   ├── package.json, vite.config.js
├── start.sh, README.md
```
