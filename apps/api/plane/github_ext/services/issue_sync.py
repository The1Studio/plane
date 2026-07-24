# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# P3 — bidirectional issue/comment mirror: field mapping, provenance stamping,
# the echo-loop guard, and the two write channels (inbound service-token
# internal API, outbound installation-token GitHub REST).
#
# ---------------------------------------------------------------------------
# Bookkeeping decision (phase-P3.md "Decision at start of P3")
# ---------------------------------------------------------------------------
# The plan recommended reusing the dormant core models `GithubIssueSync` /
# `GithubCommentSync` "storing provenance in their existing JSON fields".
# Verified against db/models/integration/github.py:54-87 — that premise does
# not hold: NEITHER model has a JSON/metadata column (their only fields are
# BigInteger ids + FKs), and adding one would be a new column on a core model,
# which docs/FORK.md forbids. `GithubIssueSync.repository_sync` is also a
# required FK to `GithubRepositorySync`, which in turn requires a
# `GithubRepository` + `actor` + `workspace_integration` row — writing one
# mirror record would force a parallel repo->project mapping chain that
# duplicates github_ext's own `RepoProjectMap` SSOT.
#
# So P3 reuses EXISTING tables, just not those two:
#
#   1. Issue mirror + provenance -> `WorkItemGithubLink` (github_ext-owned,
#      P0). It already declares `link_type="issue"` in LINK_TYPE_CHOICES, has
#      a `metadata` JSONField, and is `unique(issue, link_type, external_id)`
#      — exactly the idempotent mapping row P3 needs, with a real home for the
#      provenance stamp.
#   2. Cross-side identity -> the CORE `Issue.external_source/external_id` and
#      `IssueComment.external_source/external_id` columns, which already exist
#      (db/models/issue.py:161-162, 464-465) and which Plane's own public API
#      treats as the integration-provenance slot (it 409s on a duplicate
#      external pair — free double-create protection).
#
# Net: zero new tables, zero migrations, zero core columns.
#
# ---------------------------------------------------------------------------
# Echo-loop guard (phase-P3.md top risk, 20/25)
# ---------------------------------------------------------------------------
# Two independent guards, both required:
#
#   (a) Actor guard — drop any inbound event whose `sender.login` is our own
#       App bot (`GithubInstallation.config["bot_login"]`). Same primitive P2
#       uses in bgtasks/transition_task.py, applied to content sync.
#   (b) Provenance guard — `is_reflection()` below. The mirror row records
#       WHICH SIDE originated the last applied sync (`source`) plus a
#       per-side content hash. A write toward a side whose own content we
#       last took the sync FROM, carrying identical content, is a reflection
#       and is dropped.
#
# The per-side hash is what keeps guard (b) precise rather than lossy: a bare
# `source == target` rule would also drop a genuine human edit made on the
# side we last wrote to. Hashes are stored per side (`github_hash`,
# `plane_hash`) because the two sides hold different representations of the
# same content (GitHub markdown vs Plane HTML) — one shared hash could never
# match across the boundary.

import hashlib
import logging
import os
import time

from django.utils import timezone
from django.utils.html import escape

logger = logging.getLogger("plane.github_ext")

# Provenance side identifiers (values of the `source` stamp).
SOURCE_GITHUB = "github"
SOURCE_PLANE = "plane"

# Written to the core Issue/IssueComment `external_source` column.
EXTERNAL_SOURCE = "github"

# WorkItemGithubLink.link_type used for the issue mirror row.
MIRROR_LINK_TYPE = "issue"

GITHUB_API_ROOT = "https://api.github.com"
GITHUB_ACCEPT = "application/vnd.github+json"
GITHUB_API_VERSION = "2022-11-28"

# App JWT lifetime. GitHub rejects anything over 10 minutes; 9 leaves headroom
# for clock skew (which is also why `iat` is backdated 60s).
_APP_JWT_TTL_SECONDS = 540

_HTTP_TIMEOUT = 30


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------


