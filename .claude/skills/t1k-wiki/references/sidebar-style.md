---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# Sidebar Style — Collapsible + Status-Aware Convention

The canonical `_Sidebar.md` style for every TheOneKit-managed GitHub Wiki. Supersedes the flat `### Heading` + bullet style. Adopted as SSOT 2026-05-27 after the StickManForge sidebar restyle worked-example session.

## When this style applies

| Trigger | Behavior |
|---|---|
| New wiki initialized via `t1k:wiki init` | Scaffold sidebar in this style by default |
| Existing wiki with ≥10 pages | Migrate next time `t1k:wiki fix` runs (regenerates from page discovery) |
| Sidebar gains a new section | Add as `<details open>` block per element rules below |
| Wiki has <5 pages | Flat style acceptable; collapsibles add noise without payoff |

## Element anatomy

Ten elements compose the style. Reference these by number when reviewing or composing a sidebar.

| # | Element | Pattern |
|---|---|---|
| 1 | **Home anchor** | `🏠 **[Home](Home)**` — bold link at top, NOT an `#` heading |
| 2 | **Section delimiter** | `---` horizontal rule between every top-level section AND before footer |
| 3 | **Collapsible section** | `<details open>...<summary>EMOJI <b>Name · count</b></summary>...</details>` |
| 4 | **Count suffix** | Middle-dot separator: `Core Mechanics · 3`. Count = items inside this section (exclude nested sub-section counts) |
| 5 | **Nested sub-categories** | Inner `<details>` with `&nbsp;&nbsp;` (2 nbsps) indent in summary, `&nbsp;&nbsp;&nbsp;` (3 nbsps) before list items inside |
| 6 | **List item** | `- 📄 [Display](URL-encoded-href) PRIORITY STATUS` |
| 7 | **Status icon** (suffix) | 🟢 ready · ⏳ in-progress · 🚫 blocked/deprecated · ✅ done |
| 8 | **Priority label** (mid) | `P0` `P1` `P2` `P3` — between link and status icon |
| 9 | **Item prefix** | `📄` page · `📋` template · `~~Strikethrough~~` deprecated. ONE prefix per item |
| 10 | **Footer** | `> 🔗 [link]` blockquote — external/related resource at very bottom |

## Two structural patterns

Pick ONE per top-level section. Do not mix within a single `<details>` block.

### Pattern A — Flat list (default, 2-8 items)

```markdown
<details open>
<summary>⚔️ <b>Core Mechanics · 3</b></summary>

- 📄 [Combat System](StickManForge-Combat) P0 ✅
- 📄 [Equipment](StickManForge-Equipment) P0 ✅
- 📄 [Forge System](StickManForge-Forge-System) P0 ✅

</details>
```

### Pattern B — Bucketed tree (9+ items, distinct sub-domains)

```markdown
<details open>
<summary>🔧 <b>Service Domains · 26</b></summary>

<details open>
<summary>&nbsp;&nbsp;💰 <b>Financial · 5</b></summary>

- &nbsp;&nbsp;&nbsp;📄 [Wallet](Service-Spec-Wallet) P3 🟢
- &nbsp;&nbsp;&nbsp;📄 [Ledger](Service-Spec-Ledger) P3 🟢

</details>

<details>
<summary>&nbsp;&nbsp;💬 <b>Social · 3</b></summary>

- &nbsp;&nbsp;&nbsp;📄 [Chat](Service-Spec-Chat) P2 🟢

</details>

</details>
```

Indent rules:
- `&nbsp;&nbsp;` (2 nbsps) before sub-category emoji in the inner `<summary>`
- `&nbsp;&nbsp;&nbsp;` (3 nbsps) before list-item emoji inside the inner `<details>`
- Blank line above + below every `<details>` block (renders cleanly across themes)

## Status & priority vocabulary

| Field | Allowed values | Meaning |
|---|---|---|
| Priority | `P0` | Critical / launch-blocking / canon |
| Priority | `P1` | Important / next-tier polish |
| Priority | `P2` | Nice-to-have / supporting reference |
| Priority | `P3` | Future / experimental / backlog |
| Status | `✅` | Done, production-ready, shipped |
| Status | `🟢` | Ready for use (similar to ✅; use for "specced and approved, awaiting impl") |
| Status | `⏳` | In progress, stub, illustrative, pending balance pass |
| Status | `🚫` | Deprecated, blocked, do-not-use |

