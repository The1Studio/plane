# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# GitHub integration fork models (P0). All new tables live here — no edits
# to core plane/db/models/ (fork isolation, docs/FORK.md). Every FK to a
# core model is declared by STRING reference ("db.Workspace", "db.Project",
# "db.Issue") — never an import of the core model class.

import uuid

from django.db import models


class GithubInstallation(models.Model):
    """One row per installed GitHub App installation.

    Bound to a Plane workspace out-of-band (backend-only MVP, no admin UI in
    P0 — see plan §0): an admin creates a `WorkspaceIntegration` row for
    `Integration(provider="github")` pointing at the target workspace, and
    `services/installation.py` resolves it from there.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    installation_id = models.CharField(max_length=64, unique=True)
    account_login = models.CharField(max_length=255)
    workspace = models.ForeignKey(
        "db.Workspace",
        on_delete=models.CASCADE,
        related_name="github_installations",
    )
    config = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "github_ext_installations"
        verbose_name = "GitHub Installation"
        verbose_name_plural = "GitHub Installations"

    def __str__(self):
        return f"GithubInstallation({self.installation_id}, {self.account_login})"


class RepoProjectMap(models.Model):
    """Maps a GitHub repo (within an installation) to a Plane project.

    Auto-seeded from `installation` / `installation_repositories` webhooks
    (repo -> inferred project by name match). `project` is left null when
    the repo cannot be confidently matched — never guessed. Editable later
    via the P4 API/MCP surface.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    installation = models.ForeignKey(
        GithubInstallation,
        on_delete=models.CASCADE,
        related_name="repo_project_maps",
    )
    repo_full_name = models.CharField(max_length=400)
    project = models.ForeignKey(
        "db.Project",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="github_repo_maps",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "github_ext_repo_project_maps"
        verbose_name = "GitHub Repo Project Map"
        verbose_name_plural = "GitHub Repo Project Maps"
        unique_together = [("installation", "repo_full_name")]

    def __str__(self):
        return f"RepoProjectMap({self.repo_full_name} -> {self.project_id})"


class WorkItemGithubLink(models.Model):
    """Reference link between a Plane Issue and a GitHub object.

    Defined in P0; written by the P1 link-parsing pipeline (branch/PR/commit
    reference detection) and mirrored into the existing IssueLink UI.
    """

    LINK_TYPE_CHOICES = (
        ("branch", "Branch"),
        ("pr", "Pull Request"),
        ("commit", "Commit"),
        ("issue", "Issue"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    issue = models.ForeignKey(
        "db.Issue",
        on_delete=models.CASCADE,
        related_name="github_links",
    )
    project = models.ForeignKey(
        "db.Project",
        on_delete=models.CASCADE,
        related_name="github_links",
    )
    link_type = models.CharField(max_length=16, choices=LINK_TYPE_CHOICES)
    external_id = models.CharField(max_length=255)
    url = models.TextField()
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "github_ext_work_item_links"
        verbose_name = "Work Item GitHub Link"
        verbose_name_plural = "Work Item GitHub Links"
        unique_together = [("issue", "link_type", "external_id")]

    def __str__(self):
        return f"WorkItemGithubLink({self.issue_id}, {self.link_type}:{self.external_id})"


class StateTransitionConfig(models.Model):
    """Configurable state-transition rules driven by GitHub PR lifecycle.

    Defined in P0; consumed by the P2 status-automation pipeline. `rules` is
    an opaque JSON blob owned by P2 (e.g. {"pr_opened": "in_progress", ...}).
    """

    SCOPE_CHOICES = (
        ("global", "Global"),
        ("project", "Project"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scope = models.CharField(max_length=16, choices=SCOPE_CHOICES, default="global")
    project = models.ForeignKey(
        "db.Project",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="github_state_transition_configs",
    )
    rules = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "github_ext_state_transition_configs"
        verbose_name = "GitHub State Transition Config"
        verbose_name_plural = "GitHub State Transition Configs"

    def __str__(self):
        return f"StateTransitionConfig({self.scope}, project={self.project_id})"


class WebhookDelivery(models.Model):
    """Idempotency ledger for inbound GitHub webhook deliveries.

    NEVER store token/secret bytes here. `headers` is an allowlisted subset
    of the inbound request headers (event/delivery/signature/UA metadata
    only) for debugging — see webhook/views.py `_safe_headers`.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    delivery_id = models.CharField(max_length=64, unique=True)
    event_type = models.CharField(max_length=64)
    received_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=32, default="received")
    headers = models.JSONField(default=dict)

    class Meta:
        db_table = "github_ext_webhook_deliveries"
        verbose_name = "GitHub Webhook Delivery"
        verbose_name_plural = "GitHub Webhook Deliveries"

    def __str__(self):
        return f"WebhookDelivery({self.delivery_id}, {self.event_type}, {self.status})"
