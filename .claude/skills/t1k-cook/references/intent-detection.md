---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# Intent Detection Logic

Detect user intent from natural language and route to appropriate workflow.

## Detection Algorithm

```
FUNCTION detectMode(input):
  # Priority 1: Explicit flags (override all)
  IF input contains "--yolo": RETURN "yolo"   # superset of --auto; check first
  IF input contains "--fast": RETURN "fast"
  IF input contains "--parallel": RETURN "parallel"
  IF input contains "--auto": RETURN "auto"
  IF input contains "--no-test": RETURN "no-test"

  # Priority 2: Plan path detection
  IF input matches path pattern (./plans/*, plan.md, phase-*.md):
    RETURN "code"

  # Priority 3: Keyword detection (case-insensitive)
  keywords = lowercase(input)

  IF keywords contains ["fast", "quick", "rapidly", "asap"]:
    RETURN "fast"

  IF keywords contains ["yolo"]:
    RETURN "yolo"

  IF keywords contains ["trust me", "auto", "just do it"]:
    RETURN "auto"

  IF keywords contains ["no test", "skip test", "without test"]:
    RETURN "no-test"

  # Priority 4: Complexity detection
  features = extractFeatures(input)  # comma-separated or "and"-joined items
  IF count(features) >= 3 OR keywords contains "parallel":
    RETURN "parallel"

  # Default: interactive workflow
  RETURN "interactive"
```

## Feature Extraction

Detect multiple features from natural language:

```
"implement auth, payments, and notifications" → ["auth", "payments", "notifications"]
"add login + signup + password reset"        → ["login", "signup", "password reset"]
"create dashboard with charts and tables"    → single feature (dashboard)
```

**Parallel trigger:** 3+ distinct features = parallel mode

## Mode Behaviors

| Mode | Skip Research | Skip Test | Review Gates | Auto-Approve | Parallel Exec |
|------|---------------|-----------|--------------|--------------|---------------|
| interactive | ✗ | ✗ | **Yes (stops)** | ✗ | ✗ |
| auto | ✗ | ✗ | **No (skips)** | ✓ (score≥9.5) | ✓ (all phases) |
| yolo | ✗ | ✗ | **No (defers to end)** | ✓ (artifact-gated) | ✓ (all phases) |
| fast | ✓ | ✗ | Yes (stops) | ✗ | ✗ |
| parallel | Optional | ✗ | Yes (stops) | ✗ | ✓ |
| no-test | ✗ | ✓ | Yes (stops) | ✗ | ✗ |
| code | ✓ | ✗ | Yes (stops) | Per plan | Per plan |

**Review Gates:** Human approval checkpoints between major steps (see `workflow-steps.md`).
- All modes EXCEPT `auto` and `yolo` stop at review gates for human approval.
- `auto` and `yolo` run continuously without stopping. `yolo` additionally defers every clarifying question (requirements, mid-flow ambiguity, high-risk approval) to a single end-of-run batch instead of asking up front — see `yolo-mode.md`.

## Examples

```
"/t1k:cook implement user auth"
→ Mode: interactive (default, stops at review gates)

"/t1k:cook plans/260120-auth/phase-02-api.md"
→ Mode: code (path detected, stops at review gates)

"/t1k:cook quick fix for the login bug"
→ Mode: fast ("quick" keyword, stops at review gates)

"/t1k:cook implement auth, payments, notifications, shipping"
→ Mode: parallel (4 features, stops at review gates)

"/t1k:cook implement dashboard --fast"
→ Mode: fast (explicit flag, stops at review gates)

"/t1k:cook implement everything --auto"
→ Mode: auto (NO STOPS, implements all phases continuously)

"/t1k:cook implement dashboard trust me"
→ Mode: auto ("trust me" keyword, NO STOPS)

"/t1k:cook implement the whole milestone --yolo"
→ Mode: yolo (NO STOPS; every question deferred to one end-of-run batch)
```

**Note:** `--auto`/`--yolo` flags or "trust me"/"auto"/"just do it"/"yolo" keywords enable continuous execution. `--yolo` (or the bare "yolo" keyword) additionally defers every clarifying question to a single end-of-run batch.

## Conflict Resolution

When multiple signals detected, priority order:
1. Explicit flags (`--fast`, `--auto`, etc.)
2. Path detection (plan files)
3. Keywords in text
4. Feature count analysis
5. Default (interactive)
