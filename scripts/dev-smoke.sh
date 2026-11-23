#!/usr/bin/env bash
# Exercise the documented quickstart against a running `make dev` stack:
# API readiness, console login, and the React console with its assets.
# Used by CI on a clean checkout so the first-run path cannot regress silently.
#
#   make dev && make dev-smoke
#   WEBUI_URL=http://127.0.0.1:15000 API_URL=http://127.0.0.1:18000 scripts/dev-smoke.sh
set -euo pipefail

WEBUI_URL="${WEBUI_URL:-http://localhost:5000}"
API_URL="${API_URL:-http://localhost:8000}"
WEBUI_USERNAME="${WEBUI_USERNAME:-admin}"
WEBUI_PASSWORD="${WEBUI_PASSWORD:-nidavellir}"
TIMEOUT="${SMOKE_TIMEOUT:-180}"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
jar="$work/cookies"

fail() { echo "dev-smoke: FAIL: $*" >&2; exit 1; }
status() { curl -sS -o "${2:-/dev/null}" -w '%{http_code}' -b "$jar" -c "$jar" "$1" || true; }

wait_for() {
  local url="$1" deadline=$((SECONDS + TIMEOUT))
  until [ "$(status "$url" 2>/dev/null)" = 200 ]; do
    [ "$SECONDS" -lt "$deadline" ] || fail "$url not ready after ${TIMEOUT}s"
    sleep 2
  done
  echo "dev-smoke: ready $url"
}

wait_for "$API_URL/ready"
wait_for "$WEBUI_URL/login"

status "$WEBUI_URL/login" "$work/login.html" >/dev/null
csrf="$(sed -n 's/.*name="csrf_token" value="\([^"]*\)".*/\1/p' "$work/login.html" | head -n1)"
[ -n "$csrf" ] || fail "no CSRF token on the login page"

code="$(curl -sS -o /dev/null -w '%{http_code}' -b "$jar" -c "$jar" \
  --data-urlencode "csrf_token=$csrf" \
  --data-urlencode "username=$WEBUI_USERNAME" \
  --data-urlencode "password=$WEBUI_PASSWORD" \
  "$WEBUI_URL/login")"
[ "$code" = 302 ] || fail "login returned HTTP $code (expected a 302 redirect)"
echo "dev-smoke: logged in as $WEBUI_USERNAME"

code="$(status "$WEBUI_URL/console" "$work/console.html")"
[ "$code" = 200 ] || fail "/console returned HTTP $code: $(head -c 200 "$work/console.html")"

assets="$(grep -oE '/static/console/[^"]+\.(js|css)' "$work/console.html" | sort -u)"
[ -n "$assets" ] || fail "/console references no built JS/CSS assets"
for asset in $assets; do
  code="$(status "$WEBUI_URL$asset")"
  [ "$code" = 200 ] || fail "$asset returned HTTP $code"
done
echo "dev-smoke: console and $(wc -w <<<"$assets") assets served"
echo "dev-smoke: OK"
