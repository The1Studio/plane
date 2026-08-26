#!/usr/bin/env bash
#
# Post a deploy-result notification to a Discord thread.
# Called by deploy-master.yml and deploy-staging.yml as a final `if: always()` step.
# Never fails the job: a webhook error is logged as a warning and the script exits 0.
#
# Required env (from the workflow):
#   DISCORD_WEBHOOK_URL  (secret)   DISCORD_THREAD_ID
#   DEPLOY_OUTCOME  GH_REPO  GH_REF  GH_SHA  GH_ACTOR  GH_EVENT  GH_RUN_URL
#
# Optional env — both default to production, so an unset value changes nothing:
#   ENV_LABEL  production                     -> embed title + Environment field
#   SITE_URL   https://plane.the1studio.org   -> the Site field value
#
# Production and staging share one Discord thread; ENV_LABEL is what tells the
# two apart in a thread carrying both.
#
set -uo pipefail

ENV_LABEL="${ENV_LABEL:-production}"
SITE_URL="${SITE_URL:-https://plane.the1studio.org}"
export ENV_LABEL SITE_URL

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
env_label = os.environ.get("ENV_LABEL", "production")
site_url = os.environ.get("SITE_URL", "https://plane.the1studio.org")
verb = "thành công" if ok else "thất bại"
embed = {
    "title": f"{'✅' if ok else '❌'} Plane {env_label} deploy {verb}",
    "url": os.environ.get("GH_RUN_URL", ""),
    "color": 3066993 if ok else 15158332,
    "fields": [
        {"name": "Environment", "value": env_label,                       "inline": True},
        {"name": "Repo",        "value": os.environ.get("GH_REPO", "-"),  "inline": True},
        {"name": "Branch",      "value": os.environ.get("GH_REF", "-"),   "inline": True},
        {"name": "Commit",      "value": sha or "-",                      "inline": True},
        {"name": "Bởi",         "value": os.environ.get("GH_ACTOR", "-"), "inline": True},
        {"name": "Trigger",     "value": os.environ.get("GH_EVENT", "-"), "inline": True},
        {"name": "Site",        "value": site_url,                        "inline": True},
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
