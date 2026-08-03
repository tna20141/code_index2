# Maintain MCP entry point (pm2 target). Serves the code-index-admin curation tools over streamable HTTP.
# Run: uv run uvicorn main_admin:app --host 0.0.0.0 --port $ADMIN_MCP_PORT   (or via pm2)

from src.config import settings
from src.mcp.admin_server import build_app

app = build_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=settings.admin_mcp_port)
