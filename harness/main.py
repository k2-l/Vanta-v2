"""harness 后端启动入口（`harness-api` 命令）。FastAPI 应用装配见 harness/app/。"""

from harness.app.main import run

if __name__ == "__main__":
    run()
