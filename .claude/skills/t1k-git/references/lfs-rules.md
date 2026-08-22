---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# t1k-git — Git LFS Rules (Detail)

The decision table in `SKILL.md` § "Step 2.7: Large-File / LFS Check" covers the operative
STOP/suggest actions. This file backs those with the full rationale.

1. **`.gitattributes` before (or with) the binary — never after.** The filter applies at `git
   add` time; a binary staged before its pattern lands is a raw blob, and re-tracking later does
   NOT fix it.
2. **Retrofitting requires a history rewrite.** `git lfs track` on an already-committed file
   leaves the old blob in history. The fix is `git lfs migrate import --include="*.ext"
   --everything` — a rewrite with force-push implications; coordinate like any rebase of shared
   history (see SKILL.md § "Force-Push Safeguard").
3. **Track by asset class, deliberately.** Binary media (textures, models, audio, video,
   archives, ML weights) → LFS. Small text/config → never; LFS'd text loses diffs/blame and burns
   quota (GitHub free tier: 1GB storage / 1GB-month bandwidth; large fleets exhaust it fast).
4. **Clones without `git lfs install` get pointer files, not content** — builds then fail on
   130-byte "models" with confusing errors. CI runners and every teammate machine need LFS
   installed (`actions/checkout` needs `lfs: true`).
5. **Verify, don't assume:** `git lfs status` before commit, `git lfs ls-files` after. A
   `.gitattributes` pattern that misses a path fails **silently** — the blob commits raw and
   nothing warns.
