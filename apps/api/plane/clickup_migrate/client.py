# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# The1Studio SP1 — ClickUp v2 API client (Phase 2 extractor).
#
# Rate limit: ~90 req/min (hard cap 100); concurrency ≤2.
# Auth: "Authorization: <pk_token>" (no Bearer prefix).
# Paging: page=0..N; terminate on last_page==true OR <100 rows returned.
# Comments: start_id cursor paging (NOT page= offset).

import logging
import time
from threading import Semaphore
from typing import Generator, Optional

import requests

logger = logging.getLogger(__name__)

_RATE_LIMIT_PER_MIN = 90  # conservative margin below ClickUp's 100
_CONCURRENCY_CAP = 2

# Module-level semaphore to cap concurrent in-flight requests.
_semaphore = Semaphore(_CONCURRENCY_CAP)

# Minimum inter-request gap in seconds to honour ~90 req/min.
_MIN_GAP_S = 60.0 / _RATE_LIMIT_PER_MIN  # ≈ 0.67 s


class ClickUpRateLimitError(Exception):
    """Raised when ClickUp returns 429 after exhausting backoff."""
    pass


class ClickUpAPIError(Exception):
    """Raised for non-recoverable ClickUp API errors."""

    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"ClickUp API {status_code}: {body[:200]}")


