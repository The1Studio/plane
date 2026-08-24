# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.apps import AppConfig


class IssueDefaultsExtConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "plane.issue_defaults_ext"
    label = "issue_defaults_ext"
    verbose_name = "Issue Creation Defaults (The1Studio)"
