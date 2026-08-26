# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# SP2 P4a — embed-on-write post_save signals.
# Imported from AiExtConfig.ready() (guarded).
# Signals enqueue via transaction.on_commit to avoid pre-commit/rollback races.
# All tasks run on the `ai` queue (CELERY_TASK_ROUTES).

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger("plane.ai_ext")


# ------------------------------------------------------------------
# Issue
# ------------------------------------------------------------------
def _connect_issue():
    from plane.db.models import Issue

    @receiver(post_save, sender=Issue, dispatch_uid="ai_ext_embed_issue")
    def on_issue_save(sender, instance, **kwargs):
        # Skip if no stripped text and no name.
        text = " ".join(
            filter(None, [instance.name, instance.description_stripped])
        )
        if not text or not text.strip():
            return
        if not instance.workspace_id or not instance.project_id:
            return

        from django.db import transaction
        from plane.ai_ext.bgtasks.embed_task import embed_entity, purge_entity_embeddings

        if getattr(instance, "deleted_at", None):
            transaction.on_commit(
                lambda: purge_entity_embeddings.apply_async(
                    kwargs={"entity_type": "issue", "entity_id": str(instance.id)},
                    queue="ai",
                )
            )
        else:
            _workspace_id = str(instance.workspace_id)
            _project_id = str(instance.project_id)
            _text = text
            _entity_id = str(instance.id)
            transaction.on_commit(
                lambda: embed_entity.apply_async(
                    kwargs={
                        "workspace_id": _workspace_id,
                        "project_id": _project_id,
                        "entity_type": "issue",
                        "entity_id": _entity_id,
                        "text": _text,
                    },
                    queue="ai",
                )
            )


# ------------------------------------------------------------------
# IssueComment
# ------------------------------------------------------------------
def _connect_issue_comment():
    from plane.db.models import IssueComment

    @receiver(post_save, sender=IssueComment, dispatch_uid="ai_ext_embed_issue_comment")
    def on_comment_save(sender, instance, **kwargs):
        text = instance.comment_stripped
        if not text or not text.strip():
            return
        if not instance.workspace_id or not instance.project_id:
            return

        from django.db import transaction
        from plane.ai_ext.bgtasks.embed_task import embed_entity, purge_entity_embeddings

        if getattr(instance, "deleted_at", None):
            transaction.on_commit(
                lambda: purge_entity_embeddings.apply_async(
                    kwargs={"entity_type": "issue_comment", "entity_id": str(instance.id)},
                    queue="ai",
                )
            )
        else:
            _workspace_id = str(instance.workspace_id)
            _project_id = str(instance.project_id)
            _text = text
            _entity_id = str(instance.id)
            transaction.on_commit(
                lambda: embed_entity.apply_async(
                    kwargs={
                        "workspace_id": _workspace_id,
                        "project_id": _project_id,
                        "entity_type": "issue_comment",
                        "entity_id": _entity_id,
                        "text": _text,
                    },
                    queue="ai",
                )
            )


# ------------------------------------------------------------------
# Page
# ------------------------------------------------------------------
def _connect_page():
    from plane.db.models import Page

    @receiver(post_save, sender=Page, dispatch_uid="ai_ext_embed_page")
    def on_page_save(sender, instance, **kwargs):
        text = instance.description_stripped
        if not text or not text.strip():
            return
        if not instance.workspace_id:
            return

        from django.db import transaction
        from plane.ai_ext.bgtasks.embed_task import embed_entity, purge_entity_embeddings

        # Pages may span multiple projects (ProjectPage M2M); use project=None.
        if getattr(instance, "deleted_at", None):
            transaction.on_commit(
                lambda: purge_entity_embeddings.apply_async(
                    kwargs={"entity_type": "page", "entity_id": str(instance.id)},
                    queue="ai",
                )
            )
        else:
            _workspace_id = str(instance.workspace_id)
            _text = text
            _entity_id = str(instance.id)
            transaction.on_commit(
                lambda: embed_entity.apply_async(
                    kwargs={
                        "workspace_id": _workspace_id,
                        "project_id": None,
                        "entity_type": "page",
                        "entity_id": _entity_id,
                        "text": _text,
                    },
                    queue="ai",
                )
            )


