#!/usr/bin/env bash
#
# Post a deploy-result notification to a Discord thread.
# Called by .github/workflows/deploy-master.yml as a final `if: always()` step.
# Never fails the job: a webhook error is logged as a warning and the script exits 0.
#
# Required env (from the workflow):
#   DISCORD_WEBHOOK_URL  (secret)   DISCORD_THREAD_ID
#   DEPLOY_OUTCOME  GH_REPO  GH_REF  GH_SHA  GH_ACTOR  GH_EVENT  GH_RUN_URL
#
set -uo pipefail

if [ -z "${DISCORD_WEBHOOK_URL:-}" ]; then
  echo "DISCORD_WEBHOOK_URL not set — skipping Discord notification."
  exit 0
fi

URL="$DISCORD_WEBHOOK_URL"
if [ -n "${DISCORD_THREAD_ID:-}" ]; then
  URL="${URL}?thread_id=${DISCORD_THREAD_ID}"
fi

PAYLOAD="$(python3 - <<'PY'
import json, os
outcome = os.environ.get("DEPLOY_OUTCOME", "unknown")
ok = outcome == "success"
sha = os.environ.get("GH_SHA", "")[:7]
embed = {
    "title": "✅ Plane deploy thành công" if ok else "❌ Plane deploy thất bại",
    "url": os.environ.get("GH_RUN_URL", ""),
    "color": 3066993 if ok else 15158332,
    "fields": [
        {"name": "Repo",    "value": os.environ.get("GH_REPO", "-"),  "inline": True},
        {"name": "Branch",  "value": os.environ.get("GH_REF", "-"),   "inline": True},
        {"name": "Commit",  "value": sha or "-",                      "inline": True},
        {"name": "Bởi",     "value": os.environ.get("GH_ACTOR", "-"), "inline": True},
        {"name": "Trigger", "value": os.environ.get("GH_EVENT", "-"), "inline": True},
        {"name": "Site",    "value": "https://plane.the1studio.org",  "inline": True},
    ],
}
print(json.dumps({"username": "Plane CI/CD", "embeds": [embed]}))
PY
)"

code="$(curl -s -o /tmp/discord_resp -w '%{http_code}' \
  -H "Content-Type: application/json" \
  -X POST -d "$PAYLOAD" "$URL" || true)"

echo "Discord webhook HTTP $code"
if [ "$code" != "204" ] && [ "$code" != "200" ]; then
  echo "WARN: Discord notification failed (HTTP $code):"
  cat /tmp/discord_resp 2>/dev/null || true
fi
exit 0
