#!/usr/bin/env python3
# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Resolve the pytest paths for fork-owned Django apps.

The master CI pytest job used to carry a HARDCODED app list, so a newly
scaffolded app's tests silently never ran — the job went green while covering
nothing of the new app, which is the most dangerous kind of pass. It happened
with `github_ext` (47 tests merged only because a human ran pytest by hand) and
again with `project_ext` (9 tests). This script removes the manual step.

Sources of truth:
  - `.claude/skills/_shared/references/fork-convention.md` → `forkApps` (registry)
  - `apps/api/plane/<app>/tests/` on disk (reality)

An app with tests on disk but missing from the registry is a hard error: that
combination means the classifier (`plane-classify-path.cjs`) also mislabels the
app's files as `core`, so the isolation audit reports false violations. Failing
here surfaces the drift instead of silently under-testing.

Usage:
    python3 .claude/scripts/plane-fork-test-paths.py           # space-separated paths
    python3 .claude/scripts/plane-fork-test-paths.py --check   # validate only, no stdout

Exits non-zero on drift or if no suites are discovered (a broken glob must not
masquerade as "nothing to test").
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONVENTION = REPO_ROOT / ".claude/skills/_shared/references/fork-convention.md"
APP_ROOT = REPO_ROOT / "apps/api/plane"


def read_registry() -> set[str]:
    if not CONVENTION.is_file():
        sys.exit(f"error: fork-convention registry not found at {CONVENTION}")

    match = re.search(r'"forkApps"\s*:\s*(\[[^\]]*\])', CONVENTION.read_text())
    if not match:
        sys.exit(f'error: no "forkApps" array found in {CONVENTION}')

    try:
        return set(json.loads(match.group(1)))
    except json.JSONDecodeError as exc:
        sys.exit(f'error: "forkApps" in {CONVENTION} is not valid JSON: {exc}')


def discover_suites() -> set[str]:
    if not APP_ROOT.is_dir():
        sys.exit(f"error: app root not found at {APP_ROOT}")

    return {
        path.parent.name
        for path in APP_ROOT.glob("*/tests")
        if path.is_dir() and not path.parent.name.startswith((".", "__"))
    }


def main() -> None:
    registry = read_registry()
    on_disk = discover_suites()

    unregistered = sorted(on_disk - registry)
    if unregistered:
        sys.exit(
            "error: these apps ship tests but are missing from `forkApps` in\n"
            f"  {CONVENTION.relative_to(REPO_ROOT)}\n"
            f"    {', '.join(unregistered)}\n"
            "Add them to the array. Until you do, their tests are excluded here AND\n"
            "plane-classify-path.cjs reports their files as `core` violations."
        )

    covered = sorted(on_disk & registry)
    if not covered:
        sys.exit("error: no fork-owned test suites discovered — the glob or layout changed")

    # Registered apps with no tests directory are legitimate (an app may own no
    # tables and no tests yet), so this is a note rather than a failure.
    for app in sorted(registry - on_disk):
        print(f"note: `{app}` is registered but ships no tests/ directory", file=sys.stderr)

    if "--check" not in sys.argv:
        print(" ".join(f"plane/{app}" for app in covered))


if __name__ == "__main__":
    main()
