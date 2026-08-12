# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# project_ext owns NO tables.
#
# This app exists solely to expose an endpoint for a column that already lives
# on the core `Project` model (`network`) but is absent from the core public-API
# serializer (`plane.api.serializers.project.ProjectCreateSerializer.Meta.fields`),
# which makes project visibility unreachable over /api/v1/ — see docs/FORK.md.
#
# Per docs/FORK.md we do NOT add the field to the core serializer (that is a core
# file, not a touch-point, and would conflict on every upstream rebase). We also
# do not add a column to a core model. There is therefore nothing to migrate:
# `migrations/` holds only `__init__.py` and `makemigrations --check` stays clean.
