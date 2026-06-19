# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# The1Studio fork add-on app — time-based estimates (hours) per issue +
# per-person workload (day/week/month). Self-contained per docs/FORK.md:
# owns its own table + migrations; core touch-points are append-only
# (INSTALLED_APPS, urls.py, frontend extended route, issue sidebar input).
