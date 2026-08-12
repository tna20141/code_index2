# Deploying code_index2 to a VPS

Shape: **MongoDB in Docker; the two MCP servers run natively (pm2); nginx terminates TLS in front.**

```
internet --HTTPS--> nginx --HTTP(127.0.0.1)--> pm2: code-index-read (8210)
                                            \-> pm2: code-index-admin (8211)
                                                     |
                                            Docker: mongo (127.0.0.1:27017)
```

## 1. Host prerequisites

```bash
# Docker (for Mongo)
curl -fsSL https://get.docker.com | sh && sudo usermod -aG docker $USER   # re-login after

# uv (runs the app; puts .venv/bin on PATH so jedi-language-server can spawn)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Node + pm2 + the claude CLI (query-views shell out to `claude -p`)
#   install node (nvm or distro pkg), then:
npm i -g pm2 @anthropic-ai/claude-code
claude login          # authenticate the CLI -- query-views won't work until this is done

# git is required (spread shells out to it) -- usually already present
```

Also: **every indexed repo must exist on the VPS** at the path stored in its `projects.root_path` (spread
reads real files there, and `claude -p` runs `cd`'d into it).

## 2. MongoDB (Docker)

```bash
cd code_index2/deploy
cp .env.mongo.example .env.mongo
#  edit .env.mongo: set MONGO_ROOT_USER + a strong MONGO_ROOT_PASSWORD (openssl rand -hex 24)
docker compose -f docker-compose.mongo.yml --env-file .env.mongo up -d
docker compose -f docker-compose.mongo.yml logs -f    # wait for "Waiting for connections"
```

Move your data (the local Mongo has your seeded projects/entities):
```bash
# on the LOCAL machine:
mongodump --uri="mongodb://localhost:27017" --db=code_index2 --archive | \
  ssh user@vps "docker exec -i code-index-mongo mongorestore \
    --uri='mongodb://codeindex:<pass>@localhost:27017/?authSource=admin' --archive --db=code_index2"
```
(Or seed the VPS fresh by re-running the scan there.)

## 3. The app (pm2)

```bash
cd code_index2
uv sync
cp .env.prod.example .env.prod
#  edit .env.prod: MONGO_URI (with the mongo password), VOYAGE_API_KEY, READ_MCP_TOKEN, ADMIN_MCP_TOKEN
#  (strong random: openssl rand -hex 32). The ecosystem sets ENV=prod so this file is loaded.

pm2 start ecosystem.config.js
pm2 save            # persist the process list
pm2 startup         # print+run the systemd hook so pm2 (and the servers) come back on reboot
pm2 logs            # verify both started; first spread warms jedi (a few seconds)
```
The servers now listen on 127.0.0.1:8210 / :8211 (not public).

## 4. nginx + TLS

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/code-index
#  edit it: replace YOUR_HOST with your domain; optionally uncomment the admin IP allowlist
sudo ln -s /etc/nginx/sites-available/code-index /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# TLS (fills in the :443 block + redirect):
sudo certbot --nginx -d <your-host>
```

Endpoints after this:
- read : `https://<host>/read/mcp/`   (Authorization: Bearer <READ_MCP_TOKEN>)
- admin: `https://<host>/admin/mcp/`  (Authorization: Bearer <ADMIN_MCP_TOKEN>)

## 5. Point a client at it

```bash
claude mcp add code-index       --transport http --url https://<host>/read/mcp/  \
  --header "Authorization: Bearer <READ_MCP_TOKEN>"
claude mcp add code-index-admin --transport http --url https://<host>/admin/mcp/ \
  --header "Authorization: Bearer <ADMIN_MCP_TOKEN>"
```

## Notes / gotchas

- **Firewall:** open 80/443 only. Do NOT expose 8210/8211/27017 -- they're localhost-bound by design.
- **Admin is the privileged surface** (mutates the index, spends money via `claude -p`). Consider the IP
  allowlist in nginx.conf, or don't expose `/admin/` publicly at all (tunnel to it over SSH instead).
- **claude CLI auth is per-user/host** -- if pm2 runs the app as a different user than the one you ran
  `claude login` as, query-views fail (falls back to verbatim bodies). Run both as the same user.
- **Sanity-check the DB after restore:** `uv run python scripts/sanity_check.py`.
