# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from rest_framework import serializers

from .aggregation import MAX_HOURS, quantize_hours
from .models import WorkloadCapacity, WorkloadEstimate, WorkloadSettings


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


class WorkloadSettingsSerializer(serializers.ModelSerializer):
    """Serializes/validates exactly the payload pinned in phase-0.md's
    contract (`TWorkSettings`) — no id/workspace/timestamps in the body.
    `workspace` is always server-derived from the slug, never client
    supplied, and is not part of the wire shape at all (unlike
    WorkloadCapacitySerializer, which exposes it as read-only)."""

    class Meta:
        model = WorkloadSettings
        fields = ["max_weekly_hours", "workdays", "week_start_day"]

    def validate_max_weekly_hours(self, value):
        if value is None or value < 0:
            raise serializers.ValidationError("max_weekly_hours must be a number >= 0")
        if value > MAX_HOURS:
            raise serializers.ValidationError(f"max_weekly_hours must be <= {MAX_HOURS}")
        # Quantize via the SAME cents rounding the aggregation uses (SSOT).
        return quantize_hours(value)

    def validate_workdays(self, value):
        # Empty workdays is the divide-by-zero the whole feature guards
        # against (plan risk table) — reject at the serializer, backstopped
        # by the model's CheckConstraint for writers that bypass DRF.
        if not value:
            raise serializers.ValidationError("workdays must not be empty")
        for day in value:
            if not isinstance(day, int) or day < 0 or day > 6:
                raise serializers.ValidationError("each workday must be an integer 0..6")
        if len(set(value)) != len(value):
            raise serializers.ValidationError("workdays must not contain duplicates")
        # Normalize to ascending order on write so storage is canonical
        # regardless of client-submitted order.
        return sorted(value)

    def validate_week_start_day(self, value):
        if value is None or not isinstance(value, int) or value < 0 or value > 6:
            raise serializers.ValidationError("week_start_day must be an integer 0..6")
        return value
