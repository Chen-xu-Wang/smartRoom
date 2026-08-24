"""FastAPI main application."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database import init_db
from .api import houses, chat, workorders, maintenance

app = FastAPI(
    title="筑维AI - 一房一码住宅智能运维助手",
    description="Based on China State Construction International's 'One House One Code' digital archive, "
               "this system uses AI to assist residents with maintenance reporting and work order management.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    init_db()

@app.get("/")
async def root():
    return {
        "name": "筑维AI - 一房一码住宅智能运维助手",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": {
            "houses": "/api/houses",
            "chat": "/api/chat",
            "workorders": "/api/workorders",
            "maintenance": "/api/maintenance",
        },
    }

app.include_router(houses.router)
app.include_router(chat.router)
app.include_router(workorders.router)
app.include_router(maintenance.router)
