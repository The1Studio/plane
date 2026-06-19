# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Atomic Redis-based dollar cost tracker (SP2 P1).
# Tracks monthly spend per workspace using INCRBY on integer micro-dollars
# (1 USD = 1_000_000 micro-USD) to keep atomicity without floats.

import calendar
import logging
import time
from datetime import datetime, timezone

from django.conf import settings

from plane.settings.redis import redis_instance

logger = logging.getLogger("plane.ai_ext")

# 1 USD represented as micro-dollars for integer Redis ops.
_USD_SCALE = 1_000_000

# Cost-check key TTL: always set to expire at next month boundary + buffer.
_KEY_TTL_BUFFER_SECS = 86_400  # 1-day safety buffer after month end


def _month_key(workspace_id: str) -> str:
    """Redis key for monthly spend counter: ai:cost:<workspace_id>:<YYYY-MM>"""
    now = datetime.now(tz=timezone.utc)
    return f"ai:cost:{workspace_id}:{now.year:04d}-{now.month:02d}"


def _month_ttl_secs() -> int:
    """Seconds until end of current month (UTC) + buffer."""
    now = datetime.now(tz=timezone.utc)
    _, last_day = calendar.monthrange(now.year, now.month)
    end_of_month = datetime(now.year, now.month, last_day, 23, 59, 59, tzinfo=timezone.utc)
    ttl = int((end_of_month - now).total_seconds()) + _KEY_TTL_BUFFER_SECS
    return max(ttl, 3600)


class CostTracker:
    """Atomic per-workspace monthly spend tracker backed by Redis.

    Usage:
        tracker = CostTracker(workspace_id="…")
        tracker.record(0.0042)          # record USD cost after an API call
        tracker.check_ceiling(5.00)     # raises CostCeilingExceeded if over
    """

    def __init__(self, workspace_id: str):
        self._workspace_id = str(workspace_id)
        self._ri = redis_instance()

    def record(self, cost_usd: float) -> None:
        """Atomically add cost_usd to the monthly counter."""
        if cost_usd <= 0:
            return
        micro = int(cost_usd * _USD_SCALE)
        key = _month_key(self._workspace_id)
        pipe = self._ri.pipeline()
        pipe.incrby(key, micro)
        pipe.expire(key, _month_ttl_secs())
        pipe.execute()

    def current_spend_usd(self) -> float:
        """Read current month spend in USD (approximate — Redis int)."""
        key = _month_key(self._workspace_id)
        val = self._ri.get(key)
        if val is None:
            return 0.0
        return int(val) / _USD_SCALE

    def check_ceiling(self, ceiling_usd: float) -> None:
        """Raise CostCeilingExceeded if monthly spend >= ceiling_usd.

        ceiling_usd == 0 means no ceiling (always passes).
        """
        if ceiling_usd <= 0:
            return
        spent = self.current_spend_usd()
        if spent >= ceiling_usd:
            raise CostCeilingExceeded(
                f"AI quota exceeded: ${spent:.4f} >= ${ceiling_usd:.2f} "
                f"monthly ceiling for workspace {self._workspace_id}"
            )

    def pre_reserve(self, estimated_cost_usd: float, ceiling_usd: float) -> None:
        """Reserve an estimated cost atomically before submitting a Batch.

        Raises CostCeilingExceeded if current + estimated would exceed ceiling.
        If ceiling is 0, no check is performed.
        """
        if ceiling_usd <= 0:
            return
        # Read → check → write is not fully atomic but acceptable for cost
        # tracking (eventual consistency; ceiling is a soft limit).
        spent = self.current_spend_usd()
        if spent + estimated_cost_usd >= ceiling_usd:
            raise CostCeilingExceeded(
                f"AI pre-reserve: estimated ${estimated_cost_usd:.4f} would push "
                f"total ${spent + estimated_cost_usd:.4f} >= ${ceiling_usd:.2f} ceiling"
            )
        self.record(estimated_cost_usd)


class CostCeilingExceeded(Exception):
    """Raised when an AI operation would exceed the workspace monthly budget."""
