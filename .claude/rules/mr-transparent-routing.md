---
origin: theonekit-model-router
repository: The1Studio/theonekit-model-router
module: null
protected: false
---
# Model Router — Transparent Routing

When transparent routing is enabled, swap the **model** that runs each subagent — keep the agent's identity, prompt, and tools intact. This is what preserves engine-kit specialization (Unity DOTS, Cocos, etc.): the resolved Unity agent still runs, just on a cheap LLM instead of Opus.

## Activation Check

Read `.claude/t1k-config-mr.json`. The hook + rule both only fire when:
- File exists AND `modelRouter.enabled` is `true` AND `modelRouter.mode` is `"transparent"`

If any condition is false, this rule is inert.

## How It Works

Two mechanisms cooperate:

### 1. `mr-task-interceptor.cjs` (PreToolUse on `Task`)

When the main session spawns a subagent via the `Task` tool, the hook resolves the agent's `.md`, reads its `model:` frontmatter, and looks that tier up in `modelRouter.modelMapping`. On a match — and unless the agent is in `excludeAgents` or floored by one of the policies below — it runs `mr-delegate.sh` synchronously, DENIES the original Task, and returns the cheap delegation's stdout as a `systemMessage`, so the parent sees it as the Task's result. Otherwise: silent passthrough to Anthropic.

This is the primary mechanism, and it is mechanical and deterministic — it runs whether or not you read this rule. Full algorithm, every config key, and the worked examples: `docs/mr-transparent-routing.md`.

### 2. Delegation Bias (this rule, behavioral)

For **main-session work** that doesn't go through `Task` (inline `Edit` / `Write` / `Bash`), you decide whether to delegate. The interceptor only catches Task spawns; mainline edits stay on Opus unless you redirect them yourself.

## Step 0 — MANDATORY pre-tool consultation (mainline only)

**Before ANY inline Edit / Write / Bash that mutates user files, evaluate Delegation Bias.** The Task interceptor handles delegated work for you. This step is for the rest.

The check is one sentence: *"Is this task mechanical, boilerplate, or single-purpose?"*

- **Yes** → spawn it via `Task` with the appropriate `subagent_type` (e.g. `t1k-fullstack-developer` for implementation, `t1k-code-reviewer` for review). The interceptor will route to a cheap model automatically. If no `subagent_type` fits, call `mr-delegate.sh` directly with a sensible agent name.
- **No** → proceed with inline Edit/Write/Bash. State briefly why (e.g. "multi-file refactor needing cross-file context, inlining").

Skipping this step and going straight to inline Read+Edit burns Opus tokens for work a cheap model could do. The session-start hook `mr-transparent-routing-reminder.cjs` reinforces this — if you see `[t1k:transparent-routing] ACTIVE`, Step 0 is required.

## Step 0.5 — Parallel sub-agent dispatch (Agent tool, TeamCreate)

When fanning out parallel sub-agents for mechanical code work, pick the narrowest specialized T1K agent that fits the task. The transparent-routing interceptor will route the agent to a cheap provider automatically via `modelMapping` — no need to name a v1 cheap-coder shim.

| Task pattern | Preferred subagent_type |
|---|---|
| Mass rename, mechanical refactor, edit-per-plan | `t1k-fullstack-developer` |
| Read-only exploration ("find/list/grep") | `Explore` (built-in) |
| Run tests + report results | `t1k-tester` |
| Code review (read-only with Bash for lint/grep) | `t1k-code-reviewer` |
| Doc audit (read-only) or doc writes per spec | `t1k-docs-manager` |
| Multi-server MCP tool invocation | `t1k-mcp-manager` |

`general-purpose` is the FALLBACK when no specialized T1K agent matches. Default bias: pick the narrowest specialist that fits, not the broadest generalist.

## Delegation Bias — Prefer delegation for mechanical work

The primary motivation is **Opus token preservation**. Cheap subagents cost roughly 1-5% of Opus per token.

