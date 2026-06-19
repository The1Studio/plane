# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# The1Studio fork add-on app (SP1 — one-time ClickUp -> Plane ETL).
# Self-contained per docs/FORK.md isolation convention: owns its own
# migrations; the ONLY core touch-point is the INSTALLED_APPS append.
from django.apps import AppConfig


class ClickupMigrateConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "plane.clickup_migrate"
    label = "clickup_migrate"
    verbose_name = "ClickUp Migration (The1Studio)"
