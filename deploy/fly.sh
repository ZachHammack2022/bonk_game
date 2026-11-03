#!/usr/bin/env bash
# Deploy the bonk server to Fly.io (https://fly.io), or update it.
#
#   ./deploy/fly.sh <app-name> [region]     e.g. ./deploy/fly.sh bonk-sam ord
#
# Needs flyctl (https://fly.io/docs/flyctl/install/) and a Fly account. The
# first run makes the app and a metrics token; every run deploys the code
# in this folder to one machine and then checks it with the smoke test.
# Players open https://<app-name>.fly.dev. Regions: fly platform regions.
set -euo pipefail

APP="${1:-${FLY_APP:-}}"
REGION="${2:-${FLY_REGION:-}}"
if [ -z "$APP" ]; then
  echo "usage: $0 <app-name> [region]   (e.g. $0 bonk-sam ord)" >&2
  exit 2
fi
cd "$(dirname "$0")/.."

FLY="$(command -v fly || command -v flyctl || true)"
if [ -z "$FLY" ]; then
  echo "Install flyctl first: https://fly.io/docs/flyctl/install/" >&2
  exit 1
fi
"$FLY" auth whoami >/dev/null 2>&1 || "$FLY" auth login

if ! "$FLY" status -a "$APP" >/dev/null 2>&1; then
  echo "Making the app $APP"
  "$FLY" apps create "$APP"
fi

# A token for /metrics and /api/playtest, made once
if ! "$FLY" secrets list -a "$APP" 2>/dev/null | grep -q BONK_METRICS_TOKEN; then
  TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  "$FLY" secrets set -a "$APP" --stage BONK_METRICS_TOKEN="$TOKEN"
  echo "Metrics token (keep it somewhere safe): $TOKEN"
fi

# --ha=false and count 1: rooms live in memory, so exactly one machine
"$FLY" deploy -a "$APP" --ha=false ${REGION:+--primary-region "$REGION"}
"$FLY" scale count 1 -a "$APP" --yes

URL="https://$APP.fly.dev"
echo
if python3 -c 'import aiohttp' 2>/dev/null; then
  python3 -m bonk_game.server.smoke "$URL" || echo "The smoke test failed: see $FLY logs -a $APP" >&2
else
  echo "(pip install -r requirements-server.txt to run the smoke test from here)"
fi
echo "Play at $URL"
