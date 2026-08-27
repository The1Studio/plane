# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest
from django.http import QueryDict

from plane.workload_cache.keys import (
    SURFACE_VIEWSEXT,
    SURFACE_WORKLOAD,
    entry_key,
    params_hash,
    version_key,
)


class TestClosedAllowList:
    """workload/: only listed params may affect the key."""

    def test_dict_order_does_not_change_the_key(self):
        a = {"granularity": "week", "date_from": "2026-08-01", "date_to": "2026-10-31"}
        b = {"date_to": "2026-10-31", "granularity": "week", "date_from": "2026-08-01"}
        assert params_hash(SURFACE_WORKLOAD, a) == params_hash(SURFACE_WORKLOAD, b)

    def test_changed_granularity_changes_the_key(self):
        base = {"granularity": "week", "date_from": "2026-08-01"}
        other = {"granularity": "month", "date_from": "2026-08-01"}
        assert params_hash(SURFACE_WORKLOAD, base) != params_hash(SURFACE_WORKLOAD, other)

    def test_unrecognized_param_does_not_change_the_key(self):
        base = {"granularity": "week"}
        noisy = {"granularity": "week", "utm_source": "slack", "_": "1724668800"}
        assert params_hash(SURFACE_WORKLOAD, base) == params_hash(SURFACE_WORKLOAD, noisy)

    def test_list_order_does_not_change_the_key(self):
        a = {"assignee_ids": ["u2", "u1"]}
        b = {"assignee_ids": ["u1", "u2"]}
        assert params_hash(SURFACE_WORKLOAD, a) == params_hash(SURFACE_WORKLOAD, b)

    def test_empty_and_absent_are_the_same(self):
        assert params_hash(SURFACE_WORKLOAD, {"granularity": "week"}) == params_hash(
            SURFACE_WORKLOAD, {"granularity": "week", "state_groups": []}
        )


class TestOpenSurface:
    """views_ext/: every param must affect the key.

    This is the collision guard. If an allow-list were reintroduced here, two
    differently-filtered responses would share a key and the cache would serve
    the wrong data — the failure this mode exists to prevent.
    """

    def test_an_arbitrary_filter_changes_the_key(self):
        a = QueryDict("group_by=state")
        b = QueryDict("group_by=state&priority=urgent")
        assert params_hash(SURFACE_VIEWSEXT, a) != params_hash(SURFACE_VIEWSEXT, b)

    def test_a_filter_core_might_add_tomorrow_changes_the_key(self):
        # Deliberately a name this code has never heard of.
        a = QueryDict("group_by=state")
        b = QueryDict("group_by=state&some_future_filter=42")
        assert params_hash(SURFACE_VIEWSEXT, a) != params_hash(SURFACE_VIEWSEXT, b)

    def test_querydict_multivalue_is_stable(self):
        a = QueryDict("project=b&project=a")
        b = QueryDict("project=a&project=b")
        assert params_hash(SURFACE_VIEWSEXT, a) == params_hash(SURFACE_VIEWSEXT, b)


class TestEntryKey:
    def test_two_users_never_collide(self):
        p = {"granularity": "week"}
        assert entry_key(SURFACE_WORKLOAD, "cocos", "user-a", 3, p) != entry_key(
            SURFACE_WORKLOAD, "cocos", "user-b", 3, p
        )

    def test_version_is_in_the_key(self):
        p = {"granularity": "week"}
        assert entry_key(SURFACE_WORKLOAD, "cocos", "u", 3, p) != entry_key(
            SURFACE_WORKLOAD, "cocos", "u", 4, p
        )

    def test_unknown_surface_is_rejected_loudly(self):
        with pytest.raises(ValueError):
            entry_key("typo", "cocos", "u", 1, {})

    def test_version_key_shape(self):
        assert version_key("cocos") == "wlc:ver:cocos"
