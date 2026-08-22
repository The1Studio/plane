#!/usr/bin/env bash
# t1k-origin: kit=theonekit-core | repo=The1Studio/theonekit-core | module=t1k-base | protected=true
# t1k-origin: kit=theonekit-core
# t1k:statusline-full — install TheOneKit's CANONICAL statusline GLOBALLY to ~/.claude/
# so it renders in every Claude Code session (not just inside t1k projects).
#
# Single source of truth: this copies the kit's own hooks/statusline.cjs + hooks/lib/*
# — it does NOT carry its own fork. Run it from inside a t1k project (so the kit's
# .claude/hooks/statusline.cjs is present), or point at one with --from <dir>.
#
# Options:
#   --from <dir>   source the canonical statusline from <dir> (a .claude/hooks directory)
set -e

# Directory this script lives in (the skill bundle)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

FROM=""
while [ $# -gt 0 ]; do
  case "$1" in
    --from) FROM="$2"; shift 2 ;;
    -h|--help)
      sed -n '3,11p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

# Kit statusline needs these libs (relative ./lib/*); everything else is Node built-ins.
LIBS="colors transcript-parser git-info-cache statusline-private-cache model-scoped-quota"
DEST="$HOME/.claude"

# Resolve the canonical hooks dir (where statusline.cjs + lib/ live).
resolve_src() {
  if [ -n "$FROM" ]; then echo "$FROM"; return; fi
  # Skill installed inside a kit's .claude/skills/<skill>/ -> ../../hooks
  if [ -f "$SCRIPT_DIR/../../hooks/statusline.cjs" ]; then
    (cd "$SCRIPT_DIR/../../hooks" && pwd); return
  fi
  echo ""
}

SRC_HOOKS="$(resolve_src)"
if [ -z "$SRC_HOOKS" ] || [ ! -f "$SRC_HOOKS/statusline.cjs" ]; then
  echo "ERROR: canonical statusline not found." >&2
  echo "Run this from inside a TheOneKit project (so .claude/hooks/statusline.cjs exists)," >&2
  echo "or pass --from <path-to-.claude/hooks>." >&2
  exit 1
fi

echo "Source (canonical kit statusline): $SRC_HOOKS"
echo "Target: $DEST"

mkdir -p "$DEST/lib"

# Copy the statusline + its libs to the global ~/.claude (./lib/* resolves there).
cp "$SRC_HOOKS/statusline.cjs" "$DEST/statusline.cjs"
echo "  + statusline.cjs"
for lib in $LIBS; do
  src="$SRC_HOOKS/lib/$lib.cjs"
  if [ -f "$src" ]; then
    cp "$src" "$DEST/lib/$lib.cjs"
    echo "  + lib/$lib.cjs"
  else
    echo "  ! missing lib: $lib.cjs (statusline may fail)" >&2
  fi
done

# Wire ~/.claude/settings.json statusLine to run the global statusline directly.
node - <<'NODE'
const fs = require('fs');
const os = require('os');
const path = require('path');
const p = path.join(os.homedir(), '.claude', 'settings.json');
let cfg = {};
try { cfg = JSON.parse(fs.readFileSync(p, 'utf8')); } catch {}
cfg.statusLine = {
  type: 'command',
  command: 'node "$HOME/.claude/statusline.cjs"',
  padding: 0,
};
fs.writeFileSync(p, JSON.stringify(cfg, null, 2) + '\n');
console.log('  + settings.json statusLine wired at', p);
NODE

echo ""
echo "Done. Restart Claude Code to see the full statusline globally."
echo "Mode defaults to 'full'; set T1K_STATUSLINE_MODE=compact|minimal to change it."
