# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# SP2 P5 — Eval harness task (egress-aware; runs on opted-in workspaces only).
# Uses Opus 4.8 as a different-model grader.
# Triage: field-by-field code grading + Opus grader.
# RAG: precision@k + citation-faithfulness + cross-project-leak red-team.

import logging

from celery import shared_task

from plane.ai_ext.clients.anthropic_client import MODEL_OPUS, AnthropicClient, wrap_untrusted

logger = logging.getLogger("plane.ai_ext")


@shared_task(
    name="plane.ai_ext.bgtasks.eval_task.run_rag_eval",
    bind=True,
    max_retries=0,
)
def run_rag_eval(self, workspace_id: str, golden_set: list[dict]):
    """Evaluate RAG precision@k and citation faithfulness.

    golden_set: [{query, relevant_entity_ids: [uuid, …]}, …]
    Uses Opus 4.8 as a different-model grader.
    Results are logged; no user-visible output.
    """
    from plane.ai_ext.gate import gate_or_raise, AiGateError

    try:
        gate_or_raise(workspace_id)
    except AiGateError as exc:
        logger.info("run_rag_eval: gate blocked — %s", exc.message)
        return

    client = AnthropicClient(workspace_id=workspace_id)
    metrics = {"precision_at_k": [], "citation_faithfulness": []}

    for item in golden_set:
        query = item["query"]
        relevant_ids = set(item.get("relevant_entity_ids", []))

        # Import search function (live-filtered retrieval).
        from plane.ai_ext.views.search import (
            _ann_search,
            _tsv_search,
            _rrf_fuse,
        )
        from plane.ai_ext.clients.bge_client import BgeClient

        bge = BgeClient()
        try:
            embed_result = bge.embed_one(query)
        finally:
            bge.close()

        # NOTE: In eval we use all workspace entity ids (no user context).
        all_entity_ids = set(
            str(e)
            for e in __import__("plane.ai_ext.models", fromlist=["AiEmbedding"])
            .AiEmbedding.objects.filter(workspace_id=workspace_id)
            .values_list("entity_id", flat=True)
        )

        ann = _ann_search(embed_result.embedding, workspace_id, all_entity_ids, k=10)
        tsv = _tsv_search(query, workspace_id, all_entity_ids, k=10)
        fused = _rrf_fuse(ann, tsv)[:10]

        retrieved_ids = {r["entity_id"] for r in fused}
        if relevant_ids:
            precision = len(retrieved_ids & {str(r) for r in relevant_ids}) / len(retrieved_ids) if retrieved_ids else 0
            metrics["precision_at_k"].append(precision)

        # Grader: ask Opus whether the retrieved set is faithful.
        if fused:
            grader_prompt = (
                f"Query: {query}\n"
                f"Retrieved entity ids: {list(retrieved_ids)}\n"
                f"Relevant entity ids: {list(relevant_ids)}\n"
                "Rate citation faithfulness 0-10 (10=all retrieved are relevant)."
            )
            try:
                score_text = client.generate(
                    model=MODEL_OPUS,
                    system="You are a strict retrieval evaluator.",
                    user_message=wrap_untrusted(grader_prompt),
                    max_tokens=64,
                )
                # Extract first number from output.
                import re
                nums = re.findall(r"\b\d+\b", score_text)
                if nums:
                    metrics["citation_faithfulness"].append(int(nums[0]))
            except Exception as exc:
                logger.warning("run_rag_eval: grader error — %s", exc)

    if metrics["precision_at_k"]:
        avg_p = sum(metrics["precision_at_k"]) / len(metrics["precision_at_k"])
        avg_f = (
            sum(metrics["citation_faithfulness"]) / len(metrics["citation_faithfulness"])
            if metrics["citation_faithfulness"] else 0
        )
        logger.info(
            "run_rag_eval: precision@k=%.3f, citation_faithfulness=%.1f/10",
            avg_p, avg_f,
        )
