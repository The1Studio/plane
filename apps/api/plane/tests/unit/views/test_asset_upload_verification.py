# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from types import SimpleNamespace

import pytest

from plane.app.views.asset.v2 import get_verified_upload_metadata


@pytest.mark.unit
class TestGetVerifiedUploadMetadata:
    """get_verified_upload_metadata must only bless storage objects that exist with content."""

    def _asset(self):
        return SimpleNamespace(asset=SimpleNamespace(name="workspace-id/abc123-image.png"))

    class _Storage:
        def __init__(self, metadata=None, raise_error=False):
            self._metadata = metadata
            self._raise_error = raise_error
            self.called_with = None

        def get_object_metadata(self, object_name):
            self.called_with = object_name
            if self._raise_error:
                raise RuntimeError("storage unavailable")
            return self._metadata

    def test_returns_metadata_when_object_has_content(self):
        storage = self._Storage({"ContentLength": 697741, "ContentType": "image/png"})
        metadata = get_verified_upload_metadata(storage, self._asset())
        assert metadata == {"ContentLength": 697741, "ContentType": "image/png"}
        assert storage.called_with == "workspace-id/abc123-image.png"

    def test_rejects_empty_object(self):
        # regression: a finalized row pointing at a 0-byte object is exactly the
        # production incident this gate prevents
        assert get_verified_upload_metadata(self._Storage({"ContentLength": 0}), self._asset()) is None

    def test_rejects_missing_object(self):
        assert get_verified_upload_metadata(self._Storage(None), self._asset()) is None

    def test_rejects_when_storage_raises(self):
        assert get_verified_upload_metadata(self._Storage(raise_error=True), self._asset()) is None
