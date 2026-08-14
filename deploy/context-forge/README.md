# clops over HTTP, behind ContextForge

A minimal, runnable example of the thing `docs/deployment-research.md` spent a
long time deciding: **clops reachable over HTTP instead of stdio**, with a
gateway in front doing auth and routing.

Two containers:

```
  you ──HTTP──▶  gateway (ContextForge)  ──▶  clops-support
                 :4444, the only thing            :9000, internal only
                 exposed to the host              stdio ⇄ HTTP bridge
                                                  + clops-server
```

**No clops source changes are involved.** clops still speaks stdio and nothing
else; `mcpgateway.translate` runs it as a subprocess and puts an HTTP endpoint in
front. That is the whole trick, and it's why this is a deployment artifact rather
than a feature.

> ### Verified how far, exactly
>
> **The bridge is proven.** `mcpgateway.translate` was run against a real
> `clops-server`, and an MCP client spoke to it over HTTP end to end:
> `initialize` returned `"serverInfo":{"name":"clops"}`, `tools/list` returned
> **all 11 clops tools**, and `tools/call list_processes` returned the library's
> entry Op. That is the load-bearing claim of this whole directory, and it holds.
>
> **The Docker stack has not been run.** No Docker daemon was available. The
> compose file validates (`docker compose config`) and the shell script parses,
> but the containers have never started. Expect to debug the first run.
>
> Three things that only showed up by running it, now folded in: `translate`
> needs the gateway's secrets too, those secrets must be **≥ 32 characters**,
> and `translate --host` defaults to `127.0.0.1` — which inside a container
> would have made the bridge unreachable from anywhere.

---

## Test it without Docker first

Do this before touching the compose stack. It exercises the only genuinely novel
part — clops over HTTP — in about a minute, and if it fails, nothing about
Docker is to blame.

```bash
# a throwaway env with both pieces
uv venv /tmp/clops-http && VENV=/tmp/clops-http
uv pip install --python $VENV/bin/python mcp-contextforge-gateway -e .

# secrets are required even for the bridge, and must be >= 32 chars
export JWT_SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(24))")
export AUTH_ENCRYPTION_SECRET=$(python3 -c "import secrets;print(secrets.token_hex(24))")

$VENV/bin/python -m mcpgateway.translate \
  --stdio "$VENV/bin/clops-server --library clops.stdlib.business_designer" \
  --expose-streamable-http --host 127.0.0.1 --port 9000
```

In another shell:

```bash
curl -s -X POST http://127.0.0.1:9000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{
        "protocolVersion":"2025-06-18","capabilities":{},
        "clientInfo":{"name":"curl","version":"0"}}}'
```

Expect `"serverInfo":{"name":"clops",...}`. Then swap the body for
`{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}` and expect 11 tools.

If that works, clops-over-HTTP works, and anything that fails afterwards is
Docker or gateway configuration.

---

## Run the stack

```bash
cd deploy/context-forge

cp .env.example .env
pip install mcp-contextforge-gateway                      # for init_secrets
python3 -m mcpgateway.scripts.init_secrets --patch-env .env
# then set PLATFORM_ADMIN_PASSWORD in .env yourself

docker compose up -d --build
docker compose logs -f gateway        # wait for it to come up

./register-clops.sh
```

`register-clops.sh` mints an admin JWT, tells the gateway about the agent, and
prints the tool catalogue. **Expect the 11 clops tools** — `start_process`,
`step_complete`, `complete`, `need`, and the rest.

Admin UI: <http://localhost:4444/admin>

---

## Prerequisites, including one that will bite

- Docker with Compose v2.
- **ContextForge's README states arm64 is not supported in production.** On
  Apple Silicon you may need Rosetta emulation, or run the gateway from PyPI on
  the host (`uvx --from mcp-contextforge-gateway mcpgateway --port 4444`) with
  only the clops container in Docker. This example uses the GHCR image; if it
  won't start on your machine, that's the first thing to check.
- The clops repo must be **public**, or the image build has to carry git
  credentials — `CLOPS_SPEC` points at a `git+https://` URL because `clops-mcp`
  isn't on PyPI yet.

---

## Using your own Op library

Two lines change. Point `CLOPS_LIBRARY` at your module, and make sure the module
is installed in the image:

```bash
# .env
CLOPS_LIBRARY=my_ops
```

```dockerfile
# Dockerfile.clops — a published library
RUN pip install --no-cache-dir my-ops-package

# ...or a local one, copied in
COPY ./my_ops /app/my_ops
ENV PYTHONPATH=/app
```

The library needs at least one Op with `entry = True`; only those are surfaced
by `list_processes`.

## Adding a second agent

The point of the whole design: same image, different flags.

```yaml
  clops-review:
    build:
      context: .
      dockerfile: Dockerfile.clops
    environment:
      CLOPS_LIBRARY: my_review_ops
      CLOPS_PORT: "9000"
    expose: ["9000"]
```

Then `./register-clops.sh clops-review`. One gateway, two agents, separate Op
sets — and the gateway's RBAC decides who reaches which.

---

## What this example does *not* do

Being explicit, because each of these is a real gap rather than an omission:

1. **The SubagentStop hook does not work here.** clops enforces its completion
   contract through a Unix socket on the *client* machine
   (`clops/runtime/hook_server.py`). Nothing in this stack carries it, so a
   subagent that ends its turn without calling `complete` is not caught. See
   `docs/deployment-research.md` §4.1 — the fix is to re-point the hook at an
   HTTP endpoint, and it is small, but it isn't done.
2. **Run state is in memory, and dies with the container.** Fine for one
   instance per agent, which is the intended shape (§3.2). Do not scale a single
   agent to two replicas expecting them to share runs.
3. **Auth here is the gateway's own JWT/admin login, not OIDC.** ContextForge
   supports OIDC federation (Google, GitHub, Entra, Keycloak); wiring it is a
   deployment decision this example doesn't make for you.
4. **The gateway cannot scope which Ops an agent exposes** — that's what
   `--library` is for (§5.2). It *can* gate who may call which Op, via a
   `tool_pre_invoke` plugin reading `start_process`'s `process` argument (§5.3),
   which is not set up here.
5. **SQLite, single node.** Add Postgres and Redis before running more than one
   gateway replica.

## If you deploy this somewhere real

`docs/deployment-research.md` §5.6 covers the Aptible shape (Procfile services,
internal endpoints) and §5.7 covers why a FastMCP wrapper may beat a separate
gateway when you only have two or three agents. §5.8 is the short version of how
that decision moved. This example exists because ContextForge is the option that
gives you the most for free while you're still finding out what you need.
