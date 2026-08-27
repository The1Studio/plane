# Cache contract — pinned shared shape

**This file is the SSOT for everything Phase 2 declares and Phase 3 consumes.** Neither phase
invents any of it. Per `rules/contract-first-integration.md`, it is fixed before either side is
written, and it is linked — never copied — into the phase briefs.

## Connection

- Client is built inside the fork app from the `REDIS_URL` environment variable, **db index 1**.
- No `CACHES` alias is added and `apps/api/plane/settings/common.py` is **not** edited. Core keeps
  db0; core's `KEYS *` sweeps therefore never traverse fork keys (`plan.md` § D5).
- `REDIS_URL` in this deployment is `redis://plane-redis:6379/` — no db index present, so the
  fork appends `1`. The builder must handle both a present and an absent trailing index rather
  than assuming this exact string.
- SSL: honour `rediss://` the same way `common.py:238` does. Staging and production are both plain
  `redis://` today, so this path is untested here — treat it as unverified, not as working.

## Key format

```
wlc:v{version}:{surface}:{workspace_slug}:{user_id}:{params_hash}
```

| Segment          | Meaning                                                                    |
| ---------------- | -------------------------------------------------------------------------- |
| `wlc`            | fixed namespace prefix, so a fork key is identifiable in any keyspace dump |
| `version`        | integer read from the workspace version counter (below)                    |
| `surface`        | `workload` or `viewsext` — never free-form                                 |
| `workspace_slug` | the `slug` path param                                                      |
| `user_id`        | `request.user.id`; permission-scoped results must never cross users        |
| `params_hash`    | stable hash of the normalized query params that affect the response        |

`params_hash` is over a **sorted** `(key, value)` list of only the params that change the response
— for workload: `granularity`, `date_from`, `date_to`, `project_ids`, `assignee_ids`,
`state_groups`. Unrecognized params are excluded, not hashed, so a tracking param cannot fragment
the cache.

## Version token

```
wlc:ver:{workspace_slug}   ->  random hex token (uuid4)
```

- Read with `GET`. **Absent means "do not serve"** — never a default version.
- Bumped with a plain `SET` of a fresh token. O(1), no key scanning, no ordering.
- Carries no expiry, like every other key.

**A random token, not an incrementing counter — amended 2026-08-27.** The
original design used `INCR`. That is the obvious choice and it has a failure mode
that only appears once the key can be evicted, which it can: filling staging's
db1 to its 1 GB bound evicted 112,784 keys including _every_ `wlc:ver:*`. A
counter then has to restart from something, and anything it restarts from can
re-enter a range that entries surviving the same sweep were written under —
making superseded data reachable again.

Seeding the restart from the server clock narrows the window and does not close
it: a burst of bumps outruns the clock.
`test_recreated_version_cannot_re_reach_surviving_entries` failed on exactly
that, with a reseed of `1800000000` against versions already at `1800000002`.

A random token closes it outright — a new token cannot collide with any token
ever used, so old entries stay unreachable regardless of what survived, what the
clock reads, or how fast writes arrive. It also removes ordering entirely:
nothing compares two versions, so there is no monotonicity to preserve.

## Invalidation semantics

A bump makes every prior key for that workspace unreachable **immediately**, including the writing
user's own. This is what delivers zero staleness; a TTL cannot (`plan.md` § write rate).

## Reclamation — no TTL

Entries are written with **no expiry**. `allkeys-lru` on the instance is the sole reclamation
mechanism (D6).

A superseded entry — one whose workspace version has since been bumped — is unreachable the instant
it is superseded, but it keeps occupying memory until LRU evicts it. Nothing else removes it.

Three consequences to hold, none of them blocking but none of them obvious:

1. **db1 will grow to `maxmemory` and stay there.** That is the steady state, not a leak. `INFO
memory` sitting at ~1 G is therefore expected and is **not** a signal of anything — do not treat
   a full instance as an incident, and do not alert on it.
2. **`evicted_keys` will climb continuously** once warm. It is the mechanism working, not a fault.
   The metric that matters is the _hit rate_, not the eviction count.
3. **`maxmemory` is instance-wide, so core's db0 keys compete for eviction permanently**, not
   occasionally. Core holds 3 keys read on essentially every page load, so LRU should always rank
   them hot — but "should" is the reason Phase 5 verifies it under a real fill rather than assuming
   it. This is the one place where dropping the TTL raises a risk rather than simplifying.

Because nothing expires, `DBSIZE` on db1 is unbounded-by-count and only bounded by memory. A
keyspace dump is correspondingly large; prefer `SCAN` with a `MATCH` when inspecting, never `KEYS`.

## Public interface Phase 3 may call

```python
get_cached_bytes(surface, slug, user_id, params) -> bytes | None
render_json(data)                                -> bytes
set_cached(surface, slug, user_id, params, val)  -> None   # val: bytes or dict
bump_workspace(slug)                             -> None
```

Nothing else is public. Phase 3 must not construct a key, touch the client, or read the counter
directly.

**Entries are pre-rendered JSON bytes, not dicts** — amended 2026-08-27 after measurement. Storing
a dict meant every hit `json.loads`-ed 478 KB that DRF then immediately re-encoded: 6.09 ms to
decode plus ~5 ms to re-encode, ~11 ms of round-tripping to turn JSON into JSON. The endpoint now
renders once with `render_json`, caches those exact bytes, and returns them via `HttpResponse` on
both paths. Warm went 11.35 ms -> 3.30 ms.

Byte-identity between a hit and a miss is therefore **by construction**: the miss path renders with
the same `JSONRenderer` instance before caching, so a hit returns precisely the bytes that request
would have produced. Do not reintroduce a dict-returning accessor — two payloads for one URL,
varying by cache state, is the subtlest bug this design can have.

## Param hashing — two modes, and the wrong one is a correctness bug

Amended 2026-08-27. The original single rule ("unrecognized params are excluded") is safe only on a
CLOSED parameter surface.

| Surface    | Mode                       | Why                                                                                                                                                                          |
| ---------- | -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `workload` | closed allow-list          | `_parse_common()` returns a fixed validated dict and 400s anything malformed, so the allow-list IS the whole surface. Names are that parsed dict's keys, not raw query args. |
| `viewsext` | hash the full query string | `request.query_params` flows through `issue_filters()` and a `ComplexFilterBackend` filterset — open and independently evolving.                                             |

Excluding a param that DOES change the response makes two different responses collide on one key,
so the cache serves the **wrong data** rather than merely missing. On `viewsext` an allow-list would
go stale silently the moment core adds a filter. Key fragmentation from tracking args is the
accepted cost: a wasted entry is cheap, a collision is wrong.

## Failure posture

Every cache operation is **fail-open**: on any Redis exception, log at `warning` and behave as a
miss (reads) or a no-op (writes). A cache outage must degrade to today's 98.8 ms, never to a 500.

The one deliberate exception is `bump_workspace`: a failed bump means a subsequent read could
serve stale data, which D2 forbids. On bump failure, log at `error` and **fail the request**
rather than silently accepting staleness — a write that appears to succeed while the timeline
keeps showing the old value is the worse outcome.
