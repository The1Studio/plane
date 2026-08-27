# Phase 1 — Cache instance hardening

**Goal:** give the Valkey instance cache semantics (bounded memory, LRU eviction) and stop paying
for persistence nothing depends on. Config only — no application code changes.

**Depends on:** nothing. Runs in parallel with Phases 2 and 4.

**Owns:** `deployments/selfhost/deploy.sh`, `deployments/cli/community/docker-compose.yml`
(fork-side override only), staging and production run-dir config on `server`.

**Status: implemented 2026-08-27.** The override block in `deploy.sh` now writes the
`plane-redis` command **unconditionally** — previously it was written only when `LOCAL_DB=0` or
`LOCAL_STORAGE=0`, and the cache config must not depend on unrelated gate flags.

---

## Why

Measured 2026-08-26 on `plane-staging-app-plane-redis-1`:

```
maxmemory                   0
maxmemory-policy            noeviction
save                        3600 1 300 100 60 10000
appendonly                  no
```

`noeviction` on an unbounded cache means that once memory fills, Valkey **returns errors on writes
rather than evicting** — the cache would break the application instead of shedding cold keys. This
is inert at today's 1.10 MB and becomes live the moment Phase 3 starts writing ~320 KB entries.

RDB persistence on a pure cache is a periodic background fork plus disk write that nothing reads.

## Target config (D3, D4)

| Key                | From                      | To               |
| ------------------ | ------------------------- | ---------------- |
| `maxmemory`        | `0`                       | `1gb`            |
| `maxmemory-policy` | `noeviction`              | `allkeys-lru`    |
| `save`             | `3600 1 300 100 60 10000` | `""` (disabled)  |
| `appendonly`       | `no`                      | `no` (unchanged) |

`allkeys-lru`, not `volatile-lru` — and **D6 makes this mandatory rather than merely preferable.**
`volatile-*` can only evict keys that carry an expiry, degrading to `noeviction` behaviour for any
key that does not. Fork cache entries are written with **no TTL at all** (D6), so under
`volatile-lru` they would be _entirely unevictable_: the instance would fill and start refusing
writes, which is precisely the failure this phase exists to remove. `allkeys-lru` has no such
blind spot.

## Steps

1. Add the config to the compose service definition so it survives a redeploy. The upstream
   `plane-redis` service takes no `command:`; the fork override adds one. Land this in the
   deploy-time override that `deploy.sh` already generates (the same mechanism used for
   `LOCAL_DB` / `LOCAL_STORAGE`), so `deployments/cli/community/docker-compose.yml` — an upstream
   file — is not edited.

   ```yaml
   plane-redis:
     command: >
       valkey-server
       --maxmemory 1gb
       --maxmemory-policy allkeys-lru
       --save ""
   ```

2. Apply to **staging** and verify:

   ```bash
   ssh server 'C=plane-staging-app-plane-redis-1
   for k in maxmemory maxmemory-policy save; do
     printf "%-20s" "$k"; docker exec $C valkey-cli CONFIG GET $k | tail -1
   done'
   ```

   Expect `1073741824`, `allkeys-lru`, empty.

3. Confirm the running config is what the compose file says, not a leftover `CONFIG SET`. Restart
   the service and re-read — a value that only exists at runtime is not wired
   (`rules/wired-not-just-present.md`).

4. **Prove the eviction actually fires.** A config that has never been observed evicting is
   unproven. Fill past the bound in a scratch db and assert `evicted_keys` rises and writes keep
   succeeding:

   ```bash
   ssh server 'C=plane-staging-app-plane-redis-1
   docker exec $C valkey-cli -n 9 FLUSHDB
   docker exec $C valkey-benchmark -q -n 200000 -c 20 -d 8192 -t set -r 200000 --dbnum 9 >/dev/null
   docker exec $C valkey-cli INFO stats | grep evicted_keys
   docker exec $C valkey-cli -n 9 SET canary ok        # must return OK, not OOM
   docker exec $C valkey-cli -n 9 FLUSHDB'
   ```

   `SET canary ok` returning `OK` under memory pressure is the whole point of this phase. Under the
   old config it would have returned `OOM command not allowed when used memory > maxmemory`.

5. Apply to **production** as a separate, explicit step after staging verifies (D4). Production
   holds 3 keys / 1.10 MB, so the change is not disruptive, but it restarts the container — confirm
   the API reconnects (`docker logs plane-fork-app-api-1 --tail 20`).

## Verified 2026-08-27, before touching either stack

Proven against throwaway Valkey containers rather than asserted.

**The compose string splits correctly.** `command:` folds to a single string, which Compose splits
shell-style, and `--save ""` is exactly the shape that silently half-works. It does not:

```
docker inspect -> ["valkey-server","--maxmemory","1gb","--maxmemory-policy","allkeys-lru","--save",""]
maxmemory 1073741824 | maxmemory-policy allkeys-lru | save (empty) | appendonly no
```

**Eviction fires, and the old config genuinely failed.** Same 32 MB cap, same ~160 MB of writes:

| Policy              | Keys stored     | Evicted    | Benchmark                                                     |
| ------------------- | --------------- | ---------- | ------------------------------------------------------------- |
| `noeviction` (old)  | 6,133 of 40,000 | 0          | **errored out, no throughput summary** — ~34k writes rejected |
| `allkeys-lru` (new) | 6,132 of 40,000 | **28,206** | completed, 206,185 req/s                                      |

Both held at 31.35 M. The ceiling is identical; the difference is entirely whether the application's
writes succeed. That is the failure this phase removes.

**RDB is off:** `/data` stays empty and `rdb_changes_since_last_save` climbs with no bgsave.

_An earlier probe in this session appeared to show `noeviction` accepting a write under pressure and
was inconclusive, not a disproof — `noeviction` rejects writes only while `used_memory > maxmemory`,
so it hovers at the boundary and a tiny `SET` still fits. The table above writes enough to make the
rejection unambiguous._

## Success criteria

- `CONFIG GET` on both stacks returns the target values **after a container restart**, not only
  after a `CONFIG SET`.
- Step 4's canary `SET` succeeds while `evicted_keys > 0`.
- `SLOWLOG LEN` remains `0` on both stacks.
- No RDB write occurs: `rdb_changes_since_last_save` climbs without `rdb_last_save_time` advancing.

## Rollback

Revert the `command:` block and redeploy. No data is at risk — the cache holds nothing that is not
recomputable, which is the same premise that justifies disabling RDB.
