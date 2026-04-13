#!/usr/bin/env bash
set -e

BASE_URL="${BASE_URL:-http://127.0.0.1:3004}"
REQUESTS="${REQUESTS:-1000}"
CONCURRENCY="${CONCURRENCY:-50}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}═══════════════════════════════════════════${NC}"
echo -e "${BLUE}  Load Test — $BASE_URL${NC}"
echo -e "${BLUE}  $REQUESTS requests, $CONCURRENCY concurrent${NC}"
echo -e "${BLUE}═══════════════════════════════════════════${NC}"
echo ""

run_endpoint() {
  local name="$1"
  local path="$2"
  local method="${3:-GET}"
  local body="${4:-}"

  echo -e "${YELLOW}▶ $name${NC}  ($method $path)"
  local out
  if [ "$method" = "POST" ] && [ -n "$body" ]; then
    local tmpfile=$(mktemp)
    echo "$body" > "$tmpfile"
    out=$(ab -q -n "$REQUESTS" -c "$CONCURRENCY" -T "application/json" -p "$tmpfile" "$BASE_URL$path" 2>&1)
    rm -f "$tmpfile"
  else
    out=$(ab -q -n "$REQUESTS" -c "$CONCURRENCY" "$BASE_URL$path" 2>&1)
  fi

  local rps=$(echo "$out" | awk '/Requests per second/ {print $4}')
  local p50=$(echo "$out" | awk '/^  50%/ {print $2}')
  local p95=$(echo "$out" | awk '/^  95%/ {print $2}')
  local p99=$(echo "$out" | awk '/^  99%/ {print $2}')
  local failed=$(echo "$out" | awk '/^Failed requests/ {print $3}')
  local non200=$(echo "$out" | awk '/^Non-2xx responses/ {print $3}')

  local status_text="OK"
  local status_color="$GREEN"
  if [ -n "$non200" ] && [ "$non200" -gt 0 ]; then
    status_text="FAIL (non-2xx: $non200)"
    status_color="$RED"
  elif [ -n "$failed" ] && [ "$failed" -gt "$((REQUESTS / 20))" ]; then
    status_text="FAIL (failed: $failed)"
    status_color="$RED"
  fi

  echo -e "    ${status_color}${status_text}${NC}  ${rps:-?} rps | p50=${p50:-?}ms p95=${p95:-?}ms p99=${p99:-?}ms"
  echo ""
}

if ! curl -s -o /dev/null -m 3 "$BASE_URL/api/health"; then
  echo -e "${RED}✗ Backend $BASE_URL не отвечает на /api/health${NC}"
  exit 1
fi
echo -e "${GREEN}✓ Backend жив${NC}"
echo ""

run_endpoint "health"             "/api/health"
run_endpoint "landing page data"  "/api/web/pages/landing"
run_endpoint "tariffs public"     "/api/tariffs/public"
run_endpoint "site config"        "/api/site-config"
run_endpoint "flow default"       "/api/flows/default"

echo -e "${YELLOW}▶ Rate limit stress test (register endpoint, same IP)${NC}"
hit_counts=$(for i in $(seq 1 20); do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST "$BASE_URL/api/auth/register" \
    -H "Content-Type: application/json" \
    -d '{"email":"loadtest@example.com","password":"testpass123"}' 2>/dev/null
done | sort | uniq -c | sort -rn)
echo "$hit_counts" | sed 's/^/    /'
echo ""

if echo "$hit_counts" | grep -q "429"; then
  echo -e "    ${GREEN}✓ Rate limit сработал (получено 429)${NC}"
else
  echo -e "    ${YELLOW}⚠ Rate limit не сработал (нет 429) — проверь Redis/конфиг${NC}"
fi

echo ""
echo -e "${BLUE}═══════════════════════════════════════════${NC}"
echo -e "${BLUE}  Load test завершён${NC}"
echo -e "${BLUE}═══════════════════════════════════════════${NC}"
