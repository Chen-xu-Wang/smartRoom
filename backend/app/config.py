"""统一配置模块 —— 整个后端所有配置的唯一入口.

作用（相当于 Java Spring Boot 的 application.yml + @Configuration 类）：
    1. 启动时加载 backend/.env 文件里的环境变量
    2. 把环境变量转换成 Python 常量，供其他模块导入使用
    3. 其他任何模块需要配置时，只从这里拿，不在代码里写死

使用方式（其他文件中）：
    from app.config import DB_HOST, PORT   # 直接导入常量即可

注意：修改 .env 后需要重启后端服务才会生效。
"""
import os
from pathlib import Path

# ------------------------------------------------------------------
# 加载 .env 环境变量文件
# ------------------------------------------------------------------
# BASE_DIR = app 目录，BACKEND_DIR = backend 目录（.env 就放在这里）
BASE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = BASE_DIR.parent

# load_dotenv() 会把 .env 文件中的键值对读进环境变量（不会覆盖已存在的）
# find_dotenv() 自动向上查找 .env 文件位置
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(str(BACKEND_DIR / ".env")))

# ------------------------------------------------------------------
# 数据路径配置（静态参考数据）
# ------------------------------------------------------------------
# data 目录：存放房屋档案补充信息、AI 运维知识库等静态文件
DATA_DIR = os.path.join(BASE_DIR, "data")
# 知识库目录：RAG 检索用的维修手册（Markdown 文件）
KNOWLEDGE_DIR = os.path.join(DATA_DIR, "knowledge")
# 房屋档案补充信息文件：户型、MiC 模块号、管线布局等静态描述性信息
# （说明：这类「不常变化的档案描述」暂存本地 JSON；房屋、设备、工单等
#   业务数据已全部存入 MySQL 数据库，见 app/database.py）
HOUSE_PROFILES_FILE = os.path.join(DATA_DIR, "house_profiles.json")
# 演示数据源：种子脚本 init_database.py 用来往 MySQL 灌初始数据
HOUSES_FILE = os.path.join(DATA_DIR, "houses.json")

# ------------------------------------------------------------------
# MySQL 数据库配置
# ------------------------------------------------------------------
# 各项含义：
#   DB_HOST     数据库服务器地址
#   DB_PORT     端口号（你们的服务器是 13306，不是默认 3306）
#   DB_USER     用户名
#   DB_PASSWORD 密码（从 .env 读取，不写死在代码里）
#   DB_NAME     库名（与 Java 端共用同一个库，共 8 张表）
# os.getenv("键", 默认值)：读环境变量，不存在时用默认值
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "SmartRoom")
# 连接池大小：同时保持的数据库连接数量上限
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))

# ------------------------------------------------------------------
# AI 大模型配置（预留，当前未启用）
# ------------------------------------------------------------------
# 目前 AI 分析用的是关键词匹配模拟实现（app/services/agent.py）。
# 后续接真实大模型时，在 .env 里填上这三项即可，不用改这里。
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

# ------------------------------------------------------------------
# 后端服务配置
# ------------------------------------------------------------------
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
