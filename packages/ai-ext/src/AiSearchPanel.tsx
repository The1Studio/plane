// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
//
// SP2 AI search panel — minimal functional component.
// Rendered by the /[workspaceSlug]/ai/search route (extended.ts).

import React, { FormEvent, useState } from "react";
import { aiSearch, type SearchResponse } from "./api";

interface Props {
  workspaceSlug: string;
}

export function AiSearchPanel({ workspaceSlug }: Props) {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await aiSearch(workspaceSlug, query);
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ padding: "1.5rem", maxWidth: "48rem", margin: "0 auto" }}>
      <h1 style={{ marginBottom: "1rem", fontSize: "1.5rem", fontWeight: 600 }}>
        AI Smart Search
      </h1>
      <form onSubmit={handleSubmit} style={{ display: "flex", gap: "0.5rem" }}>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ask anything about your projects…"
          style={{
            flex: 1,
            padding: "0.5rem 0.75rem",
            border: "1px solid #d1d5db",
            borderRadius: "0.375rem",
          }}
        />
        <button
          type="submit"
          disabled={loading}
          style={{
            padding: "0.5rem 1rem",
            background: "#2563eb",
            color: "#fff",
            border: "none",
            borderRadius: "0.375rem",
            cursor: loading ? "not-allowed" : "pointer",
          }}
        >
          {loading ? "Searching…" : "Search"}
        </button>
      </form>

      {error && (
        <p style={{ color: "#dc2626", marginTop: "0.75rem" }}>Error: {error}</p>
      )}

      {result && (
        <div style={{ marginTop: "1.5rem" }}>
          <h2 style={{ fontWeight: 600, marginBottom: "0.5rem" }}>Answer</h2>
          <p style={{ whiteSpace: "pre-wrap" }}>{result.answer}</p>
          {result.citations.length > 0 && (
            <div style={{ marginTop: "0.75rem" }}>
              <h3 style={{ fontWeight: 600, fontSize: "0.875rem" }}>Sources</h3>
              <ul style={{ listStyle: "disc", paddingLeft: "1.25rem" }}>
                {result.citations.map((c) => (
                  <li key={c.id} style={{ fontSize: "0.875rem", color: "#4b5563" }}>
                    {c.entity_type}: {c.id}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
