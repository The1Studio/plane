---
name: t1k:coding-level
description: "Set coding experience level for tailored output. Use for adjusting explanation depth, code complexity, and response format to user expertise."
keywords: [experience, level, explanation, format, eli5, junior, senior, god]
argument-hint: "[0-5]"
effort: low
tools: [Read, Edit, Write, AskUserQuestion]
version: 2.86.0
origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---

# TheOneKit Coding Level

Set your coding experience level so explanations match your background. T1K skills read your level from `.claude/t1k-config-base.json` and adapt output depth, jargon, and code-block size automatically.

## Usage

```
/t1k:coding-level [0-5]
```

If no argument provided, the skill uses AskUserQuestion to ask you. After loading the schema via `ToolSearch(query="select:AskUserQuestion")` if needed.

## Levels

| Level | Name      | For                 | Behavior |
|-------|-----------|---------------------|----------|
| 0     | ELI5      | Zero coding experience | Analogies, no jargon, 5-10 line code blocks |
| 1     | Junior    | 0-2 years           | Concepts explained, WHY not just HOW |
| 2     | Mid-Level | 3-5 years           | Design patterns, system thinking |
| 3     | Senior    | 5-8 years           | Trade-offs, business context, architecture |
| 4     | Tech Lead | 8-10 years          | Risk assessment, business impact, strategy |
| 5     | God Mode  | 15+ years           | Maximum efficiency, no hand-holding (fallback when `codingLevel` is set to an invalid value) |

> **Default behavior:** when `codingLevel` is NOT set in `.claude/t1k-config-base.json`, NO coding-level output-style loads — Claude uses its default behavior. "God Mode" is the **fallback** when an invalid value is supplied (e.g. `codingLevel: 99`), NOT the implicit default for unconfigured projects.

## How it works

1. User invokes `/t1k:coding-level <0-5>` (or skill asks via AskUserQuestion).
2. Skill writes `{"codingLevel": <N>}` to `.claude/t1k-config-base.json` (creates file if absent, merges if present).
3. Skill activates the corresponding output-style file in `.claude/output-styles/t1k-coding-level-<N>-*.md`.
4. Subsequent sessions auto-load the style.

## Manual output-style activation

Users can also pick a style directly via Claude Code's `/output-style` command:
- `/output-style t1k-coding-level-0-eli5`
- `/output-style t1k-coding-level-1-junior`
- `/output-style t1k-coding-level-2-mid`
- `/output-style t1k-coding-level-3-senior`
- `/output-style t1k-coding-level-4-lead`
- `/output-style t1k-coding-level-5-god`

## Tool guard — AskUserQuestion is deferred

If level is missing/unclear and the tool isn't loaded, first run:
```
ToolSearch(query="select:AskUserQuestion", max_results=1)
```
then invoke the tool with 6 options (one per level). Never prose-list options.

## Config schema

`.claude/t1k-config-base.json`:
```json
{
  "codingLevel": 5
}
```

Valid values: integers 0-5. **When `codingLevel` is unset, no coding-level style loads — Claude uses its default behavior** (NOT God Mode). God Mode (5) is only the fallback for an *invalid* value (e.g. `codingLevel: 99`).

## Sub-Agent Fork Hygiene

**Sub-agent forking:** see `skills/t1k-architecture/references/fork-hygiene.md`.
