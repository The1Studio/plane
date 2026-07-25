# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from rest_framework import serializers

from .aggregation import MAX_HOURS, quantize_hours
from .models import WorkloadCapacity, WorkloadEstimate


class WorkloadEstimateSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkloadEstimate
        fields = ["id", "issue", "hours", "created_at", "updated_at"]
        read_only_fields = ["id", "issue", "created_at", "updated_at"]

    def validate_hours(self, value):
        if value is None or value < 0:
            raise serializers.ValidationError("hours must be a number >= 0")
        if value > MAX_HOURS:
            raise serializers.ValidationError(f"hours must be <= {MAX_HOURS}")
        # Quantize via the SAME cents rounding the aggregation uses (SSOT).
        return quantize_hours(value)


class WorkloadCapacitySerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkloadCapacity
        fields = ["id", "member", "workspace", "project", "weekly_hours", "created_at", "updated_at"]
        # `member` stays writable — the capacity endpoint has no member URL
        # segment, so PUT/DELETE identify the target row via the request
        # body (docs/plan Delta B contract). workspace/project are always
        # server-derived (slug + v1 project=None), never client-supplied.
        read_only_fields = ["id", "workspace", "project", "created_at", "updated_at"]

    def validate_weekly_hours(self, value):
        if value is None or value < 0:
            raise serializers.ValidationError("weekly_hours must be a number >= 0")
        if value > MAX_HOURS:
            raise serializers.ValidationError(f"weekly_hours must be <= {MAX_HOURS}")
        # Quantize via the SAME cents rounding the aggregation uses (SSOT).
        return quantize_hours(value)
