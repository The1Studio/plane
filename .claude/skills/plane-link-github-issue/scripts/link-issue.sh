#!/usr/bin/env bash
# plane-link-github-issue — deterministic half: attach a URL as a link on a
# Plane work item via the public REST API. Judgment (which GH issue ↔ which
# work item) lives in SKILL.md; this script only performs the verified POST.
#
# Usage:
#   link-issue.sh --project <UUID> --work-item <UUID> --url <URL> [--title <TEXT>]
#
# Env (required):
#   PLANE_API_TOKEN       Plane personal API token (Settings → API tokens)
#   PLANE_WORKSPACE_SLUG  workspace slug (e.g. the1studio)
#   PLANE_BASE_URL        instance base, no trailing slash (e.g. https://plane.the1studio.org)
#
# Errors over silent fallback: any missing arg/env or non-2xx HTTP → exit 1 + message.
set -euo pipefail

project="" work_item="" url="" title=""
while [ $# -gt 0 ]; do
  case "$1" in
    --project)   project="$2"; shift 2 ;;
    --work-item) work_item="$2"; shift 2 ;;
    --url)       url="$2"; shift 2 ;;
    --title)     title="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

for v in PLANE_API_TOKEN PLANE_WORKSPACE_SLUG PLANE_BASE_URL; do
  eval "val=\${$v:-}"
  [ -n "$val" ] || { echo "ERROR: env $v is required" >&2; exit 1; }
done
check_required() { [ -n "$2" ] || { echo "ERROR: --$1 is required" >&2; exit 1; }; }
check_required project "$project"
check_required work-item "$work_item"
check_required url "$url"

# Build JSON body safely (jq preferred; fall back to printf with basic escaping).
if command -v jq >/dev/null 2>&1; then
  body="$(jq -cn --arg url "$url" --arg title "$title" \
    'if $title == "" then {url:$url} else {url:$url, title:$title} end')"
else
  esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
  if [ -n "$title" ]; then
    body="{\"url\":\"$(esc "$url")\",\"title\":\"$(esc "$title")\"}"
  else
    body="{\"url\":\"$(esc "$url")\"}"
  fi
fi

endpoint="${PLANE_BASE_URL}/api/v1/workspaces/${PLANE_WORKSPACE_SLUG}/projects/${project}/issues/${work_item}/links/"

resp="$(mktemp)"
code="$(curl -sS -o "$resp" -w '%{http_code}' -X POST "$endpoint" \
  -H "X-API-Key: ${PLANE_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "$body")"

if [ "$code" -ge 200 ] && [ "$code" -lt 300 ]; then
  echo "OK ($code): linked $url → work item $work_item"
  cat "$resp"; echo
  rm -f "$resp"
else
  echo "ERROR: Plane API returned HTTP $code" >&2
  cat "$resp" >&2; echo >&2
  rm -f "$resp"
  exit 1
fi
