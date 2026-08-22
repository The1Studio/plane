---
name: t1k:model-router:my-savings
description: "Show how many Opus tokens were preserved by model-router delegations over the last N days. Reports raw token counts and a relative-savings percentage. Does NOT compute USD — the kit uses quota-based CCS access, not per-token billing."
keywords: [my savings, model router savings, opus saved, delegation savings, mr savings, tokens saved]
argument-hint: "[--days N] [--user gh-login]"
effort: low
version: 3.39.4
origin: theonekit-model-router
repository: The1Studio/theonekit-model-router
module: model-router
protected: false
---

# t1k:model-router:my-savings

Reports **token volume preserved on the Opus tier** by model-router delegations. Output is in tokens and percentages — no USD figures, because The1Studio's CCS quota and Anthropic retail billing both exist and the kit can't know which (if either) the user pays.

## Usage

```
/t1k:model-router:my-savings              # last 30 days, your gh login
/t1k:model-router:my-savings --days 7     # last week
/t1k:model-router:my-savings --user alice # someone else's stats
```

## Workflow

### Step 1 — Resolve user

```bash
GH_LOGIN="${USER_FROM_FLAG:-$(gh api user --jq .login)}"
```

### Step 2 — Fetch aggregates from worker

```bash
TOKEN=$(gh auth token)
EP="${T1K_TELEMETRY_ENDPOINT:-https://t1k-telemetry.the1studio.org}"
curl -sf -H "Authorization: Bearer $TOKEN" \
  "$EP/api/contributors/mr-savings?user=${GH_LOGIN}&days=${DAYS:-30}"
```

If the curl fails or returns non-200, report `Could not fetch mr-savings for {user}. Check gh token and org membership.` and stop.

### Step 3 — Compute "Opus-tokens-preserved"

The honest metric: **every token that ran on a non-Opus model is a token NOT spent on Opus.** Sum the input + output + cached tokens across all `by_model` entries — that's the total volume that would otherwise have been spent on Opus.

```
opus_tokens_preserved = sum(by_model[*].input_tokens + output_tokens + cached_tokens)
```

For the percentage view, you'd need to know what total volume the user *would* have spent on Opus had they not delegated — which the worker can't observe. State the limitation explicitly in the render.

### Step 4 — Render

```
## Model-Router Savings — {user} (last {days} days)

| Metric | Value |
|---|---|
| Delegations recorded (request events) | {total.request_count} |
| Input tokens (preserved from Opus) | {total.input_tokens.toLocaleString()} |
| Output tokens (preserved from Opus) | {total.output_tokens.toLocaleString()} |
| Cached read tokens | {total.cached_tokens.toLocaleString()} |
| **Total Opus tokens preserved** | **{sum_all_three.toLocaleString()}** |

### By model
| Model | Requests | Input | Output | Cached | Avg latency (ms) |
|---|---|---|---|---|---|
| (one row per by_model entry) |
```

If `request_count == 0`: render

```
No request events recorded in the last {days} days.
Either no delegations ran, your provider isn't emitting model-router:request events,
or you're newly installed — give it a session of delegations and re-check.
```

If `request_count > 0` add a line under the table:

```
That's ~{sum_all_three.toLocaleString()} tokens that ran on cheap models (kimi/qwen/glm/gpt)
instead of Opus. If your Anthropic Opus rate is in the $15-input / $75-output per
million-tokens range (current Anthropic public pricing), back-of-envelope you'd
multiply input × ~$15/M + output × ~$75/M to estimate retail-billing equivalent.
The1Studio CCS quota math will differ.
```

## Why no USD column?

1. **The kit's economics are quota-based, not per-token.** Users access cheap models via The1Studio's CCS proxy, where billing is `~880 req/5hr` quotas (see `model-capabilities.md`), not USD/MTok.
2. **Anthropic public pricing changes.** Hardcoding a rate table in the skill body means maintaining a list that drifts silently.
3. **A user's Opus path varies.** Some pay Anthropic retail, some use a team key with negotiated pricing, some use CCS quota. The skill can't know which.
4. **Tokens are honest.** Token counts come directly from the model's API response — no estimation, no drift.

For users who want a USD estimate, the math is one line at any current Anthropic rate-card page. Better to put the rate-card link in front of the user than guess.

## Caveats

- **Only `request` events count.** `delegation` and `tool-use` events don't carry token counts so they're excluded.
- **"Preserved from Opus"** assumes you would have used Opus for the same work had you not delegated. If you'd have used a smaller model anyway, the saved-from-Opus framing overstates the benefit.
- **Cached read tokens** are cheap on all providers; lumping them with input tokens slightly overstates total volume "saved." Treat the cached line as directional.

## Related

- Endpoint source: `t1k-telemetry-worker/src/contributors/api-routes.ts` § `handleMrSavings`
- Per-event schema: `t1k-telemetry-worker/migrations/0010_add_model_router_events.sql`
- Kit cost-tier convention: `.claude/model-capabilities.md` (uses CCS quota / req-per-5hr terminology)
