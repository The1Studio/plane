# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# GitHub integration fork add-on app (P0 — ingest spine).
# ready() import mirrors ai_ext/apps.py: deferred + guarded so a partial
# build / missing optional dep never blocks app startup.

from django.apps import AppConfig


class GithubExtConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "plane.github_ext"
    label = "github_ext"
    verbose_name = "GitHub Integration (The1Studio)"

    def ready(self):
        try:
            from plane.github_ext import signals  # noqa: F401
        except ImportError:
            pass
