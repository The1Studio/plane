# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from unittest import mock

import pytest

from plane.workload_cache import cache as cache_mod
from plane.workload_cache.cache import render_json
from plane.workload_cache.client import _build_url
from plane.workload_cache.keys import SURFACE_WORKLOAD, version_key

PARAMS = {"granularity": "week", "date_from": "2026-08-01"}
PAYLOAD = {"rows": [{"total": 8}], "meta": {}}


@pytest.fixture
def fake_redis():
    """In-memory stand-in recording the exact calls made."""

    class Fake:
        def __init__(self):
            self.store = {}
            self.set_calls = []
            self.commands = []

        def get(self, k):
            self.commands.append(("get", k))
            return self.store.get(k)

        def set(self, k, v, **kwargs):
            self.commands.append(("set", k))
            self.set_calls.append((k, v, kwargs))
            self.store[k] = v

        def incr(self, k):
            self.commands.append(("incr", k))
            self.store[k] = str(int(self.store.get(k, 0)) + 1).encode()
            return int(self.store[k])

        def keys(self, *a, **kw):  # pragma: no cover - must never be called
            self.commands.append(("keys", a))
            raise AssertionError("KEYS must never be issued by this app")

    f = Fake()
    with mock.patch.object(cache_mod, "get_client", return_value=f):
        yield f


class TestRoundTrip:
    def test_set_then_get_returns_rendered_bytes(self, fake_redis):
        cache_mod.set_cached(SURFACE_WORKLOAD, "cocos", "u1", PARAMS, PAYLOAD)
        got = cache_mod.get_cached_bytes(SURFACE_WORKLOAD, "cocos", "u1", PARAMS)
        assert got == render_json(PAYLOAD)

    def test_hit_is_byte_identical_to_what_the_miss_path_renders(self, fake_redis):
        """The whole reason the cache stores bytes rather than a dict.

        The miss path renders with this same renderer before caching, so a hit
        must be byte-for-byte what that request would have produced. If these
        ever diverge, clients see two different payloads for one URL depending
        on cache state — the subtlest possible bug.
        """
        body = render_json(PAYLOAD)
        cache_mod.set_cached(SURFACE_WORKLOAD, "cocos", "u1", PARAMS, body)
        assert cache_mod.get_cached_bytes(SURFACE_WORKLOAD, "cocos", "u1", PARAMS) == body

    def test_miss_returns_none(self, fake_redis):
        assert cache_mod.get_cached_bytes(SURFACE_WORKLOAD, "cocos", "u1", PARAMS) is None

    def test_other_user_does_not_see_it(self, fake_redis):
        cache_mod.set_cached(SURFACE_WORKLOAD, "cocos", "u1", PARAMS, PAYLOAD)
        assert cache_mod.get_cached_bytes(SURFACE_WORKLOAD, "cocos", "u2", PARAMS) is None


class TestNoExpiry:
    """D6: allkeys-lru is the sole reclamation path.

    Adding a TTL is the reflexive move when reviewing cache code, and here it
    would be wrong — entries would expire on a schedule the design does not
    assume. Asserted explicitly so a well-meaning `ex=3600` fails the suite.
    """

    def test_set_passes_no_expiry(self, fake_redis):
        cache_mod.set_cached(SURFACE_WORKLOAD, "cocos", "u1", PARAMS, PAYLOAD)
        _key, _val, kwargs = fake_redis.set_calls[0]
        assert "ex" not in kwargs and "px" not in kwargs
        assert "exat" not in kwargs and "pxat" not in kwargs
        assert kwargs == {}


