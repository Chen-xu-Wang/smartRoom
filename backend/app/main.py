"""FastAPI 后端入口（相当于 Java Spring Boot 的启动类）.

启动流程：
    1. 应用启动时触发 startup 钩子
    2. 检查 house 表是否为空，为空则自动灌入初始房屋与用户数据（首次部署免手动初始化）
    3. 注册 5 组 API 路由
"""
import os
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .api import houses, chat, workorders, maintenance, auth, admin, sensing, twin
from .config import BACKEND_DIR
from .database import query_one
from .services.dispatch_schema import ensure_dispatch_schema, seed_default_profiles
from .services.sensing_schema import ensure_sensing_schema
from .services.user_house import ensure_user_house_schema, seed_default_bindings
from .security import current_user, require_staff

app = FastAPI(
    title="筑维AI - 一房一码住宅智能运维助手",
    description="基于「一房一码」数字档案的 AI 辅助住宅维修报修系统。"
                "后端数据存储在远程 MySQL（SmartRoom 库，8 张业务表）。",
    version="2.1.0",
)

# ---------- 跨域配置 ----------
# 允许前端开发服务器（Vite，端口 5173）跨域访问后端
# 注意：开发阶段其实走的是 Vite 代理（见 frontend/vite.config.js），
# 这里放开全部来源是为了方便直接调试接口（如 Postman、手机访问）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    """应用启动钩子：检查数据库是否需要初始化基础数据."""
    try:
        # 独立于 house 是否为空执行幂等迁移，确保已有数据库也能补齐调度画像表。
        ensure_dispatch_schema()
        row = query_one("SELECT COUNT(*) AS c FROM house")
        # 主动感知：事件表、提醒表，工单来源字段（幂等）
        ensure_sensing_schema()
        # 住户与房屋绑定表（幂等）
        ensure_user_house_schema()
        if row and row["c"] == 0:
            # house 表为空说明是全新数据库 → 自动执行种子脚本
            # 注意：init_database.py 位于 backend 目录（不在 app 包内），
            # 先把 backend 目录加入模块搜索路径再导入
            print("[启动] 检测到数据库为空，开始灌入初始数据 ...")
            import sys
            from pathlib import Path
            backend_dir = str(Path(__file__).resolve().parent.parent)
            if backend_dir not in sys.path:
                sys.path.insert(0, backend_dir)
            from init_database import main as seed
            seed()
        else:
            print("[启动] 数据库连接正常，基础数据已就绪")
        # 按 username 幂等补齐维修工画像，不覆盖已有的自定义容量/技能配置。
        seed_default_profiles()
        # 演示住户默认绑定房屋（已有绑定时不覆盖）
        seed_default_bindings()
    except Exception as e:
        # 数据库连不上时打印错误但不阻止启动（方便排查配置问题）
        print(f"[启动警告] 数据库初始化检查失败：{e}")
        print("           请检查 backend/.env 中的数据库连接配置是否正确")


@app.get("/")
async def root():
    """根路径：返回服务基本信息和接口清单."""
    return {
        "name": "筑维AI - 一房一码住宅智能运维助手",
        "version": "2.1.0",
        "docs": "/docs",
        "endpoints": {
            "houses": "/api/houses",
            "chat": "/api/chat",
            "workorders": "/api/workorders",
            "maintenance": "/api/maintenance",
            "dispatch_overview": "/api/workorders/dispatch/overview",
            "maintenance_risks": "/api/maintenance/risks",
            "sensing_events": "/api/sensing/events",
            "sensing_notices": "/api/sensing/notices",
        },
    }


# ---------- 静态资源：上传附件可通过 /uploads/xxx 直接访问 ----------
_upload_dir = os.path.join(BACKEND_DIR, "uploads")
os.makedirs(_upload_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=_upload_dir), name="uploads")

@app.get("/api/health")
async def health():
    """健康检查（无需登录），前端据此判断后端是否在线."""
    return {"ok": True}


# ---------- 注册 API 路由（相当于 @RestController 扫描）----------
# 除登录接口外全部要求登录；各接口内部再按角色和数据范围校验（见 app/security.py）
_login_required = [Depends(current_user)]
app.include_router(auth.router)                                           # 认证：登录签发令牌、当前用户
app.include_router(admin.router, dependencies=[Depends(require_staff)])   # 管理后台（仅物业/管理员）
app.include_router(houses.router, dependencies=_login_required)           # 房屋档案
app.include_router(chat.router, dependencies=_login_required)             # AI 报修对话
app.include_router(workorders.router, dependencies=_login_required)       # 工单管理
app.include_router(maintenance.router, dependencies=_login_required)      # 维修历史
app.include_router(sensing.router, dependencies=_login_required)          # 主动感知：检测事件、住户提醒、复查建单
app.include_router(twin.router, dependencies=_login_required)             # 3D 数字孪生数据（按账号裁剪）