# ------------------------------------------------------------------
# M1 FIX: on_page_acl_change was a dead no-op (`pass` body).
# Removed — _connect_page() above already handles every Page save, and
# retrieval-time live-filtering in _get_accessible_entity_ids() is the
# SOLE ACL gate (embeddings are corpus keys, not auth tokens).
# A page access flip (public→private) takes effect instantly for new
# queries without any re-embed: the live filter checks
#   Q(access=0) | Q(created_by=user)
# at query time.  No separate ACL signal is needed.
# ------------------------------------------------------------------


# ------------------------------------------------------------------
# Project — ACL re-stamp on network change
# ------------------------------------------------------------------
def _connect_project():
    from plane.db.models import Project

    @receiver(post_save, sender=Project, dispatch_uid="ai_ext_embed_project")
    def on_project_save(sender, instance, **kwargs):
        text = instance.description
        if not text or not text.strip():
            return
        if not instance.workspace_id:
            return

        from django.db import transaction
        from plane.ai_ext.bgtasks.embed_task import embed_entity

        _workspace_id = str(instance.workspace_id)
        _project_id = str(instance.id)
        _text = text
        transaction.on_commit(
            lambda: embed_entity.apply_async(
                kwargs={
                    "workspace_id": _workspace_id,
                    "project_id": _project_id,
                    "entity_type": "project",
                    "entity_id": _project_id,
                    "text": _text,
                },
                queue="ai",
            )
        )


# ------------------------------------------------------------------
# Cycle
# ------------------------------------------------------------------
def _connect_cycle():
    from plane.db.models import Cycle

    @receiver(post_save, sender=Cycle, dispatch_uid="ai_ext_embed_cycle")
    def on_cycle_save(sender, instance, **kwargs):
        text = getattr(instance, "description", None)
        if not text or not text.strip():
            return
        if not instance.workspace_id or not instance.project_id:
            return

        from django.db import transaction
        from plane.ai_ext.bgtasks.embed_task import embed_entity

        _workspace_id = str(instance.workspace_id)
        _project_id = str(instance.project_id)
        _text = text
        _entity_id = str(instance.id)
        transaction.on_commit(
            lambda: embed_entity.apply_async(
                kwargs={
                    "workspace_id": _workspace_id,
                    "project_id": _project_id,
                    "entity_type": "cycle",
                    "entity_id": _entity_id,
                    "text": _text,
                },
                queue="ai",
            )
        )


# ------------------------------------------------------------------
# Module
# ------------------------------------------------------------------
def _connect_module():
    from plane.db.models import Module

    @receiver(post_save, sender=Module, dispatch_uid="ai_ext_embed_module")
    def on_module_save(sender, instance, **kwargs):
        text = getattr(instance, "description", None)
        if not text or not text.strip():
            return
        if not instance.workspace_id or not instance.project_id:
            return

        from django.db import transaction
        from plane.ai_ext.bgtasks.embed_task import embed_entity

        _workspace_id = str(instance.workspace_id)
        _project_id = str(instance.project_id)
        _text = text
        _entity_id = str(instance.id)
        transaction.on_commit(
            lambda: embed_entity.apply_async(
                kwargs={
                    "workspace_id": _workspace_id,
                    "project_id": _project_id,
                    "entity_type": "module",
                    "entity_id": _entity_id,
                    "text": _text,
                },
                queue="ai",
            )
        )


# ------------------------------------------------------------------
# Wire all signals (called from AiExtConfig.ready())
# ------------------------------------------------------------------
_connect_issue()
_connect_issue_comment()
_connect_page()
# _connect_page_acl() removed (M1 fix — was dead no-op; live filter is the ACL gate)
_connect_project()
_connect_cycle()
_connect_module()

logger.debug("plane.ai_ext: embed-on-write signals registered")
