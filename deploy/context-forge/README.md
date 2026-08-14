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

> ### ⚠️ Verified how far, exactly
>
> The configuration here is built from ContextForge's own documented interfaces,
> and every flag was checked against its source — notably `translate --host`,
> which defaults to `127.0.0.1` and would otherwise make the bridge unreachable
> from outside the container.
>
> **It has not been executed end to end.** No Docker daemon was available when it
> was written. Treat it as a careful first draft: the shape is right, the flags
> are real, but expect to debug the first run. Please fix this notice once you've
> run it.

---

## Run it

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
