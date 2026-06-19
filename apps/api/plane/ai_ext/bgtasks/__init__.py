# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Celery autodiscover picks up tasks from the package modules below.
# All tasks route to the `ai` queue via CELERY_TASK_ROUTES in settings/common.py.
