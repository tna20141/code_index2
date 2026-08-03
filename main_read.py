# Read MCP entry point (pm2 target). Serves the code-index navigation tools over streamable HTTP.
# Run: uv run uvicorn main_read:app --host 0.0.0.0 --port $READ_MCP_PORT   (or via pm2 / ecosystem.config.js)

from src.config import settings
from src.mcp.read_server import build_app

app = build_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=settings.read_mcp_port)
