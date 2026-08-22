---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# Example: Iconified `_Sidebar.md`

A working iconified sidebar from `The1Studio/StickmanForge_IdleRPG.wiki`. Use this as a copy-paste-then-edit starter when applying the icon convention to a new wiki. See `icon-convention.md` for the canonical icon set + rules.

## Why this layout works

1. Every section header leads with a single domain emoji — scannable in <1s
2. Subsections under "Overview" and "Technical" use their own domain icons (📚 Index, 🎯 Design Pillars, 📖 Glossary, 🌳 Tech Tree, ⚙️ Content Pipeline, 📦 Library Mapping) — chosen from the canonical set
3. Section ordering follows reader-progression (Overview → Mechanics → Progression → Presentation → Tech → Roadmap), NOT alphabetical
4. One link per section by default — the section header carries the navigational weight; extra bullets go under it ONLY when they reference specific anchors inside the page

## The sidebar

```markdown
## 🎮 StickMan Forge: IdleRPG

### 🏠 Overview
- [Home](Home)
- [🎯 Design Pillars](Home#design-pillars)
- [📚 Index](StickManForge-Index)
- [📖 Glossary — Engine Terms](Home#glossary--unity--engine-terms)

### ⚔️ Combat
- [Combat System](StickManForge-Combat)

### 🛡️ Items
- [Equipment](StickManForge-Equipment)

### 🔨 Forge
- [Forge System](StickManForge-Forge-System)

### 💰 Economy
- [Economy](StickManForge-Economy)

### 🦸 Heroes
- [Heroes / Pets / Mounts](StickManForge-Heroes-Pets-Mounts)

### 🗺️ Progression
- [Realm Progression](StickManForge-Realm-Progression)

### 🎨 UI-UX
- [UI / UX](StickManForge-UI-UX)

### 🖌️ Art
- [Art Brief](StickManForge-Art-Brief)

### 👥 Social
- [Social](StickManForge-Social)

### 🔧 Technical
- [Technical](StickManForge-Technical)
- [🌳 Tech Tree](StickManForge-TechTree)
- [⚙️ Content Pipeline](StickManForge-Content-Pipeline)
- [📦 Library Mapping](StickManForge-Library-Mapping)

### 🚀 Roadmap
- [Tier 2 Preview](StickManForge-Tier2-Preview)
```

## How to adapt it

1. Replace `StickMan Forge: IdleRPG` with your project name (keep `🎮` or pick your hub icon from the canonical set)
2. Rename section headers to match your domains; keep one emoji per header
3. Reorder by reader-progression for your project — for a tutorial-heavy wiki, start with "Tutorials"; for a reference wiki, start with "Concepts"; for a game wiki, start with "Overview" + mechanics
4. Drop sections you don't have; add sections you do (but cap at ~12 — beyond that, sidebar nav becomes a wall of text)
