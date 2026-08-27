# Phase 2 — Versioned-key cache layer

**Goal:** a self-contained fork app providing versioned-key caching with zero staleness, exposing
exactly the three functions Phase 3 consumes.

**Depends on:** nothing. Runs in parallel with Phases 1 and 4.

**Owns:** `apps/api/plane/workload_cache/` (new, exclusive), plus the two registration lines in
`settings/common.py` `INSTALLED_APPS` (touch-point 1) — no other core file.

**Contract:** [`references/cache-contract.md`](references/cache-contract.md) is the SSOT for the key
format, reclamation semantics, connection, and public interface. **Read it before writing any code; do not re-derive
any of it here.** Phase 3 codes against that file, not against this one.

---

## Why a new app rather than extending `plane/utils/cache.py`

`plane/utils/cache.py` is a core file. Editing it is a rebase conflict on every upstream bump and
falls outside the 7 sanctioned touch-points (`docs/FORK.md`). A fork-owned Django app is the
established pattern here — `workload/`, `views_ext/`, `cascade_ext/` all follow it.

The new app is **model-less**: no `models.py`, no `migrations/`, no `urls.py`, no touch-point 2
entry. It is a library plus a signal registration, exactly like `issue_defaults_ext/`.

## Prior art check

Recorded so this is a due-diligence result rather than an assumption. Scope: `apps/api/plane/` in
full, excluding `__pycache__`.

- `grep -rn "cache_response\|invalidate_cache" plane/` — 5 decorated endpoints, all core, all using
  path-keyed caching with no versioning. No version counter exists anywhere.
- `grep -rn "cache" plane/workload/ plane/views_ext/` — **zero matches**. Both fork apps are
  uncached.
- `find plane -name "*cache*.py"` — `plane/utils/cache.py` and
  `plane/db/management/commands/clear_cache.py` only.

No existing helper does versioned invalidation, so this is genuinely new rather than a duplicate.
`generate_cache_key` in `plane/utils/cache.py` is deliberately **not** reused: it keys on raw path
plus auth header with no version segment, which is the shape being replaced.

## Structure

```
plane/workload_cache/
  __init__.py
  apps.py          # AppConfig; ready() imports signals
  client.py        # db1 connection builder, fail-open wrapper
  keys.py          # key + params_hash construction (contract § Key format)
  cache.py         # get_cached / set_cached / bump_workspace
  signals.py       # post_save/post_delete -> bump_workspace
  tests/
    test_keys.py
    test_cache.py
    test_signals.py
```

## Steps

1. `client.py` — build the db1 client from `REDIS_URL`. Handle a URL with and without a trailing
   db index. Honour `rediss://` per contract, and mark that path unverified in a comment rather
   than claiming it works.

2. `keys.py` — implement the key format and `params_hash` exactly as the contract specifies:
   sorted `(key, value)` pairs, allow-list of response-affecting params only, unrecognized params
   excluded rather than hashed.

3. `cache.py` — the three public functions. Fail-open on reads and writes; **fail-loud on
   `bump_workspace`** per the contract's failure posture. Nothing else is exported.

4. `signals.py` — `post_save` and `post_delete` receivers calling `bump_workspace(slug)`. Model
   coverage is fixed in Phase 3 (it owns the write-path analysis); this phase provides the
   registration mechanism and one worked receiver.

5. `apps.py` — `ready()` imports `signals`. Register in `INSTALLED_APPS` (touch-point 1).

## Tests

Unit tests, no live Redis required beyond the containerized instance already running:

- **Key stability** — same params in a different dict order produce the same key; a changed
  `granularity` produces a different one; an unrecognized param produces the _same_ key.
- **User isolation** — two user ids never collide.
- **Version behaviour** — a bump makes the previous key unreachable; a missing counter reads as 0
  and is not written on read; `INCR` is used, not read-modify-write.
- **Fail-open** — with the client patched to raise, `get_cached` returns `None` and `set_cached` is
  a no-op, neither propagating.
- **Fail-loud** — with the client patched to raise, `bump_workspace` raises. This is the one place
  where swallowing the error would silently reintroduce staleness, so it is asserted explicitly
  rather than left to the fail-open rule.
- **No expiry is set** (D6) — assert `set_cached` issues `SET` **without** `ex`/`px` and that the
  written key's `TTL` is `-1`. Worth a test precisely because adding a TTL is the reflexive thing
  to do when reviewing cache code, and here it would be wrong: `allkeys-lru` is the only
  reclamation path, and a stray expiry would silently make entries evictable on a different
  schedule than the design assumes.

## Success criteria

- All tests pass: `pytest plane/workload_cache/tests/ -v`.
- `python manage.py makemigrations --check --dry-run` reports **no** new migrations (the app is
  model-less; a migration appearing means a model was added by mistake).
- `python manage.py check` clean.
- The three public functions are importable and nothing else is exported —
  `from plane.workload_cache.cache import get_cached, set_cached, bump_workspace`.

## Out of scope

Wiring any endpoint (Phase 3), deciding which models bump (Phase 3), any change to
`plane/utils/cache.py` or core's db0 caching (explicitly out per D1/D5).