def github_content_hash(title, body):
    """Canonical hash of the GitHub-side content of an issue/comment."""
    payload = "\x00".join([title or "", body or ""])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def plane_content_hash(name, description_html):
    """Canonical hash of the Plane-side content of a work item."""
    payload = "\x00".join([name or "", description_html or ""])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def body_to_html(body):
    """GitHub markdown/plain body -> Plane `description_html`.

    Deliberately conservative: every line is HTML-ESCAPED and wrapped in a
    paragraph. We never pass GitHub-authored markup through to Plane's rich
    text field — the core serializer sanitizes too, but escaping here means
    untrusted remote content is never even offered as markup.
    """
    if not body:
        return "<p></p>"
    lines = body.splitlines() or [body]
    return "".join(f"<p>{escape(line)}</p>" for line in lines)


def html_to_body(description_html):
    """Plane `description_html` -> a plain-text GitHub body.

    Intentionally minimal (tag strip + unescape): Plane rich text has no
    lossless markdown representation, and a half-correct converter would
    produce noisy diffs on every outbound push. Callers treat the result as
    plain text.
    """
    from django.utils.html import strip_tags
    from html import unescape

    if not description_html:
        return ""
    # Paragraph boundaries become newlines before tags are stripped, else all
    # paragraphs collapse onto one line.
    normalized = description_html.replace("</p>", "</p>\n").replace("<br>", "\n").replace("<br/>", "\n")
    return unescape(strip_tags(normalized)).strip()


def map_github_issue(gh_issue):
    """GitHub issue payload -> the Plane work-item field dict.

    Unmapped GitHub concepts (labels, assignees, milestones) are deliberately
    skipped rather than guessed — phase-P3.md risk "field-mapping drift:
    unmapped -> skip + log".
    """
    title = (gh_issue.get("title") or "").strip() or "(untitled GitHub issue)"
    return {
        # Issue.name is max_length=255; a longer GitHub title would 400 the
        # serializer, so truncate rather than drop the whole sync.
        "name": title[:255],
        "description_html": body_to_html(gh_issue.get("body")),
    }


def build_external_id(repo_full_name, number):
    """Stable cross-side identity for a GitHub issue: `owner/repo#123`.

    Repo-qualified because a bare number is only unique within one repo, and
    a Plane project may be mapped from more than one repo over its lifetime.
    """
    return f"{repo_full_name}#{number}"


# ---------------------------------------------------------------------------
# Provenance + echo guard
# ---------------------------------------------------------------------------


def _opposite(side):
    return SOURCE_PLANE if side == SOURCE_GITHUB else SOURCE_GITHUB


def is_reflection(metadata, target_side, source_hash):
    """True when a write toward `target_side` would just replay content that
    originated on `target_side` itself — i.e. an echo.

    `source_hash` is the hash of the content we are about to propagate,
    computed in the ORIGIN side's representation (`github_content_hash` for an
    inbound write to Plane, `plane_content_hash` for an outbound write to
    GitHub).

    Drop iff BOTH hold:
      * the last applied sync on this mirror originated from `target_side`
        (so the target already knows this content), AND
      * the content is byte-identical to what we recorded then.

    The second clause is what lets a genuine later edit on `target_side`
    through: same `source`, different hash -> not a reflection.
    """
    if not metadata:
        return False
    if metadata.get("source") != target_side:
        return False
    stored = metadata.get(f"{_opposite(target_side)}_hash")
    return bool(source_hash) and stored == source_hash


def stamp_provenance(link, source, external_id, github_hash=None, plane_hash=None, extra=None):
    """Record the provenance stamp on the mirror row's `metadata` JSON.

    Stamp shape (phase-P3.md step 2): `source`, `external_id`, `synced_at`,
    plus the per-side content hashes the echo guard compares against. Never
    holds a token or any secret — this row is persisted.
    """
    metadata = dict(link.metadata or {})
    metadata.update(
        {
            "source": source,
            "external_id": external_id,
            "synced_at": timezone.now().isoformat(),
        }
    )
    if github_hash is not None:
        metadata["github_hash"] = github_hash
    if plane_hash is not None:
        metadata["plane_hash"] = plane_hash
    if extra:
        metadata.update(extra)
    link.metadata = metadata
    link.save(update_fields=["metadata"])
    return link


