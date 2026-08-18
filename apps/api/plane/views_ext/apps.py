# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.apps import AppConfig


class ViewsExtConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "plane.views_ext"
    label = "views_ext"
    verbose_name = "Views Ext (The1Studio)"
