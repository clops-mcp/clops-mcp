# clops over HTTP, behind ContextForge

A minimal, runnable example of the thing `docs/deployment-research.md` spent a
long time deciding: **clops reachable over HTTP instead of stdio**, with a
gateway in front doing auth and routing.

```
  you ──HTTP──▶  gateway (ContextForge)  ──┬──▶  clops-support   business_designer
                 :4444, the only thing     │      :9000, internal only
                 exposed to the host       └──▶  clops-session   session_analyzer
                                                  :9000, internal only
```

**No clops source changes are involved.** clops still speaks stdio and nothing
else; `mcpgateway.translate` runs it as a subprocess and puts an HTTP endpoint in
front. That is the whole trick, and it's why this is a deployment artifact rather
than a feature.

Two agents rather than one on purpose. The point of the design is **different Op
sets per container, not replicas** — and the two services differ by exactly one
environment variable.

> ### Verified
>
> The stack has been run end to end on Docker (OrbStack 28.3.3, **arm64**, Compose
> v2.39.2). Both agents come up, both register, and a tool call returns real data:
>
> - `POST /rpc` → `clops-support-list-processes` → `DesignBusinessAgents`
> - `POST /rpc` → `clops-session-list-processes` → `AnalyzeSession`
> - `clops-support-start-process` → a live run (`run_f785c6dd`) with its dispatch prompt
> - the gateway lists **22 tools**, 11 per agent
>
> ContextForge's README says arm64 is unsupported in production; the GHCR image
> nonetheless came up healthy and stayed healthy here.
>
> **One thing is broken and is not a configuration problem** — see
> [The tool names do not match](#the-tool-names-do-not-match). Discovery and
> invocation work; multi-step *runs* will stall.

---

## The tool names do not match

The gateway rewrites every tool name it proxies. clops publishes `list_processes`;
the gateway exposes it as `clops-support-list-processes` — its own prefix,
hyphens for underscores, **no `mcp__` at all**.

That is fine for discovery, and it is fine for one-shot calls. It breaks runs,
because clops writes tool names *into the prompts it returns*:

```
$ curl ... -d '{"method":"clops-support-start-process", ...}'

  "Call mcp__clops__complete(execution_id, output) or
   mcp__clops__need(execution_id, reason) before ending your turn."
```

A subagent driven through the gateway is being told to call
`mcp__clops__complete`, which does not exist on its tool list. The real name is
`clops-support-complete`. **Every multi-step run stalls at the first step.**

`--server-name` does not fix this. It changes the middle segment of
`mcp__<name>__<tool>`, but the gateway's scheme isn't that shape — `mcp__X__Y` is
a *Claude Code* convention for naming MCP tools locally, not something MCP or the
gateway agree to. The fix is for clops to learn the literal naming pattern its
client will see, rather than assuming one. Nothing here works around it.

Stdio clients are unaffected: Claude Code connecting directly to `clops-server`
sees `mcp__clops__complete`, which is exactly right.

---

## Test it without Docker first

Do this if anything below fails. It exercises the only genuinely novel part —
clops over HTTP — in about a minute, with no Docker involved.

```bash
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
`{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}` and expect 11 tools —
under their **real** names here, since no gateway is rewriting them.

---

## Run the stack

```bash
cd deploy/context-forge
cp .env.example .env
```

Fill in the three secrets in `.env`. They must each be **≥ 32 characters** or the
gateway refuses to start:

```bash
python3 - <<'PY'
import re, secrets, pathlib
p = pathlib.Path(".env"); t = p.read_text()
for k in ("JWT_SECRET_KEY", "AUTH_ENCRYPTION_SECRET", "PLATFORM_ADMIN_PASSWORD"):
    t = re.sub(rf"^{k}=.*$", f"{k}={secrets.token_hex(24)}", t, flags=re.M)
p.write_text(t)
PY
```

Then, **while the repo is private**, build from a local wheel:

```bash
(cd ../.. && uv build)
mkdir -p wheels && cp ../../dist/clops_mcp-*.whl wheels/

docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
```

Once `clops-mcp` is public or on PyPI, the overlay is unnecessary — plain
`docker compose up -d --build` installs `${CLOPS_SPEC}` from git.

```bash
docker compose logs -f gateway        # wait for "healthy"
./register-clops.sh                   # clops-support
./register-clops.sh clops-session     # the second agent
```

Each prints the registration and the gateway's tool list. Expect 11 tools after
the first, 22 after the second.

Call one:

```bash
TOKEN=$(docker compose exec -T gateway python3 -m mcpgateway.utils.create_jwt_token \
          --username admin@example.com --exp 10080 \
          --secret "$(grep '^JWT_SECRET_KEY=' .env | cut -d= -f2-)" 2>/dev/null)

curl -sS -X POST http://localhost:4444/rpc \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"clops-support-list-processes","params":{}}'
```

Admin UI: <http://localhost:4444/admin>

---

## Three things that will bite, all found by running this

**1. SSRF protection blocks the entire design by default.** Registering an agent
fails with a 422:

> Gateway URL contains private network address which is blocked by SSRF protection

The gateway blocks RFC 1918 destinations, and agents are *supposed* to live on a
private network. `SSRF_ALLOWED_NETWORKS` allowlists the one compose subnet, which
is why `docker-compose.yml` also **pins** that subnet — Compose otherwise assigns
one per engine (OrbStack gave 192.168.97.0/24; Docker Desktop uses 172.x), and an
allowlist naming the wrong subnet fails the same way. `SSRF_ALLOW_PRIVATE_NETWORKS=true`
also works and is much blunter.

**2. The API is versioned: `/v1/gateways`, not `/gateways`.** The unversioned path
answers **422**, not 404, so a wrong path is indistinguishable from a bad body.
Same for `/v1/tools`.

**3. Errors are masked and the access log is `/dev/null`.** Every failure is
`{"detail":"An error occurred, please try again."}` with nothing in
`docker compose logs`. Set `EXPOSE_ERROR_DETAILS=true` in `.env` and restart the
gateway to see the real validation error. It is a dev-only switch — it returns
exception detail to callers.

---

## Prerequisites

- Docker with Compose **v2.24+** (`docker-compose.local.yml` uses `!reset`).
- The clops repo must be **public** for the non-overlay path, since `CLOPS_SPEC`
  is a `git+https://` URL and `clops-mcp` isn't on PyPI yet. Until then use the
  local-wheel overlay above.

## Using your own Op library

Point `CLOPS_LIBRARY` at your module and make sure it's installed in the image:

```yaml
  clops-review:
    <<: *clops-agent
    environment:
      CLOPS_LIBRARY: my_review_ops
      CLOPS_PORT: "9000"
      JWT_SECRET_KEY: ${JWT_SECRET_KEY:?}
      AUTH_ENCRYPTION_SECRET: ${AUTH_ENCRYPTION_SECRET:?}
```

```dockerfile
# Dockerfile.clops — a published library
RUN pip install --no-cache-dir my-ops-package

# ...or a local one, copied in
COPY ./my_ops /app/my_ops
ENV PYTHONPATH=/app
```

Then `./register-clops.sh clops-review`. One gateway, three agents, separate Op
sets — and the gateway's RBAC decides who reaches which.

The library needs at least one Op with `entry = True`; only those are surfaced by
`list_processes`. It also needs a `Meta` string on every Op —
`clops.stdlib.code_review` is currently *not* usable as a third agent for exactly
this reason, and fails at import.

---

## What this example does *not* do

Being explicit, because each of these is a real gap rather than an omission:

1. **Tool names are wrong through the gateway** — see above. This is the one that
   makes runs fail rather than merely limiting them.
2. **The SubagentStop hook does not work here.** clops enforces its completion
   contract through a Unix socket on the *client* machine
   (`clops/runtime/hook_server.py`). Nothing in this stack carries it, so a
   subagent that ends its turn without calling `complete` is not caught. The
   server logs `SubagentStop enforcement disabled` and continues. See
   `docs/deployment-research.md` §4.1.
3. **Run state is in memory, and dies with the container.** Fine for one instance
   per agent, which is the intended shape (§3.2). Do not scale a single agent to
   two replicas expecting them to share runs.
4. **Auth here is the gateway's own JWT/admin login, not OIDC.** ContextForge
   supports OIDC federation (Google, GitHub, Entra, Keycloak); wiring it is a
   deployment decision this example doesn't make for you.
5. **The gateway cannot scope which Ops an agent exposes** — that's what
   `--library` is for (§5.2). It *can* gate who may call which Op, via a
   `tool_pre_invoke` plugin reading `start_process`'s `process` argument (§5.3),
   which is not set up here.
6. **SQLite, single node.** Add Postgres and Redis before running more than one
   gateway replica.

## If you deploy this somewhere real

`docs/deployment-research.md` §5.6 covers the Aptible shape (Procfile services,
internal endpoints) and §5.7 covers why a FastMCP wrapper may beat a separate
gateway when you only have two or three agents. §5.8 is the short version of how
that decision moved. This example exists because ContextForge is the option that
gives you the most for free while you're still finding out what you need.
