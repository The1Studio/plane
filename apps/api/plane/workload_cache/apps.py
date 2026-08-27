# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.apps import AppConfig


class WorkloadCacheConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "plane.workload_cache"
    label = "workload_cache"
    verbose_name = "Workload Response Cache (The1Studio)"

    def ready(self):
        # Registers the post_save/post_delete receivers that bump each
        # workspace's version counter. Importing here rather than at module
        # scope is what makes the signals actually fire — an unimported
        # receiver module is present but never wired.
        from . import signals  # noqa: F401