def is_bot_event(installation, payload):
    """Actor-level echo guard: True when this event was produced by our own
    GitHub App bot, so applying it would echo our own outbound write.

    Mirrors the P2 guard in bgtasks/transition_task.py — the bot login is
    configured out-of-band on `GithubInstallation.config["bot_login"]`.
    """
    bot_login = (installation.config or {}).get("bot_login")
    sender_login = (payload.get("sender") or {}).get("login")
    return bool(bot_login) and bot_login == sender_login


# ---------------------------------------------------------------------------
# Mirror row lookup
# ---------------------------------------------------------------------------


def find_mirror(project, external_id):
    """The `WorkItemGithubLink` row mirroring `external_id` inside `project`."""
    from plane.github_ext.models import WorkItemGithubLink

    return (
        WorkItemGithubLink.objects.select_related("issue")
        .filter(project_id=project.id, link_type=MIRROR_LINK_TYPE, external_id=external_id)
        .first()
    )


def find_mirror_for_issue(issue):
    """The mirror row for a Plane work item, or None when it is not mirrored."""
    from plane.github_ext.models import WorkItemGithubLink

    return WorkItemGithubLink.objects.filter(issue_id=issue.id, link_type=MIRROR_LINK_TYPE).first()


def upsert_mirror(issue, project, external_id, url):
    """Create-or-fetch the mirror row (idempotent on redelivery via the P0
    `unique(issue, link_type, external_id)` constraint) and mirror it into the
    core Links panel.

    The `IssueLink` write is the same display-only mirror P1 established in
    services/link_writer.py: a link row is not a work-item state mutation, so
    the trap #4 "raw ORM skips activity" concern does not apply to it. The
    work item itself is NEVER written this way — see `create_work_item` /
    `update_work_item` below.
    """
    from plane.db.models import IssueLink

    from plane.github_ext.models import WorkItemGithubLink

    link, _created = WorkItemGithubLink.objects.get_or_create(
        issue_id=issue.id,
        link_type=MIRROR_LINK_TYPE,
        external_id=external_id,
        defaults={"project_id": project.id, "url": url, "metadata": {}},
    )
    if url:
        IssueLink.objects.get_or_create(
            issue_id=issue.id,
            url=url,
            defaults={
                "project_id": project.id,
                "title": f"GitHub issue: {external_id}",
                "metadata": {"external_id": external_id},
            },
        )
    return link


def resolve_state_for_github_state(project, github_state):
    """Map a GitHub issue state to a Plane `State`, or None to skip.

    `closed` -> first completed-group state; `open` -> first backlog-group
    state, falling back to unstarted then started. Returns None when the
    project has no suitable state — the caller logs and leaves the state
    alone rather than guessing (risk row "field-mapping drift").

    Only consulted for the two actions that actually MEAN a state change
    (`closed` / `reopened`) — see `_sync_issue`. An `edited` event must never
    reset a state a Plane user chose.
    """
    from plane.db.models import State

    groups = ("completed",) if github_state == "closed" else ("backlog", "unstarted", "started")
    for group in groups:
        state = State.objects.filter(project_id=project.id, group=group).order_by("sequence").first()
        if state is not None:
            return state
    return None


# ---------------------------------------------------------------------------
# INBOUND write channel — service-token internal API (trap #4)
# ---------------------------------------------------------------------------
#
# Every Plane-side work-item/comment write goes through Plane's own public API
# view, authenticated with the integration bot's service APIToken, exactly as
# P2's services/state_transition.py `apply_transition` does. A bare
# `Issue.objects.create(...)` would insert the row but SILENTLY skip
# IssueActivity, notifications, and the outbound webhook — those live in the
# viewset, not in save().


