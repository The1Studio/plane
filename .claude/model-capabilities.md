---

origin: theonekit-model-router
repository: The1Studio/theonekit-model-router
module: null
protected: false
---
# Model Capabilities Guide

> This file is read by the primary Claude agent to decide which provider and model to use for each delegation. When delegating via `/t1k:model-router:delegate` or transparent routing, choose the model that best fits the task requirements.

> **`.claude/providers-config.json` is the source of truth, not this file.** A model that is `enabled: false` there is never a selection candidate — `pickFromCandidates()` skips it before any tier or capability rule runs. Everything below is transcribed from that catalog; when the two disagree, the catalog wins and this file is the bug.

## Available Models (shipped enabled)

Only the newest model per family ships enabled (the kit-owner whitelist documented in the catalog's `_comment`). Tier and context window are catalog fields; "Best for" is guidance.

| Model | Provider | Tier | Context | Capabilities | Best for |
|-------|----------|------|---------|--------------|----------|
| `glm-5.2` | opencode-go | premium | 200K | text, reasoning, long-context, tool-use | Complex architecture, security review, difficult reasoning |
| `kimi-for-coding` | kimi | premium | 256K | text, reasoning, tool-use | The routed Kimi coding primary — general coding, writing, analysis |
| `kimi-k2.6` | kimi | premium | 256K | text, reasoning, vision, tool-use | Vision-pipe member; premium text fallback |
| `minimax-m3` | opencode-go | standard | **1M** | text, long-context, tool-use | Long-context specialist — the widest window in the catalog |
| `deepseek-v4-pro` | opencode-go | standard | 128K | text, reasoning, tool-use | Mid-tier reasoning without the premium tier |
| `qwen3.7-plus` | opencode-go | standard | 128K | text, tool-use | General coding when no reasoning tag is required |
| `gpt-5.4-mini` | kimi | standard | 128K | text, vision | Vision-pipe primary (benchmarked 3/3 on 2026-06-01) |
| `deepseek-v4-flash` | opencode-go | budget | 128K | text, reasoning, tool-use | Cheapest enabled text model — the shipped `modelMapping` default |

**Image generation** (enabled, but never a text-delegation candidate — they declare `image-generation` without `text`, and the selector's text floor excludes them): `gpt-image-1.5`, `gpt-image-2`. Served on `POST /v1/images/generations`, not the chat path.

### Disabled by default — do NOT route to these

They are present in `providers-config.json` for consumers who choose to re-enable them locally, and they appear throughout older docs and issues. The shipped default is off, so naming one in a `--model` flag or a `modelMapping` entry selects a model the router will not pick on its own:

<!-- mr-models: allow-disabled -->

| Family | Disabled entries |
|---|---|
| GLM | `glm-5.1`, `glm-5` |
| Kimi | `kimi-k2.7-code` (retired upstream by CCS 2026-08-18, #272), `kimi-k2-thinking`, `kimi-k2.5` (disabled on measured 6%-success evidence, #222), `kimi-k2` |
| MiMo | `mimo-v2.5-pro`, `mimo-v2.5`, `mimo-v2-pro`, `mimo-v2-omni` |
| Qwen | `qwen3.7-max`, `qwen3.6-plus`, `qwen3.5-plus` |
| MiniMax | `minimax-m2.7`, `minimax-m2.5` |
| OpenAI-owned | `gpt-5.6-luna` (protocol defect, #229), `gpt-5.4`, `gpt-5.5`, and the whole `codex` provider (`gpt-5.1`, `o3`) |
| Grok (image) | `grok-imagine-image`, `grok-imagine-image-quality` — withdrawn by CCS: no longer advertised on `/v1/models` as of 2026-08-20, while the `gpt-image-*` generators still are |

<!-- mr-models: /allow-disabled -->

**Enforced.** `tests/test-mr-doc-model-citations.sh` runs
`.claude/scripts/mr-validate-doc-model-citations.cjs` over `README.md` and every
`.claude/**/*.md`, and fails the build when one of them names a model that is not
`enabled: true` under an enabled provider in `providers-config.json` — the drift
that survived two catalog rotations in #280/#281. When a mention is deliberately
cautionary or historical, like the table above, mark it explicitly rather than
rewording around the gate:

```
<!-- mr-models: allow-disabled -->     alone on a line, opens a region
<!-- mr-models: /allow-disabled -->    alone on a line, closes it
...text...  <!-- mr-models: allow-disabled -->    trailing, that line only
```

Every exemption in the repo: `grep -rn "mr-models:" --include='*.md'`. `docs/**`
and `tests/**` are reported as advisory and never enforced — they are dated
design records and harness notes, not claims about current routing.

## Model Selection Guidelines

### By task complexity

| Task complexity | Recommended models | Why |
|----------------|-------------------|-----|
| **Simple** (list files, grep, lookup) | `deepseek-v4-flash` | Only enabled budget-tier text model — what the cheapest-tier sort picks |
| **Medium** (code review, write docs, implement feature) | `kimi-for-coding`, `deepseek-v4-pro`, `qwen3.7-plus` | Good quality/cost balance |
| **Complex** (architecture analysis, security audit, deep reasoning) | `glm-5.2` | Premium reasoning tier — what the `reasoning` sort picks first |
| **Long context** (analyze large codebase, read many files) | `minimax-m3` | 1M context window, and tool-capable (#249) |

### By task domain (suggestions)

The kit no longer ships role-shaped agents. Once you've picked an agent from the consumer's `t1k-*` roster (per `rules/mr-transparent-routing.md`), use the **task complexity** table above to pick the model. These domain hints just narrow the starting point:

| Task domain | Default model | Upgrade when |
|---|---|---|
| File discovery / grep / list | `deepseek-v4-flash` | Complex codebase, need synthesis → `kimi-for-coding` |
| Doc audit (read-only) | `kimi-for-coding` | Large docs set → `minimax-m3` |
| Doc write / README update | `kimi-for-coding` | Highly technical docs → `glm-5.2` |
| Implement / boilerplate | `kimi-for-coding` | Trivial single-file change → `deepseek-v4-flash` |
| Code review / security audit | `glm-5.2` | Quick scan only → `deepseek-v4-pro` |
| Run tests / interpret failures | `deepseek-v4-flash` | Complex multi-suite analysis → `kimi-for-coding` |
| Image content blocks (vision) | `gpt-5.4-mini` | Needs coding context too → `kimi-k2.6` |

These are **suggestions**, not defaults. You choose the best model per task.

### Known limitations

| Model | Limitation |
|-------|-----------|
| `minimax-m3` | Interleaves visible `<think>` reasoning into its reply in roughly half of runs (3/5 measured). Cosmetically noisy; correctness unaffected. |
| `kimi-k2.6` | Tool_calls with Write may fail (reasoning_content issue). Fallback auto-kicks in. |
| Image-generation models | Chat-completions path returns nothing usable — they are `POST /v1/images/generations` only, and deliberately omit the `text` capability so selection can never pick them for a normal delegation. |
| `Glob` tool (any model) | Recursive on path by default, matches FILENAME only (not full path), and does NOT expand brace patterns. Broad patterns like `*` or `[!.]*` flood with subtree results and cannot exclude subdirs (e.g. `.claude/`). Verified end-to-end via ccs proxy logs 2026-05-08 — proxy/CLIProxy/Kimi all forward Glob args correctly; the surprise is in Glob semantics. |

Limitations recorded against models that are now **disabled** are kept in git history rather than here — a caveat about a model the router cannot pick reads as a live warning and crowds out the ones that are.

## Providers

Both enabled providers authenticate with `gh auth token` (The1Studio org membership required) — no per-provider keys to manage.

| Provider | Enabled | Models | Endpoint |
|----------|---------|--------|----------|
| **OpenCode Go** | yes | glm-5.2, qwen3.7-plus, minimax-m3, deepseek-v4-pro, deepseek-v4-flash | `https://ccs.the1studio.org` |
| **Kimi (direct)** | yes | kimi-for-coding, kimi-k2.6, gpt-5.4-mini, + the image-generation set | `https://ccs.the1studio.org` |
| **Codex** | **no** | gpt-5.1, o3 — provider disabled, upstream auth dead (see closed #44) | `https://ccs.the1studio.org` <!-- mr-models: allow-disabled --> |

All providers are served by CCS through one flat `/v1/messages` endpoint, routed by model name (the legacy `/api/provider/<name>` prefixes were removed upstream and now 404).

### Provider selection guidelines

| Scenario | Provider | Why |
|----------|----------|-----|
| Default (most tasks) | OpenCode Go | Largest enabled model selection, native Anthropic-compatible endpoint |
| Kimi-specific tasks | Kimi direct | Better tool_calls support than going through OpenCode Go translation |
| OpenCode Go quota exhausted | Kimi direct | Fallback — independent quota |
| Vision (image content blocks) | Kimi direct | Both vision-capable enabled models (`gpt-5.4-mini`, `kimi-k2.6`) live there |

> Usage: `--provider kimi --model kimi-for-coding`
> Requires: `gh auth login` with The1Studio org membership.

## Cache behavior

All models auto-cache prompts ≥1024 tokens. Turn 2+ typically 98% cache hit. No action needed.
