"""Shared persisted-stage vocabulary for domain and delivery reconciliation."""

CASE_STAGES = (
    "started",
    "dna_complete",
    "facts_complete",
    "risks_complete",
    "draft_complete",
    "audited",
    "finalized",
)
CASE_OPERATIONS = {
    "start": "started",
    "run_document_dna": "dna_complete",
    "run_facts_obligations": "facts_complete",
    "run_risk_prioritisation": "risks_complete",
    "run_draft_action_pack": "draft_complete",
    "run_mandatory_audit": "audited",
    "finalize_case": "finalized",
}
