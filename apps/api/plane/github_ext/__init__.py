# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# The1Studio fork add-on app — GitHub <-> Plane integration (P0 ingest spine).
# Self-contained per docs/FORK.md isolation convention: owns its own
# migrations + tables; no edits to core `plane/db/models/`. Core touch-points
# are append-only: INSTALLED_APPS (tp1), urls.py include (tp2).
