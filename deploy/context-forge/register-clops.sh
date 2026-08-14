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

echo "==> minting an admin token"
TOKEN="$(docker compose exec -T gateway \
  python3 -m mcpgateway.utils.create_jwt_token \
    --username "${ADMIN_EMAIL}" --exp 10080 --secret "${JWT_SECRET_KEY}" \
  | tr -d '\r\n')"

# The URL is the compose service name, not localhost — this request is telling
# the gateway how *it* should reach the agent, and it resolves names on the
# internal network.
echo "==> registering ${SERVICE} with ${GATEWAY}"
curl -fsS -X POST "${GATEWAY}/gateways" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"${SERVICE}\",\"url\":\"http://${SERVICE}:9000/sse\"}" \
  | sed 's/^/    /'

echo
echo "==> tools the gateway now sees"
curl -fsS "${GATEWAY}/tools" -H "Authorization: Bearer ${TOKEN}" \
  | (command -v jq >/dev/null && jq -r '.[].name' || cat) \
  | sed 's/^/    /'

echo
echo "Expect the 11 clops tools (start_process, step_complete, complete, ...)."
echo "Admin UI: ${GATEWAY}/admin"
