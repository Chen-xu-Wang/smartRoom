"""后端启动脚本.

运行方式（在 backend 目录下）：
    方式一（推荐，用虚拟环境的 Python）：
        venv\\Scripts\\python.exe run.py
    方式二（先用 uvicorn 命令）：
        venv\\Scripts\\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000

说明：
    - reload=True 表示代码修改后自动重启（开发模式专用，
      相当于 Spring Boot DevTools 的热重载）
    - 启动后访问 http://localhost:8000/docs 可以看到自动生成的
      Swagger 接口文档（FastAPI 自带，Java 里要引 Knife4j/SpringDoc）
"""
import uvicorn
from app.config import HOST, PORT

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=True)