Order: `[name] PRIORITY STATUS`. Both labels OPTIONAL — omit if the wiki has no priority framework or no ship-state tracking. Don't invent priorities to fill the slot; absence is fine.

## URL encoding rules

Special characters in wiki page filenames MUST be percent-encoded in links. GitHub renders the filename verbatim, but anchor parsers reject many raw characters.

| Character | Percent-encoded | Use case |
|---|---|---|
| Space | `%20` | When a wiki uses spaces (rare — prefer hyphens) |
| `[` | `%5B` | Service spec brackets: `[Service Spec] Wallet` → `%5BService-Spec%5D-Wallet` |
| `]` | `%5D` | Same |
| `‐` (en-dash) | `%E2%80%90` | `Page ‐ Subtitle` → `Page-%E2%80%90-Subtitle` |
| `&` | `%26` | `R&D` → `R%26D` |
| `(` `)` | `%28` `%29` | Rarely needed; GitHub usually tolerates |

Hyphen-only ASCII page names (the recommended default per `wiki-conventions.md` § Filename rules) need NO encoding — `[Combat](Combat-System)` is fine.

## Default-state heuristic

When should a `<details>` start `open` vs collapsed?

| Section type | Default state |
|---|---|
| Top-level primary domain (Core Mechanics, Progression) | `open` |
| Overview / Index | `open` |
| Sub-categories WITHIN a top-level bucket — 1-2 items | `open` |
| Sub-categories WITHIN a top-level bucket — 3+ items, lower priority | (closed) |
| Roadmap / Future / Backlog | (closed) |
| Deprecated / Archive | (closed) |

The principle: the first viewport should reveal the wiki's primary navigation surface; lower-priority sub-buckets reduce noise by collapsing.

## AskUserQuestion decision-flow pattern

When proposing a sidebar style (new wiki OR restyling an existing one), surface tradeoffs using `AskUserQuestion` with the `preview` field. Concrete sidebar snippets in the preview let the user compare at a glance instead of imagining from prose.

```
AskUserQuestion({
  questions: [{
    question: "How much of the style should I apply?",
    header: "Apply depth",
    multiSelect: false,
    options: [
      {
        label: "Full template (collapsibles + counts + status)",
        description: "Adopt every element ...",
        preview: "🏠 **[Home](Home)**\n\n---\n\n<details open>\n<summary>⚔️ <b>Core Mechanics · 3</b></summary>\n\n- 📄 [Combat](Combat) P0 ✅\n..."
      },
      {
        label: "Lite (collapsibles + counts, no status)",
        description: "...",
        preview: "🏠 **[Home](Home)**\n\n---\n\n<details open>\n<summary>⚔️ <b>Core Mechanics · 3</b></summary>\n\n- 📄 [Combat](Combat)\n..."
      }
    ]
  }]
})
```

Decision dimensions to surface (one question each, batched in one call):

1. **Apply depth** — full template, lite, status-only
2. **Grouping shape** — flat groups (current per-domain sections), bucketed tree (super-categories), hybrid
3. **Skill-scope update** — copy local + edit, edit global only, both + sync-back (per `prefer-local-over-global-edits.md`)

Each option's `preview` MUST be a working sidebar snippet (3-10 lines), not prose. Prose answers can be re-interpreted; concrete snippets cannot.

## Worked example — StickManForge wiki (2026-05-27)

The StickManForge wiki migrated from 12 flat sections to 6 bucketed `<details open>` sections (17 pages total):

