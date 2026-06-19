# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# The1Studio fork add-on app (SP2 — AI feature suite).
# Self-contained per docs/FORK.md isolation convention: owns its own
# migrations + CreateExtension('vector'); registers embed-on-write
# post_save signals from ready() (no core viewset edits). Core
# touch-points are append-only: INSTALLED_APPS, urls.py include,
# CELERY routing settings, requirements, the BGE sidecar compose, and
# the frontend extended.ts route.
from django.apps import AppConfig


class AiExtConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "plane.ai_ext"
    label = "ai_ext"
    verbose_name = "AI Extensions (The1Studio)"

    def ready(self):
        # Wire embed-on-write post_save signals. Import is deferred to
        # ready() so model loading is complete. Guarded so a partial
        # build / missing optional dep never blocks app startup.
        try:
            from plane.ai_ext import signals  # noqa: F401
        except ImportError:
            pass
