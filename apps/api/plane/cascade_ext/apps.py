# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.apps import AppConfig


class CascadeExtConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "plane.cascade_ext"
    label = "cascade_ext"
    verbose_name = "Cascade Ext (The1Studio)"