| Task pattern | Default |
|---|---|
| Single-file rename, format, lint-fix, add boilerplate | **Delegate** (Task → implementer-type agent) |
| Run a test suite + report results | **Delegate** (Task → tester) |
| Update README / docstring / comment | **Delegate** (Task → docs-writer) |
| Code review of changed lines (single PR / small scope) | **Delegate** (Task → reviewer) |
| Find files matching a pattern, list usages, search refs | **Delegate** (Task → explorer) |
| Audit existing docs for gaps | **Delegate** (Task → docs-scout / reader) |
| Multi-file refactor with cross-file reasoning | **Inline** (Opus owns this) |
| Design decision, architecture, planning | **Inline** (judgment calls) |
| Task that needs 3+ different tool types or chained context | **Inline** (orchestration overhead > delegation cost) |
| Reading one file to gather context (no edit follows) | **Inline** (single Read is free) |

**Heuristic — apply BEFORE picking a tool:** ask *"is this task mechanical, boilerplate, or single-purpose?"* If yes → spawn via Task. If it needs design judgement, cross-file reasoning, or 3+ distinct tools → inline. When in doubt for write/mutate tasks → delegate.

**Anti-pattern:** "the task is too trivial to spawn a subagent for." That phrase is wrong when transparent routing is on. The Task interceptor does the heavy lifting — your job is just to USE `Task` for mechanical work instead of inlining.

## When NOT to Delegate

1. **Parallel/multi-agent mode**: skill invoked with `--parallel` flag or multi-agent pipeline.
2. **Orchestration tasks**: planner, git-manager, brainstormer, project-manager — usually need Opus reasoning; mark them in `excludeAgents` if you want the interceptor to skip them.
3. **MR_SPAWNED=1**: already inside a delegated session (interceptor self-skips, but inline edits should also skip).
4. **User explicitly requested Claude**: user said "use Claude" or "don't delegate".

## Routing floors — decision authority

Three floors sit ABOVE `modelMapping`. They are quality decisions, not cost lines — so where a
floor IS softenable, it is softenable only by an explicit config opt-out that fails **closed** on
any unrecognized value. Only the premium-tier floor is unconditional.