```markdown
🏠 **[Home](Home)**

---

<details open>
<summary>📚 <b>Overview · 1</b></summary>

- 📄 [Index — Page Inventory & Cross-Doc Synthesis](StickManForge-Index) P0 ✅

</details>

---

<details open>
<summary>⚔️ <b>Core Mechanics · 3</b></summary>

- 📄 [Combat System](StickManForge-Combat) P0 ✅
- 📄 [Equipment](StickManForge-Equipment) P0 ✅
- 📄 [Forge System](StickManForge-Forge-System) P0 ✅

</details>

---

<details>
<summary>🚀 <b>Roadmap · 1</b></summary>

- 📄 [Tier 2 Preview](StickManForge-Tier2-Preview) P2 ⏳

</details>

---

> 🔗 [Source GDD](https://github.com/The1Studio/StickmanForge_IdleRPG) — Game Design Document & screenshots
```

Pattern notes from this case:
- Roadmap section is closed (`<details>`, not `open`) — secondary content
- Tech Tree marked `⏳` because its skill-tier numerics are illustrative placeholders pending Tier-1 balance pass (per the page's IMPORTANT callout)
- Library Mapping marked `⏳` because the kit module/skill mapping is still being unified
- All other pages `✅` per R5 production-ready milestone

## Anti-patterns

| Anti-pattern | Why it's wrong | Fix |
|---|---|---|
| `### ⚔️ Combat` flat headings | Old style — no collapse, no count, scales poorly past 8 sections | Wrap in `<details open><summary>...</summary>` |
| `<details>` without blank lines around | Some GitHub renderers swallow adjacent content | Always blank line above + below |
| Missing emoji in summary | Visual anchor lost — humans scan icons before text | Pick one canonical emoji per domain (see `icon-convention.md`) |
| Three+ emojis per item | Emoji-soup — overwhelms scanning | Max one prefix emoji + max one status emoji per item |
| `[Wallet](Service-Spec-Wallet)` with literal brackets in filename without encoding | Anchor parsers reject `[`/`]` | Encode: `(%5BService-Spec%5D-Wallet)` |
| Count drifts from actual items | Sidebar appears stale; readers lose trust | Regenerate counts via `fix` after any add/remove |
| Mixing flat + bucketed within one `<details>` | Inconsistent indent baseline confuses readers | Pick A or B per top-level section |
| Hand-editing without running `validate` after | Breaks anchor sync, may add phantom links | Always `validate` post-edit |
| Footer link without `> 🔗` blockquote prefix | Footer blends into last section visually | Use blockquote — it visually separates without an extra `---` |
| `<details>` ALL open by default | Defeats the collapse affordance — same noise as flat | Close at least the Roadmap/Backlog/Archive sections |

## Migration from flat style

When migrating an existing `### Heading` + bullet sidebar to this style:

1. **Group existing single-page sections** — bucket related sections into super-categories (e.g., Combat + Equipment + Forge → "Core Mechanics"). Aim for 4-8 super-categories total.
2. **Compute counts** — exact page count per bucket; verify by re-counting after each iteration.
3. **Assign status icons** — read each page's frontmatter `status:` / `wikiStatus:` field. Default to `✅` if the page is production-ready and no frontmatter declares otherwise.
4. **Assign priorities** — if the wiki has no existing priority framework, omit P0/P1/P2 labels entirely. Don't invent.
5. **Test rendering** — push to a branch, view the wiki's sidebar in browser; verify `<details>` blocks render correctly on both light AND dark theme.
6. **Update `sync-sidebar.cjs` config** if the wiki uses auto-regen — the script needs to emit the new format (TODO if not done).

## Validator hooks (future work)

`validate-sidebar.cjs` checks (to be added):

- Sidebar contains `🏠 **[Home](Home)**` as line 1
- Every `<details>` block has matching `</details>` close tag
- Every `<summary>` contains an emoji + bold text + count
- Every page on disk appears in exactly one `<details>` block
- Count suffixes (`· N`) match actual item count inside the block
- No phantom links (sidebar references a page that doesn't exist on disk)
- Footer is present and uses `> 🔗` blockquote form

Until the validator ships, `t1k:wiki validate` will continue to use the legacy flat-style sidebar checks — manual review required for the new style.

## References

- `wiki-conventions.md` § Sidebar structure — short version with backref here
- `icon-convention.md` — canonical emoji palette per domain
- `github-wiki-gotchas.md` — sidebar drift, anchor behavior, default branch
- Source case study: StickManForge_IdleRPG wiki commit (2026-05-27)
