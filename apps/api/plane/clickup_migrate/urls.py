# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# SP1 clickup_migrate has no HTTP endpoints — all operations are
# management-command-driven (migrate_clickup --plan / --apply).
# This file is provided so the app is self-contained per docs/FORK.md
# and the URL include does not error if mounted.


urlpatterns: list = []