**Premium tiers are never routed.** Any agent whose `model:` frontmatter is `opus`, `claude-opus-4-7`, `claude-opus-4-7[1m]`, `fable`, `claude-fable-5`, or `claude-fable-5[1m]` is passed through to Anthropic **before** `modelMapping` is consulted (`KIT_PASSTHROUGH_MODELS` in `mr-task-interceptor.cjs`). An author writing `model: opus` (or `fable`) is asserting "I need that quality". Adding such a row to `modelMapping` will **not** override this — the passthrough guard wins. Routing them anyway is a code change, intentionally not a config knob. (#84 opus, #216 fable.)

**Write-capable agents are floorable, but do NOT floor by default.** An agent that can mutate the repo passes through when the floor is active, emitting `pass-kit-policy-write-agent`. Three clauses feed it, recorded on the breadcrumb as `clause`: `named-agent` (`KIT_PASSTHROUGH_AGENTS` — writes via Bash), `developer-suffix` (`/-developer$/` — writes via MCP tools), and `declared-tools` (`tools:` declares `Write`/`Edit`/`MultiEdit`/`NotebookEdit`, or is unrestricted). Only the third is a declaration the agent file reveals; the other two exist *because* it does not.

| `modelRouter.writeAgentFloor` | Behavior |
|---|---|
| `"premium-only"` (aliases: `"off"`, `false`) — **shipped default** | No clause floors. `KIT_PASSTHROUGH_MODELS` is then the only passthrough policy, so the net rule is exactly **"premium tiers floor, nothing else does"** |
| `"named-agents"` | Only the two name-based clauses floor; an agent floored **solely** by declaring a write tool becomes routable. **Not** the "sub-premium should route" setting — `t1k-fullstack-developer` stays floored by its name |
| `"all"` | All three clauses floor — the pre-#302 behavior. No longer shipped; select it explicitly to restore the old floor |

A config that omits the key **entirely** (a stripped-down or hand-edited install with no `t1k-config-mr.json`) still resolves in-code to `"all"` — that in-code fallback is unchanged and stays conservative on purpose. It is the *shipped* `t1k-config-mr.json` that now sets `"premium-only"` explicitly, so a fresh consumer's effective default is open, not floored — the same "config carries the effective default, code carries the fail-closed floor" split already used for `defaultBuiltInModel`/`contextGrowthAgents`. Any **unrecognized** value (a typo such as `"premium"`, `true`, `null`, a number) also fails **closed** to `"all"`.

**`"premium-only"` is a tier position, and gates all three clauses on purpose.** None of the three reads `model:`, so under a tier reading all three floor for a non-tier reason; gating only `declared-tools` would leave a sonnet agent floored by the *shape of its name*. The name it does not itself guarantee: the premium floor is `KIT_PASSTHROUGH_MODELS`, upstream and unconditional — if that ever gains a knob, this value's name becomes a lie and must change with it.

Shipping this floor open by default buys provider cost savings on every sub-premium write-capable agent, but spends the judgment such an agent applies to *whether to make the edit at all* — a trade made on the consumer's behalf, not a free win. It is **no longer true** that `spawnCapableFloor` backstops this for the two heaviest writers: `t1k-git-manager` and `t1k-fullstack-developer` both declare `Task(Explore)`, but `spawnCapableFloor` now *also* ships `"off"` by default (below), so out of the box neither floor catches them — `t1k-git-manager`'s commits/pushes/PR-creation run on a third-party provider unless a consumer opts back in (`writeAgentFloor: "all"`/`"named-agents"`, or `spawnCapableFloor: "file-agents"`/`"all"` — either alone re-floors both agents, since both declare `Task(Explore)`).

**Spawn-capable agents are floorable, but do NOT floor by default (#245).** An agent whose `tools:` declare `Agent`, `Task`, or `TeamCreate` can fan out sub-agents, and that is different work from its own task: decomposition, brief quality, coverage, synthesis. A bad brief yields confident, well-executed, wrong work no worker can recover from — when the floor is active it reads `tools:`, **not** `model:`, so it holds even against a stale on-disk agent copy. Emits `pass-kit-policy-spawn-agent`.

| `modelRouter.spawnCapableFloor` | Behavior |
|---|---|
| `"off"` (or boolean `false`) — **shipped default** | Disables the floor entirely |
| `"file-agents"` | Floor agents declaring a spawn tool in an `.md` |
| `"all"` | Additionally floor `general-purpose` and `claude` |

A config that omits the key **entirely** still resolves in-code to `"file-agents"` — that fallback is unchanged; the shipped `t1k-config-mr.json` now sets `"off"` explicitly. Any **unrecognized** value fails **closed** to `"file-agents"` (floors). `Explore` and `Plan` carry no spawn tool and stay routable at every scope.

**`perSpawnModelOverride` does not pierce these floors.** A caller may name a model per spawn (`tool_input.model`, or an `mr-model:` directive in the prompt), but the override is applied *after* the passthrough and write-agent floors — so an `opus`/`fable`-declared agent resolves to `null` and stays on Anthropic, as does a write-capable agent while `writeAgentFloor` still covers its clause. The resolved provider is still subject to the security allowlist below.

## Security — data-class gate + provider allowlist (#158)

Transparent routing re-originates a **separate** upstream connection to a third-party provider, which therefore gets **full plaintext** access to the prompt and code context (OWASP ASI04/ASI07). Two gates are mandatory and both fail toward Anthropic:

- **Data-classification gate.** Before routing, the prompt is classified (`mr-data-classifier.cjs`). If a class listed in `security.dataClassification.blockClasses` is detected — absent/empty means **any** sensitive class — the interceptor does **not** route; the task runs on Anthropic native. Never work around a block by re-wording the prompt.
- **Provider allowlist.** Only providers named in `security.allowedProviders` may be routed to, and the allowlist is enforced at **both** ends: the interceptor allowlists the primary pick, and `mr-delegate.sh` enforces it on **every** failover hop. A chain is only as safe as its weakest hop.

Known classes, patterns, config shape, and the audit breadcrumbs (`pass-data-class-blocked` / `pass-provider-not-allowlisted` in `~/.model-router/debug.jsonl`): `docs/mr-transparent-routing.md`.

## Failover, timeouts and the circuit breaker

The interceptor-selected primary is hop 0 of an ordered pipe; a provider-failure signal advances to the next hop, a transient 429 retries in place, a hard-down provider is skipped by the circuit breaker, and Anthropic is the terminal only when every hop fails. A **non-provider** failure (a real model error) STOPS the pipe rather than burning another hop.

Two values are gate-checked against `scripts/mr-defaults.cjs` by `scripts/mr-validate-timeout-ssot.cjs` — this is their single normative statement, do not mirror them elsewhere:

- `perHopTimeoutSec` — default `300`. Per-attempt budget for one hop. <!-- mr-ssot:perHopTimeoutSec -->
- `contextGrowthPerHopTimeoutSec` — default `900`. Ceiling for agents in `contextGrowthAgents`, whose real payload arrives *after* the spawn; unset ⇒ `max(900, perHopTimeoutSec)`, so raising the global key must never *shorten* it. <!-- mr-ssot:contextGrowthPerHopTimeoutSec -->

**Cost of those defaults:** at the shipped pipe the worst case is 5520s, and `mr-validate-hook-timeout.cjs` currently reports **zero headroom** — any further ceiling raise or a longer pipe must raise the registered `mr-task-interceptor` timeout in `settings.json` in the same change, or the gate fails.

Config blocks, the breaker state machine, env overrides, the outer-budget arithmetic, and the measurement narrative behind each tuning: `docs/mr-transparent-routing.md`.

## Guard coverage — routed spawns fire no SubagentStop (#784)

A routed delegation produces **no `SubagentStop` event**: the interceptor delivers its result by DENYING the original Task, so no native sub-agent is ever spawned and there is no lifecycle to stop. Every `SubagentStop`-only guard is therefore blind to routed agents — `workflow-failure-detector.cjs` (P1/P6) and `subagent-uncommitted-guard.cjs` (#508/#613) do **not** cover them; `lesson-collector.cjs` does, only because it is also registered on `Stop`.

Because `modelMapping` routes the sonnet/haiku tiers and `defaultBuiltInModel` routes the built-ins, those guards effectively cover **opus agents only** — i.e. *not* the agents most likely to be doing mechanical edit work. **Do not rely on them to catch an uncommitted or empty-handed routed agent; check its work yourself.** `mr-delegate.sh` appends what facts it has to `~/.model-router/routed-stops.jsonl` (zero-work signals, dirty-tree backstop); why we do not synthesise a SubagentStop, and the wiring-up path: `docs/mr-transparent-routing.md`.

## Routed hop environment — no team roster, no MCP, no fan-out

A routed hop is a standalone `claude -p` subprocess: `--mcp-config
'{"mcpServers":{}}'` strips every MCP server, and it sits outside any team
roster, so `SendMessage` has no peer to address even where nominally present.
`Agent` is disallowed outright; `Task`/`TeamCreate` are absent from the
allowlist and stall on a headless approval prompt — no fan-out. Write tools
follow the agent's own surface: read-only built-ins (`Explore`, `Plan`)
default to `plan` (no `Edit`/`Write`); every other agent defaults to
`acceptEdits` (`Write` enabled) unless frontmatter overrides it (#132) —
routed hops are NOT uniformly plan-mode.

**Brief accordingly:** never make `SendMessage` or a file write the ONLY
delivery channel — put the full deliverable in the final message; the
interceptor already returns that text as the Task's result (below).

## Delegation Output

The Task interceptor returns the cheap model's text output via `systemMessage`. The parent session sees it as the Task's result.

If `mr-delegate.sh` exits non-zero (timeout, provider down), the interceptor surfaces what it has + the exit code. Don't let the Task fall through to Anthropic on error — that would burn Opus tokens AND the cheap call's tokens. If the delegation failed, decide whether to retry or inline.
## Full reference

`docs/mr-transparent-routing.md` — interceptor algorithm, `modelMapping` / `defaultBuiltInModel` / `contextGrowthAgents` / `perSpawnModelOverride` schemas and worked examples, the `failover.pipe` / `inHopRetry` / `circuitBreaker` config blocks and state machine, per-hop budget arithmetic, the security pattern catalogue, and the incident archaeology (#211 inherited MCP schemas, #229, #236, #244, #249, #261, #784).
