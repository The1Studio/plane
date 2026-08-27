#!/usr/bin/env bash
# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Raw capacity + configuration of a Plane cache instance.
#
#   ./redis-server-bench.sh plane-staging-app-plane-redis-1
#
# This answers "is the cache server itself a bottleneck". On this deployment the
# answer has always been no: ~212k ops/sec against a measured real load of
# 0.6-6 ops/sec. If you are here because the workload endpoint feels slow, run
# redis_cache_bench.py instead — the endpoint's cost is not Redis.
#
# Read-only apart from the benchmark's own keys, which it writes into db9 and
# flushes afterwards. It never touches db0 (core cache) or db1 (fork cache).
set -euo pipefail

C="${1:-plane-staging-app-plane-redis-1}"
SCRATCH_DB=9

cli() { docker exec "$C" valkey-cli "$@"; }

echo "=== $C ==="
cli INFO server | tr -d '\r' | grep -E '^(redis_version|valkey_version|uptime_in_days|io_threads_active):'

echo
echo "=== configuration ==="
for k in maxmemory maxmemory-policy save appendonly io-threads lazyfree-lazy-eviction activedefrag; do
  printf '  %-26s' "$k"; cli CONFIG GET "$k" | tail -1
done

echo
echo "=== live load (NOT capacity — this is what it is actually being asked to do) ==="
cli INFO stats | tr -d '\r' | grep -E '^(total_commands_processed|instantaneous_ops_per_sec|keyspace_hits|keyspace_misses|expired_keys|evicted_keys):'
cli INFO clients | tr -d '\r' | grep -E '^connected_clients:'
cli INFO keyspace | tr -d '\r' | grep -E '^db[0-9]+:' || echo '  (keyspace empty)'
echo -n '  slowlog_len: '; cli SLOWLOG LEN

echo
echo "=== memory ==="
cli INFO memory | tr -d '\r' | grep -E '^(used_memory_human|used_memory_peak_human|used_memory_rss_human|maxmemory_human|mem_fragmentation_ratio|mem_allocator):'
echo "  NOTE: on a near-empty instance mem_fragmentation_ratio is baseline RSS overhead,"
echo "        not fragmentation. Do not act on it below a few hundred MB of real data."
echo "  NOTE: used_memory sitting near maxmemory once warm is the STEADY STATE, not an"
echo "        incident — fork cache entries carry no TTL, so LRU is the only reclamation."

echo
echo "=== capacity (writes to db$SCRATCH_DB, flushed after) ==="
cli -n "$SCRATCH_DB" FLUSHDB > /dev/null
docker exec "$C" valkey-benchmark -q -n 100000 -c 50 -t set,get -P 1 --dbnum "$SCRATCH_DB" 2>&1 | tr -d '\r' | grep -E 'requests per second' || true
echo "  -- pipelined (P16) --"
docker exec "$C" valkey-benchmark -q -n 100000 -c 50 -t set,get -P 16 --dbnum "$SCRATCH_DB" 2>&1 | tr -d '\r' | grep -E 'requests per second' || true
echo "  -- 1KB values --"
docker exec "$C" valkey-benchmark -q -n 50000 -c 50 -d 1024 -t set,get --dbnum "$SCRATCH_DB" 2>&1 | tr -d '\r' | grep -E 'requests per second' || true
cli -n "$SCRATCH_DB" FLUSHDB > /dev/null
echo "  (db$SCRATCH_DB flushed)"

echo
echo "=== eviction: does this instance shed cold keys, or refuse writes? ==="
echo "  A config never observed evicting is unproven. This fills db$SCRATCH_DB past a"
echo "  TEMPORARY low bound, then restores the real one."
real_max=$(cli CONFIG GET maxmemory | tail -1 | tr -d '\r')
before=$(cli INFO stats | tr -d '\r' | grep '^evicted_keys:' | cut -d: -f2)
cli CONFIG SET maxmemory 32mb > /dev/null
docker exec "$C" valkey-benchmark -n 40000 -c 20 -d 4096 -t set -r 40000 --dbnum "$SCRATCH_DB" > /dev/null 2>&1 || true
after=$(cli INFO stats | tr -d '\r' | grep '^evicted_keys:' | cut -d: -f2)
echo -n "  write while full:    "; cli -n "$SCRATCH_DB" SET canary ok
echo "  evicted during fill: $(( after - before ))"
echo "     >0 with an OK above  = allkeys-lru working (cold keys shed, writes succeed)"
echo "     0  with an OOM above = noeviction — the cache is refusing the app's writes"
cli -n "$SCRATCH_DB" FLUSHDB > /dev/null
cli CONFIG SET maxmemory "$real_max" > /dev/null
echo "  restored maxmemory to $real_max, db$SCRATCH_DB flushed"
