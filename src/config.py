# Intentions: single source of runtime configuration for both MCP roles (read / admin). Mirrors
# evolix-backend's src/config.py: python-dotenv loads .env.<ENV> then .env.local into the process env
# (override=False so real env vars always win), then Settings reads them. Env var names match the field
# names uppercased, no prefix (REPO_ROOT, MONGO_URI, ...).
#
# Precedence: real env > .env.<ENV> > .env.local > the code defaults below.

import os

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv(f".env.{os.environ.get('ENV', 'local')}", override=False)
load_dotenv(".env.local", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")  # env var name == field name (no prefix)

    env: str = "local"  # "local" | "prod"

    # (No repo_root here: multi-project -- each codebase's server-side root_path is seeded in the `projects`
    # collection and read from there per project; there is no global root.)

    # Code resolver backend for spread, behind the swappable Resolver seam (services/spread/lsp.py).
    # "multilspy" = multilspy-managed jedi-language-server (pip-only, no Node); "jedi"/"pyright" are aliases
    # that currently map to the same backend (see make_resolver()).
    resolver_backend: str = "multilspy"

    # Mongo persistence.
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "code_index2"

    # Semantic search.
    voyage_api_key: str = ""
    faiss_index_dir: str = "./data/indexes"

    # Query-view inlining (repo-frontier) via `claude -p`.
    claude_bin: str = "claude"
    claude_query_view_model: str = "claude-haiku-4-5-20251001"

    # MCP servers. Separate exact-match tokens per server.
    read_mcp_port: int = 8210
    admin_mcp_port: int = 8211
    read_mcp_token: str = ""
    admin_mcp_token: str = ""
    # Hosts the MCP server accepts in the Host header (DNS-rebinding protection). Behind a reverse proxy the
    # PUBLIC host must be listed or the app returns 421 Misdirected Request. Comma-separated; empty = the
    # SDK default (localhost only). Prod example: "ci.mavenic.co". Localhost is always allowed too.
    mcp_allowed_hosts: str = ""


settings = Settings()