class ClickUpClient:
    """Thin ClickUp v2 REST client with rate-limit handling.

    All methods are synchronous. The caller is responsible for running
    parallel requests via threads (concurrency ≤2 enforced via _semaphore).
    """

    BASE_URL = "https://api.clickup.com/api/v2"
    PAGE_SIZE = 100  # ClickUp default; terminate on < this OR last_page

    def __init__(self, token: str, team_id: str):
        self._token = token
        self._team_id = team_id
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": token,  # ClickUp v2: NO "Bearer" prefix
            "Content-Type": "application/json",
        })
        self._last_request_at: float = 0.0

    # ─────────────────────────────────────────────────────────────────
    # Internal request primitive
    # ─────────────────────────────────────────────────────────────────

    def _get(self, path: str, params: Optional[dict] = None, _retry: int = 3) -> dict:
        """GET with rate-limit throttle, 429 backoff, and concurrency cap."""
        url = f"{self.BASE_URL}{path}"
        with _semaphore:
            # Enforce minimum inter-request gap.
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < _MIN_GAP_S:
                time.sleep(_MIN_GAP_S - elapsed)

            resp = self._session.get(url, params=params or {}, timeout=30)
            self._last_request_at = time.monotonic()

        if resp.status_code == 429:
            reset_ts = resp.headers.get("X-RateLimit-Reset")
            if reset_ts:
                sleep_until = float(reset_ts) - time.time()
                wait = max(sleep_until, 1.0)
            else:
                wait = 60.0
            logger.warning("ClickUp 429 — sleeping %.1f s", wait)
            time.sleep(wait)
            if _retry > 0:
                return self._get(path, params, _retry=_retry - 1)
            raise ClickUpRateLimitError(f"Rate limit persists after retries: {url}")

        if not resp.ok:
            raise ClickUpAPIError(resp.status_code, resp.text)

        return resp.json()

    # ─────────────────────────────────────────────────────────────────
    # Top-level traversal
    # ─────────────────────────────────────────────────────────────────

    def get_team_members(self) -> list:
        """Return all workspace members (for email → user mapping)."""
        data = self._get(f"/team/{self._team_id}/member")
        return data.get("members", [])

    def get_spaces(self, archived: bool = False) -> list:
        """Return all Spaces in the workspace."""
        data = self._get(f"/team/{self._team_id}/space", {"archived": str(archived).lower()})
        return data.get("spaces", [])

    def get_folders(self, space_id: str, archived: bool = False) -> list:
        data = self._get(f"/space/{space_id}/folder", {"archived": str(archived).lower()})
        return data.get("folders", [])

    def get_folderless_lists(self, space_id: str, archived: bool = False) -> list:
        """Return Lists not inside any Folder (top-level space lists)."""
        data = self._get(f"/space/{space_id}/list", {"archived": str(archived).lower()})
        return data.get("lists", [])

    def get_lists_in_folder(self, folder_id: str, archived: bool = False) -> list:
        data = self._get(f"/folder/{folder_id}/list", {"archived": str(archived).lower()})
        return data.get("lists", [])

    def get_field_defs(self, list_id: str) -> list:
        """Return custom field definitions for a List."""
        try:
            data = self._get(f"/list/{list_id}/field")
            return data.get("fields", [])
        except ClickUpAPIError as exc:
            # Some lists have no custom fields and return 404.
            if exc.status_code == 404:
                return []
            raise

    # ─────────────────────────────────────────────────────────────────
    # Task extraction (pages)
    # ─────────────────────────────────────────────────────────────────

    def iter_tasks(
        self,
        list_id: str,
        archived: bool = False,
        start_page: int = 0,
    ) -> Generator[list, None, None]:
        """Yield task batches for a single list, one page at a time.

        Caller may checkpoint the page number to resume on restart.

        IMPORTANT: do NOT pass include_timl=true — it would duplicate
        multi-home tasks and corrupt the list→module mapping.
        """
        page = start_page
        while True:
            params = {
                "include_closed": "true",
                "subtasks": "true",
                "include_markdown_description": "true",
                "archived": str(archived).lower(),
                "page": page,
            }
            data = self._get(f"/list/{list_id}/task", params)
            tasks = data.get("tasks", [])
            last_page = data.get("last_page", False)

            yield tasks, page

            # Terminate on explicit last_page flag OR a short page.
            if last_page or len(tasks) < self.PAGE_SIZE:
                break
            page += 1

    # ─────────────────────────────────────────────────────────────────
    # Comment extraction (cursor paging)
    # ─────────────────────────────────────────────────────────────────

    def iter_comments(
        self,
        task_id: str,
        start_id: Optional[str] = None,
    ) -> Generator[tuple, None, None]:
        """Yield (comments_batch, next_start_id) pairs for a task.

        ClickUp comments use start/start_id cursor paging, not page=.
        Persist next_start_id in MigrationCursor.cursor_token to resume.
        Yield includes the start_id that produced this batch so callers
        can checkpoint before each request.
        """
        current_start = start_id
        while True:
            params: dict = {}
            if current_start:
                params["start_id"] = current_start

            data = self._get(f"/task/{task_id}/comment", params)
            comments = data.get("comments", [])
            next_cursor = data.get("next_id")  # ClickUp returns next_id when more pages exist

            yield comments, current_start, next_cursor

            if not next_cursor or not comments:
                break
            current_start = next_cursor

    # ─────────────────────────────────────────────────────────────────
    # Attachment auth spike helper
    # ─────────────────────────────────────────────────────────────────

    def probe_attachment_url(self, url: str) -> dict:
        """Documented spike: determine whether attachment URLs need the auth header.

        Downloads up to 16 bytes with and without the Authorization header.
        Returns a dict with keys:
          with_auth_status    — HTTP status code with auth header
          without_auth_status — HTTP status code without auth header
          recommendation      — 'use_auth' | 'no_auth_needed' | 'investigate'

        Callers should run this once per migration on a representative attachment
        before committing to the download strategy (plan P2 spike requirement).
        """
        result: dict = {}
        headers_with = {"Authorization": self._token, "Range": "bytes=0-15"}
        headers_without = {"Range": "bytes=0-15"}

        try:
            r_auth = requests.get(url, headers=headers_with, timeout=10)
            result["with_auth_status"] = r_auth.status_code
        except Exception as exc:
            result["with_auth_status"] = f"error: {exc}"

        try:
            r_noauth = requests.get(url, headers=headers_without, timeout=10)
            result["without_auth_status"] = r_noauth.status_code
        except Exception as exc:
            result["without_auth_status"] = f"error: {exc}"

        w = result.get("with_auth_status")
        n = result.get("without_auth_status")
        if n in (200, 206):
            result["recommendation"] = "no_auth_needed"
        elif w in (200, 206) and n not in (200, 206):
            result["recommendation"] = "use_auth"
        else:
            result["recommendation"] = "investigate"

        return result

    def download_attachment(self, url: str, use_auth: bool = True) -> requests.Response:
        """Stream-download an attachment, honouring the auth-spike result."""
        headers = {}
        if use_auth:
            headers["Authorization"] = self._token
        resp = self._session.get(url, headers=headers, stream=True, timeout=60)
        resp.raise_for_status()
        return resp
