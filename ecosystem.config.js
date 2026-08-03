// pm2 process config for the two MCP servers. `pm2 start ecosystem.config.js`.
// Each runs uvicorn via `uv run` (which puts .venv/bin on PATH -- REQUIRED so multilspy can spawn
// `jedi-language-server`; a bare python invocation without .venv/bin on PATH makes register_project hang on
// the LSP handshake). Ports/tokens come from .env.local (loaded by src/config.py). Resolvers are started
// per-project by register_project and torn down on shutdown.

module.exports = {
  apps: [
    {
      name: "code-index-read",
      cwd: __dirname,
      script: "uv",
      args: "run uvicorn main_read:app --host 0.0.0.0 --port 8210",
      interpreter: "none",
    },
    {
      name: "code-index-admin",
      cwd: __dirname,
      script: "uv",
      args: "run uvicorn main_admin:app --host 0.0.0.0 --port 8211",
      interpreter: "none",
    },
  ],
};
