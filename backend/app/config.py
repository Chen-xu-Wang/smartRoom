"""Configuration for the backend."""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
KNOWLEDGE_DIR = os.path.join(DATA_DIR, "knowledge")
HOUSES_FILE = os.path.join(DATA_DIR, "houses.json")
DB_PATH = os.path.join(BASE_DIR, "data", "smartroom.db")

# AI Configuration - if LLM_API_KEY is set, real LLM will be used; otherwise simulated mode
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")

# Server
HOST = "0.0.0.0"
PORT = 8000
