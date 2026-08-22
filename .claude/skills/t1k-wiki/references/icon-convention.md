---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# Icon Convention for Wiki Sidebar + Document Beautification

**MANDATORY** for every wiki the `t1k-wiki` skill manages.

## Rule

Lead with a domain emoji on:

1. **Every `_Sidebar.md` section header** (`### ⚔️ Combat`, `### 🔨 Forge`).
2. **Every Home / Index / hub-page H1** (`# 🏠 StickMan Forge Home`).
3. **Top-of-page H2 callouts** that recur across pages — `## 🎯 Design Pillars`, `## 🗺️ Roadmap`, `## 📊 Status`, `## 📚 Source Attribution`, `## 🔗 Related Pages`.
4. **Sidebar sub-bullets** that lead to a known concept anchor (`- [🎯 Design Pillars](Home#design-pillars)`).

Page H2 body sections do NOT need icons unless they're one of the recurring named callouts above. Avoid emoji-soup — one icon per heading max.

## Why it's load-bearing

| Audience | Without icons | With icons |
|---|---|---|
| Human reader scanning sidebar | Reads every section header word-by-word | Scans icon column in <1 second; jumps to the right section |
| Human reader skimming a long page | Eyes glaze at uniform `## Heading` blocks | Eyes catch `## 🗺️ Roadmap` immediately; faster nav |
| RAG retrieval | H2 text is the only semantic signal | Emoji adds an orthogonal signal (`🔨` → "forge concept", `💰` → "economy concept") which improves keyword + embedding overlap |
| Mobile reader (narrow sidebar) | Section headers wrap awkwardly | Icon is always visible even when text truncates |

## Canonical icon set (extend per-project as needed)

### Mechanics & Systems

| Emoji | Concept |
|---|---|
| ⚔️ | Combat / battle systems |
| 🛡️ | Items / equipment / armor |
| 🔨 | Forge / crafting / upgrades |
| 🌳 | Tech tree / skill tree |
| 💎 | Resources / currencies / gems |
| 💰 | Economy / shop / monetization |

### Progression & Pacing

| Emoji | Concept |
|---|---|
| 🗺️ | Progression / map / realms |
| 🚀 | Roadmap / future / Tier-2+ |
| 🎯 | Goals / pillars / design intent |
| 📊 | Balance / data / metrics |
| ⏱️ | Pacing / timing / session length |

### Characters & Social

| Emoji | Concept |
|---|---|
| 🦸 | Heroes / playable characters |
| 🐾 | Pets / companions |
| 🐴 | Mounts |
| 👥 | Social / clans / guilds |
| 🎭 | Narrative / story / lore |

### Presentation

| Emoji | Concept |
|---|---|
| 🎨 | Art / visual design / palette |
| 🖌️ | Art brief / style guide |
| 🎮 | UI / UX / controls |
| ✨ | VFX / juice / feel |
| 🎬 | Cinematics / cutscenes |

### Tech & Pipeline

| Emoji | Concept |
|---|---|
| 🔧 | Technical / engineering |
| ⚙️ | Pipeline / build / CI |
| 📦 | Library / packages / dependencies |
| 🧪 | Testing / QA |
| 🐛 | Bug / known issue |

### Meta / Navigation

| Emoji | Concept |
|---|---|
| 🏠 | Home / landing |
| 📚 | Index / library / glossary |
| 📖 | Glossary / reference |
| 🔗 | Related / cross-links |
| 📝 | Notes / changelog |

### Callouts (when not using GitHub-native `[!NOTE]`)

| Emoji | Concept |
|---|---|
| ⚠️ | Warning / caveat (prefer `[!WARNING]` GitHub-native) |
| ✅ | Done / shipped (prefer `[!TIP]` GitHub-native) |
| 🚧 | Work-in-progress / deferred |
| 🛑 | Blocked / stop |

## Consistency rule

Pick ONE emoji per concept and apply it everywhere that concept appears:

- Sidebar header for that section
- Page H1 (if it's a domain hub)
- Cross-references from other pages
- Sub-bullets that link to anchor sections inside that domain

Example: if Combat is `⚔️`, then:
- Sidebar: `### ⚔️ Combat` (header) + `- [Combat System](StickManForge-Combat)` (link — no icon needed on the page name itself, the section header carries it)
- Page H1: `# ⚔️ Combat System` (optional but recommended for the page itself)
- Cross-page link: `See [⚔️ Combat — Boss Mechanics](StickManForge-Combat#boss-mechanics)` (icon on the linked concept)

## Anti-patterns

- **Emoji-soup** — `### ⚔️🛡️💀 Combat & Items & Death` (one icon per heading; if you have 3 concepts, you have 3 headings)
- **Inconsistent icon per concept** — Combat is `⚔️` in sidebar but `🗡️` in Home H1. Pick one, apply everywhere.
- **Emoji for body prose** — icons belong in headings + callouts, not in regular sentences ("the forge 🔨 produces items 🛡️" — no)
- **Skin-tone modifiers** — keep neutral (`🦸` not `🦸🏻`)
- **Decoration without meaning** — every icon should carry a domain meaning; `### ✨ Combat` is decoration (✨ ≠ combat) and bad

## Validator integration (future work)

A future `validate-icon-convention.cjs` could enforce:

- `_Sidebar.md` headers all start with an emoji
- A `wikiIcons:` frontmatter map (`{ Combat: "⚔️", Forge: "🔨" }`) declares the canonical set per project
- Emoji-soup detection (`/^### (\p{Emoji}\s*){2,}/`)
- Inconsistent-icon-per-concept detection (Combat sidebar uses `⚔️` but Combat page H1 uses `🗡️` — flag)

Not implemented yet — file a tracking issue when the rule needs teeth.

## Where this rule lives

Authoritative copy: this file. The `beautify-headings.cjs` and `sync-sidebar.cjs` scripts SHOULD consult this when generating headers — currently they don't (TODO).

Cross-references:
- `SKILL.md` → "Dual-audience principle" §"Icons for scannability"
- `references/wiki-conventions.md` (if it covers headers)
- `references/anti-patterns.md` (icon-soup, decoration-icons)