def _dispatch(view_cls, method, path, data, service_token, http_method_names, **view_kwargs):
    """Run a Plane API view in-process with the service token.

    APIRequestFactory executes the exact same view code as a real HTTP call
    (firing every side effect) without a self-network-hop — the realization of
    "service-token internal API call" P2 established.
    """
    from rest_framework.test import APIRequestFactory

    factory = APIRequestFactory()
    request = getattr(factory, method)(path, data, format="json", HTTP_X_API_KEY=service_token)
    view = view_cls.as_view(http_method_names=http_method_names)
    response = view(request, **view_kwargs)
    if hasattr(response, "render"):
        response.render()
    return response


def _issue_collection_path(slug, project_id):
    return f"/api/v1/workspaces/{slug}/projects/{project_id}/issues/"


def create_work_item(project, service_token, fields, external_id):
    """Create a Plane work item from GitHub via the service-token API.

    Returns the created (or already-existing) `Issue`, or None on failure.
    A 409 means the external pair already exists — the API hands back the id,
    which we treat as success so webhook redelivery is idempotent.
    """
    from plane.api.views.issue import IssueListCreateAPIEndpoint
    from plane.db.models import Issue

    if not service_token:
        return None

    slug = project.workspace.slug
    data = dict(fields)
    data.update({"external_source": EXTERNAL_SOURCE, "external_id": external_id})

    response = _dispatch(
        IssueListCreateAPIEndpoint,
        "post",
        _issue_collection_path(slug, project.id),
        data,
        service_token,
        ["get", "post"],
        slug=slug,
        project_id=str(project.id),
    )

    if response.status_code in (200, 201, 409):
        issue_id = (getattr(response, "data", None) or {}).get("id")
        if issue_id:
            return Issue.objects.filter(pk=issue_id).first()

    logger.warning(
        "create_work_item: external_id=%s project=%s failed (HTTP %s)",
        external_id,
        project.identifier,
        response.status_code,
    )
    return None


def update_work_item(issue, service_token, fields):
    """PATCH a mirrored work item via the service-token API. Returns the
    HTTP status code (200 on success), or None when there is nothing to do."""
    from plane.api.views.issue import IssueDetailAPIEndpoint

    if not service_token or not fields:
        return None

    slug = issue.workspace.slug
    response = _dispatch(
        IssueDetailAPIEndpoint,
        "patch",
        f"/api/v1/workspaces/{slug}/projects/{issue.project_id}/issues/{issue.id}/",
        fields,
        service_token,
        ["get", "patch", "delete"],
        slug=slug,
        project_id=str(issue.project_id),
        pk=str(issue.id),
    )
    if response.status_code != 200:
        logger.warning(
            "update_work_item: issue=%s failed (HTTP %s)",
            issue.id,
            response.status_code,
        )
    return response.status_code


def create_work_item_comment(issue, service_token, comment_html, external_id):
    """Create a work-item comment via the service-token API.

    The comment carries `external_source="github"` so (a) redelivery 409s
    instead of duplicating, and (b) the outbound path can recognise it as
    GitHub-originated and refuse to push it back (`should_push_comment`).
    """
    from plane.api.views.issue import IssueCommentListCreateAPIEndpoint
    from plane.db.models import IssueComment

    if not service_token:
        return None

    slug = issue.workspace.slug
    response = _dispatch(
        IssueCommentListCreateAPIEndpoint,
        "post",
        f"/api/v1/workspaces/{slug}/projects/{issue.project_id}/issues/{issue.id}/comments/",
        {
            "comment_html": comment_html,
            "external_source": EXTERNAL_SOURCE,
            "external_id": external_id,
        },
        service_token,
        ["get", "post"],
        slug=slug,
        project_id=str(issue.project_id),
        issue_id=str(issue.id),
    )

    if response.status_code in (200, 201, 409):
        comment_id = (getattr(response, "data", None) or {}).get("id")
        if comment_id:
            return IssueComment.objects.filter(pk=comment_id).first()

    logger.warning(
        "create_work_item_comment: external_id=%s issue=%s failed (HTTP %s)",
        external_id,
        issue.id,
        response.status_code,
    )
    return None