class TestVersioning:
    def test_bump_makes_the_previous_entry_unreachable(self, fake_redis):
        cache_mod.set_cached(SURFACE_WORKLOAD, "cocos", "u1", PARAMS, PAYLOAD)
        assert cache_mod.get_cached_bytes(SURFACE_WORKLOAD, "cocos", "u1", PARAMS) == render_json(PAYLOAD)
        cache_mod.bump_workspace("cocos")
        assert cache_mod.get_cached_bytes(SURFACE_WORKLOAD, "cocos", "u1", PARAMS) is None

    def test_bump_uses_incr_and_never_scans(self, fake_redis):
        cache_mod.bump_workspace("cocos")
        assert ("incr", version_key("cocos")) in fake_redis.commands
        assert not any(c[0] == "keys" for c in fake_redis.commands)

    def test_missing_counter_reads_as_zero_without_writing_it(self, fake_redis):
        cache_mod.get_cached_bytes(SURFACE_WORKLOAD, "cocos", "u1", PARAMS)
        assert version_key("cocos") not in fake_redis.store
        assert not any(c[0] in ("set", "incr") for c in fake_redis.commands)

    def test_corrupt_counter_degrades_to_zero(self, fake_redis):
        fake_redis.store[version_key("cocos")] = b"not-an-int"
        assert cache_mod.get_cached_bytes(SURFACE_WORKLOAD, "cocos", "u1", PARAMS) is None

    def test_bump_isolates_workspaces(self, fake_redis):
        cache_mod.set_cached(SURFACE_WORKLOAD, "cocos", "u1", PARAMS, PAYLOAD)
        cache_mod.set_cached(SURFACE_WORKLOAD, "unity", "u1", PARAMS, PAYLOAD)
        cache_mod.bump_workspace("cocos")
        assert cache_mod.get_cached_bytes(SURFACE_WORKLOAD, "cocos", "u1", PARAMS) is None
        assert cache_mod.get_cached_bytes(SURFACE_WORKLOAD, "unity", "u1", PARAMS) == render_json(PAYLOAD)


class TestFailurePosture:
    """Reads and writes fail open; bump_workspace fails loud."""

    def test_read_failure_is_a_miss(self):
        boom = mock.Mock()
        boom.get.side_effect = RuntimeError("redis down")
        with mock.patch.object(cache_mod, "get_client", return_value=boom):
            assert cache_mod.get_cached_bytes(SURFACE_WORKLOAD, "cocos", "u1", PARAMS) is None

    def test_write_failure_is_a_noop(self):
        boom = mock.Mock()
        boom.get.return_value = None
        boom.set.side_effect = RuntimeError("redis down")
        with mock.patch.object(cache_mod, "get_client", return_value=boom):
            cache_mod.set_cached(SURFACE_WORKLOAD, "cocos", "u1", PARAMS, PAYLOAD)

    def test_bump_failure_propagates(self):
        boom = mock.Mock()
        boom.incr.side_effect = RuntimeError("redis down")
        with mock.patch.object(cache_mod, "get_client", return_value=boom):
            with pytest.raises(RuntimeError):
                cache_mod.bump_workspace("cocos")

    def test_no_client_is_survivable_everywhere(self):
        with mock.patch.object(cache_mod, "get_client", return_value=None):
            assert cache_mod.get_cached_bytes(SURFACE_WORKLOAD, "cocos", "u1", PARAMS) is None
            cache_mod.set_cached(SURFACE_WORKLOAD, "cocos", "u1", PARAMS, PAYLOAD)
            cache_mod.bump_workspace("cocos")


class TestClientUrl:
    """The db1 split is what keeps fork keys out of core's KEYS sweeps."""

    def test_appends_db_index_when_absent(self):
        assert _build_url("redis://plane-redis:6379/", db=1) == "redis://plane-redis:6379/1"

    def test_replaces_an_existing_db_index(self):
        assert _build_url("redis://plane-redis:6379/0", db=1) == "redis://plane-redis:6379/1"

    def test_handles_no_trailing_slash(self):
        assert _build_url("redis://plane-redis:6379", db=1) == "redis://plane-redis:6379/1"


class TestCachedJSONResponse:
    """Regression guard: `.data` must survive the bytes optimization.

    Returning a bare HttpResponse was measurably faster and broke 18 views_ext
    tests with AttributeError — `.data` is part of the contract in-process
    callers rely on. These assertions exist so that speedup cannot be
    reintroduced at the cost of the interface again.
    """

    def test_body_is_the_bytes_it_was_given(self):
        body = render_json(PAYLOAD)
        resp = cache_mod.CachedJSONResponse(body, status=200)
        assert resp.content == body
        assert resp["Content-Type"] == "application/json"

    def test_data_is_available_and_correct(self):
        resp = cache_mod.CachedJSONResponse(render_json(PAYLOAD), status=200)
        assert resp.data == PAYLOAD

    def test_data_is_lazy(self):
        """The wire path must not pay the decode cost.

        Constructing the response may not decode; only touching .data may.
        """
        import json as _json
        from unittest import mock

        with mock.patch.object(_json, "loads", side_effect=AssertionError("decoded eagerly")):
            resp = cache_mod.CachedJSONResponse(render_json(PAYLOAD), status=200)
            assert resp.content  # wire path only
