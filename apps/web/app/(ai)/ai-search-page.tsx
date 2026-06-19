// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
//
// SP2 — AI search route page (apps/web route file).
// Imported by extended.ts; renders the @plane/ai-ext AiSearchPanel.

import { AiSearchPanel } from "@plane/ai-ext";
import { useParams } from "react-router";

export default function AiSearchPage() {
  const { workspaceSlug = "" } = useParams();
  return <AiSearchPanel workspaceSlug={workspaceSlug} />;
}
