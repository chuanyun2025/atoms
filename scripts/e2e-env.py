from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
target = root / ".env.test"
if not target.exists():
    target.write_text(
        "APP_ENV=test\nAPP_ORIGIN=http://localhost:8082\nGATEWAY_PORT=8082\nCOOKIE_SECURE=false\n"
        "SESSION_SECRET="+secrets.token_urlsafe(48)+"\nSERVICE_TOKEN="+secrets.token_urlsafe(32)+"\n"
        "LLM_BASE_URL=\nLLM_MODEL=test-fixture-only\nLLM_API_KEY=\nTEST_FIXTURE=true\n",
        encoding="utf-8"
    )
print("独立测试环境配置已就绪，使用 atoms-e2e 独立项目和数据卷。")
