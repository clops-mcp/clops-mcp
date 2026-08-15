#!/usr/bin/env bash
# Register the clops agent with the running gateway.
#
# The gateway does not discover backends on its own — you tell it about them
# once, and it persists them in its database. Re-running this is harmless; the
# gateway rejects a duplicate name.
#
# Usage:  ./register-clops.sh [service-name] [gateway-url]

set -euo pipefail

SERVICE="${1:-clops-support}"
GATEWAY="${2:-http://localhost:4444}"

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  echo "error: no .env here. Copy .env.example and fill it in first." >&2
  exit 1
fi

JWT_SECRET_KEY="$(grep -E '^JWT_SECRET_KEY=' .env | cut -d= -f2-)"
ADMIN_EMAIL="$(grep -E '^PLATFORM_ADMIN_EMAIL=' .env | cut -d= -f2- || true)"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@example.com}"

if [[ -z "${JWT_SECRET_KEY}" ]]; then
  echo "error: JWT_SECRET_KEY is empty in .env" >&2
  exit 1
fi

# 2>/dev/null because the gateway's config module logs to stderr on import;
# only stdout is captured into TOKEN, but the noise is confusing to watch.
echo "==> minting an admin token"
TOKEN="$(docker compose exec -T gateway \
  python3 -m mcpgateway.utils.create_jwt_token \
    --username "${ADMIN_EMAIL}" --exp 10080 --secret "${JWT_SECRET_KEY}" \
  2>/dev/null | tr -d '\r\n')"

if [[ -z "${TOKEN}" ]]; then
  echo "error: could not mint a token — is the gateway container up?" >&2
  exit 1
fi

# The URL is the compose service name, not localhost — this request is telling
# the gateway how *it* should reach the agent, and it resolves names on the
# internal network.
#
# `/v1/gateways`, not `/gateways`. ContextForge 1.0.x versions its API, and the
# unversioned path answers with a 422 rather than a 404, so getting this wrong
# looks exactly like a malformed body.
echo "==> registering ${SERVICE} with ${GATEWAY}"
BODY="$(curl -sS -X POST "${GATEWAY}/v1/gateways" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"${SERVICE}\",\"url\":\"http://${SERVICE}:9000/sse\",\"transport\":\"SSE\"}" \
  -w '\n%{http_code}')"

STATUS="$(tail -n1 <<<"${BODY}")"
BODY="$(sed '$d' <<<"${BODY}")"

if [[ "${STATUS}" != "200" && "${STATUS}" != "201" ]]; then
  echo "    HTTP ${STATUS}: ${BODY}" >&2
  # The gateway returns "An error occurred, please try again." for everything
  # unless EXPOSE_ERROR_DETAILS=true, and its access log goes to /dev/null.
  if [[ "${BODY}" == *"please try again"* ]]; then
    echo >&2
    echo "    The real reason is masked. Set EXPOSE_ERROR_DETAILS=true in .env," >&2
    echo "    'docker compose up -d gateway', and retry to see it." >&2
  fi
  exit 1
fi

python3 -c "
import json,sys
d = json.loads(sys.argv[1])
for k in ('id','name','url','transport','status','enabled','reachable'):
    if k in d: print(f'    {k:12} {d[k]}')
" "${BODY}"

echo
echo "==> tools the gateway now sees"
curl -fsS "${GATEWAY}/v1/tools" -H "Authorization: Bearer ${TOKEN}" \
  | python3 -c "
import json,sys
d = json.load(sys.stdin)
items = d if isinstance(d, list) else (d.get('data') or d.get('items') or [])
print(f'    {len(items)} tools')
for t in items: print('   ', t.get('name'))
"

cat <<EOF

Expect 11 tools. Note the names: the gateway rewrites them to
'${SERVICE}-list-processes' and so on — its own prefix, hyphens for
underscores, no 'mcp__'. That rewriting has a consequence; see the README
section "The tool names do not match".

Call one:
  curl -sS -X POST ${GATEWAY}/rpc \\
    -H "Authorization: Bearer \$TOKEN" -H 'Content-Type: application/json' \\
    -d '{"jsonrpc":"2.0","id":1,"method":"${SERVICE}-list-processes","params":{}}'

Admin UI: ${GATEWAY}/admin
EOF
