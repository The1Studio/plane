# Generated for github_ext P4 — three-tier StateTransitionConfig scoping.
#
# Adds a nullable `workspace` FK and the `workspace` scope choice so config
# resolves instance-global -> per-workspace -> per-project (services/
# state_transition.py). Additive + nullable — no backfill; existing
# scope="global"/"project" rows are untouched.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("db", "0121_alter_estimate_type"),
        ("github_ext", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="statetransitionconfig",
            name="workspace",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="github_state_transition_configs",
                to="db.workspace",
            ),
        ),
        migrations.AlterField(
            model_name="statetransitionconfig",
            name="scope",
            field=models.CharField(
                choices=[
                    ("global", "Global"),
                    ("workspace", "Workspace"),
                    ("project", "Project"),
                ],
                default="global",
                max_length=16,
            ),
        ),
    ]
