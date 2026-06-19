// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
//
// Route page component for /:workspaceSlug/ai/search.
// Uses React Router v7 useParams to get workspaceSlug.

import React from "react";
import { AiSearchPanel } from "./AiSearchPanel";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Params = Record<string, string | undefined>;

interface Props {
  params?: Params;
}

export default function AiSearchPage({ params }: Props) {
  const workspaceSlug = params?.workspaceSlug ?? "";
  if (!workspaceSlug) return <p>Workspace not found.</p>;
  return <AiSearchPanel workspaceSlug={workspaceSlug} />;
}
