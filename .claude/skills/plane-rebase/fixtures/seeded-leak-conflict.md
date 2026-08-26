# Seeded Leak Conflict — Dry-Run Scenario for HARD-GATE A

This document is a **documented dry-run scenario** — no actual rebase is performed.
It proves that a conflict in a core file triggers HARD-GATE A (abort), while a conflict
in a touch-point file triggers the recipe path (continue). The classifier output below
was captured from the live repo (`master`, 2026-06-20).

---

## Scenario setup

**Simulated situation:** a developer previously added a custom field directly to
`apps/api/plane/db/models/issue.py` (a core model file), violating the fork
isolation convention ("`Issue` — NO new columns"). The upstream tag `v1.4.0`
also modifies `Issue` in the same area. A `git rebase v1.4.0` produces two
conflicts:

1. `apps/api/plane/db/models/issue.py` — the leaked edit on the core model
2. `apps/api/plane/settings/common.py` — a legitimate touch-point 1 conflict
   (upstream reordered `INSTALLED_APPS`)

---

## Step 5 — Classify both conflicted files

```bash
node .claude/scripts/plane-classify-path.cjs \
  apps/api/plane/db/models/issue.py \
  apps/api/plane/settings/common.py
```

### Real classifier output (captured 2026-06-20)

```json
[
  {
    "path": "apps/api/plane/db/models/issue.py",
    "category": "core",
    "touchPointId": null,
    "reason": "core file (not a touch-point / fork app / fork package) — fork edits forbidden, relocate"
  },
  {
    "path": "apps/api/plane/settings/common.py",
    "category": "touch-point",
    "touchPointId": 1,
    "reason": "matches touch-point 1 (apps/api/plane/settings/common.py) — fork edits allowed, append-only"
  }
]
```

---

## Decision tree applied

### File 1 — `apps/api/plane/db/models/issue.py` → `category: "core"`

**HARD-GATE A fires. Mandatory response:**

```bash
git rebase --abort   # restores master to its pre-rebase state
```

The skill NEVER calls `git rebase --continue` for this file. It presents the
following via `AskUserQuestion`:

> **Rebase aborted — leak detected**
>
> File `apps/api/plane/db/models/issue.py` is classified `core` (no fork edits
> allowed). A conflict here means a fork customization leaked into a core model.
>
> **Required action before retrying the rebase:**
>
> 1. Identify the out-of-bounds edit in `issue.py` (likely a new field or method
>    added directly to the `Issue` model).
> 2. Relocate it: create a new table in a fork app
>    (e.g. `apps/api/plane/workload/models.py`) with a OneToOne FK to `Issue`.
> 3. Wire registration via touch-points 1 and 2 only.
> 4. After relocation, verify `python manage.py makemigrations --check` passes,
>    then retry `git rebase v1.4.0` from the top.
>
> No override flag exists for this gate. This is by design —
> `docs/FORK.md` §Conflict recovery step 4: "Do not resolve-and-continue — the
> leak will compound with every future rebase."

The touch-point 2 conflict (`apps/api/plane/settings/common.py`) is **never
reached** in this scenario because the abort fires on the first `core` result.
It will be resolved correctly on the next rebase attempt (after the leak is fixed).

---

### File 2 — `apps/api/plane/settings/common.py` → `category: "touch-point"` (touchPointId: 1)

This branch applies when NO `core` conflict precedes it in the loop (i.e., after
the leak is fixed and the rebase is retried).

**Action:** check if `git rerere` already replayed the resolution.

```bash
git diff --staged apps/api/plane/settings/common.py
# If the file is already staged and the diff shows fork lines re-applied → rerere fired.
# Verify it looks correct, then:
git rebase --continue
```

If rerere did NOT replay (first time seeing this specific conflict hunk):

Apply recipe from `references/rebase-recipe.md` §Touch-point 1:

1. Accept upstream's `INSTALLED_APPS` block.
2. Re-append fork app lines at the end of the in-house block:
   ```python
   "plane.ai_ext",
   "plane.workload",
   # "plane.clickup_migrate",  ← only on the sp1/clickup-migrate branch (docs/FORK.md)
   ```
3. Stage and continue:
   ```bash
   git add apps/api/plane/settings/common.py
   git rebase --continue
   ```
4. `git rerere` records this resolution automatically for future rebases.

---

## Summary

| File                                | Classifier result     | Skill action                                                                       |
| ----------------------------------- | --------------------- | ---------------------------------------------------------------------------------- |
| `apps/api/plane/db/models/issue.py` | `core`                | HARD-GATE A → `git rebase --abort` + AskUserQuestion with relocation hint          |
| `apps/api/plane/settings/common.py` | `touch-point` (id: 1) | Check rerere; if not replayed, apply touch-point 1 recipe → `git add + --continue` |

The critical invariant: **a `core` classification always aborts, never continues.**
No flag, no argument, no user instruction can bypass HARD-GATE A once the
classifier returns `category: "core"` for a conflicted file.