# ---------------------------------------------------------------------------
# OUTBOUND write channel — installation-token GitHub REST
# ---------------------------------------------------------------------------
#
# Token discipline (phase-P3.md risk "installation-token leak", plan §7):
#   * App JWT is minted per call from env secrets, TTL <= 10 min.
#   * The installation access token is fetched fresh per outbound call and
#     lives only in a local variable — never written to a model, never cached,
#     never put in a Celery kwarg, never logged (failures log STATUS ONLY).


def _app_jwt():
    """Mint a short-lived GitHub App JWT from env-held secrets.

    Returns None (caller skips, never raises) when the App is not configured
    — the credentials live in `plane-deploy` env, never in this repo.
    """
    import jwt

    app_id = os.environ.get("GITHUB_APP_ID")
    private_key = os.environ.get("GITHUB_APP_PRIVATE_KEY")
    if not app_id or not private_key:
        logger.info("_app_jwt: GITHUB_APP_ID/GITHUB_APP_PRIVATE_KEY unset - outbound disabled")
        return None

    # Env vars commonly carry the PEM with literal \n escapes.
    private_key = private_key.replace("\\n", "\n")
    now = int(time.time())
    try:
        return jwt.encode(
            {"iat": now - 60, "exp": now + _APP_JWT_TTL_SECONDS, "iss": app_id},
            private_key,
            algorithm="RS256",
        )
    except Exception:
        # Never log the exception payload — a PyJWT key error can echo key
        # material into the log line.
        logger.warning("_app_jwt: failed to sign App JWT (bad private key?)")
        return None


def mint_installation_token(installation):
    """Exchange the App JWT for a fresh installation access token.

    Returns the token string or None. Deliberately NOT cached: GitHub tokens
    expire in ~1h and the plan requires they never be persisted beyond their
    TTL — the simplest way to honour that is to never hold one past the call
    that uses it.
    """
    import requests

    assertion = _app_jwt()
    if not assertion:
        return None

    url = f"{GITHUB_API_ROOT}/app/installations/{installation.installation_id}/access_tokens"
    try:
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {assertion}",
                "Accept": GITHUB_ACCEPT,
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
            timeout=_HTTP_TIMEOUT,
        )
    except Exception:
        logger.warning("mint_installation_token: request failed for installation=%s", installation.installation_id)
        return None

    if response.status_code != 201:
        # Status only — the response body of a failed token exchange can
        # contain the assertion back.
        logger.warning(
            "mint_installation_token: installation=%s HTTP %s",
            installation.installation_id,
            response.status_code,
        )
        return None

    return (response.json() or {}).get("token")


def patch_github_issue(token, repo_full_name, number, title, body):
    """PATCH an existing GitHub issue with the installation token.

    Returns the HTTP status code, or None when the call could not be made.
    """
    import requests

    if not token:
        return None

    url = f"{GITHUB_API_ROOT}/repos/{repo_full_name}/issues/{number}"
    try:
        response = requests.patch(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": GITHUB_ACCEPT,
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
            json={"title": title, "body": body},
            timeout=_HTTP_TIMEOUT,
        )
    except Exception:
        logger.warning("patch_github_issue: request failed for %s#%s", repo_full_name, number)
        return None

    if response.status_code != 200:
        logger.warning("patch_github_issue: %s#%s HTTP %s", repo_full_name, number, response.status_code)
    return response.status_code


def should_push_comment(comment):
    """Outbound reflection guard for comments.

    A comment we created FROM a GitHub comment carries
    `external_source="github"`; pushing it back would recreate it on GitHub
    and produce an unbounded comment loop. Only Plane-authored comments are
    eligible for outbound.
    """
    return (comment.external_source or "") != EXTERNAL_SOURCE
