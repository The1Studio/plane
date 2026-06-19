# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from rest_framework import serializers

from .aggregation import MAX_HOURS, quantize_hours
from .models import WorkloadEstimate


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
