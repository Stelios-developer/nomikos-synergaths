"""Evidence-first document-intelligence agents for the n8n workflow.

Each stage reads and writes a workspace-scoped case file. The agents only
receive explicit document evidence, and every fact, deadline, risk, decision,
or proposed action must point to one of the case evidence IDs.
"""
import json
import re
import uuid

from db.vector_store import get_collection
from services import case_store
from services.auditor import _extract_verdict_list
from services.ingestion import extract_pages, is_scanned
from services.llm import complete
from services.observability import traced_span
from services.pdf_storage import pdf_path
from services.workspace_lock import scoped_operation

MAX_EVIDENCE_CHUNKS = 48
MAX_EXCERPT_CHARS = 700
MAX_ITEMS_PER_SECTION = 20


class CaseStageError(ValueError):
    """Raised when a workflow calls an agent before its required predecessor."""


def _load_document_chunks(filename: str, workspace_id: str) -> list[dict]:
    rows = get_collection().get(
        workspace_id=workspace_id, filename=filename,
        include=["documents", "metadatas"],
    )
    documents = rows.get("documents") or []
    metadatas = rows.get("metadatas") or []
    chunks = []
    for text, metadata in zip(documents, metadatas):
        metadata = metadata or {}
        chunks.append({
            "text": text or "",
            "filename": metadata.get("filename", filename),
            "page_number": int(metadata.get("page_number", 0) or 0),
            "chunk_index": int(metadata.get("chunk_index", 0) or 0),
            "method": metadata.get("method", "unknown"),
            "upload_date": metadata.get("upload_date"),
        })
    return sorted(chunks, key=lambda chunk: (chunk["page_number"], chunk["chunk_index"]))


def _sample_chunks(chunks: list[dict]) -> list[dict]:
    if len(chunks) <= MAX_EVIDENCE_CHUNKS:
        return chunks
    indexes = {
        round(index * (len(chunks) - 1) / (MAX_EVIDENCE_CHUNKS - 1))
        for index in range(MAX_EVIDENCE_CHUNKS)
    }
    return [chunk for index, chunk in enumerate(chunks) if index in indexes]


def _build_evidence(chunks: list[dict]) -> list[dict]:
    evidence = []
    for index, chunk in enumerate(_sample_chunks(chunks), start=1):
        evidence.append({
            "id": f"C{index}",
            "filename": chunk["filename"],
            "page": chunk["page_number"],
            "chunk_index": chunk["chunk_index"],
            "excerpt": chunk["text"][:MAX_EXCERPT_CHARS],
        })
    return evidence


def _evidence_context(evidence: list[dict]) -> str:
    return "\n\n".join(
        f"[{item['id']}] page {item['page']}: {item['excerpt']}"
        for item in evidence
    )


def _parse_json_object(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", stripped, flags=re.IGNORECASE)
    decoder = json.JSONDecoder()

    # Providers occasionally preface an otherwise valid object with a short
    # sentence. raw_decode lets us recover that object without relying on a
    # greedy regex (which can accidentally include prose after the JSON).
    for match in re.finditer(r"\{", stripped):
        try:
            parsed, _ = decoder.raw_decode(stripped[match.start():])
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _json_completion(prompt: str, max_tokens: int = 1600) -> tuple[dict, str | None]:
    try:
        first_response = complete(prompt, max_tokens=max_tokens)
        result = _parse_json_object(first_response)
        if result:
            return result, None

        # One focused retry is safer than silently accepting malformed output.
        # It retains the original evidence-first prompt and makes the response
        # contract unambiguous for models that add prose or markdown by default.
        retry_prompt = (
            f"{prompt}\n\n"
            "IMPORTANT RETRY: Your previous response could not be parsed. "
            "Return exactly one valid JSON object and nothing else — no markdown, "
            "no explanation, and no text before or after the JSON."
        )
        result = _parse_json_object(complete(retry_prompt, max_tokens=max_tokens))
        if result:
            return result, None

        return {}, "The model did not return valid structured JSON after a retry."
    except Exception:
        return {}, "Structured analysis was unavailable. Please retry or review the document manually."


def _strings(value, limit: int = MAX_ITEMS_PER_SECTION) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:500] for item in value if str(item).strip()][:limit]


def _text(value, fallback: str = "", limit: int = 1200) -> str:
    return str(value).strip()[:limit] if value is not None else fallback


def _citation_ids(value, allowed: set[str]) -> list[str]:
    candidates = value if isinstance(value, list) else [value]
    result = []
    for candidate in candidates:
        citation_id = str(candidate).strip()
        if citation_id in allowed and citation_id not in result:
            result.append(citation_id)
    return result


def _confidence(value) -> str:
    normalised = str(value or "medium").lower()
    return normalised if normalised in {"high", "medium", "low"} else "medium"


def _priority(value) -> str:
    normalised = str(value or "medium").lower()
    return normalised if normalised in {"critical", "high", "medium", "low"} else "medium"


def _get_case(case_id: str, workspace_id: str) -> dict:
    case = case_store.get_case(case_id, workspace_id)
    if case is None:
        raise ValueError("Document case was not found in this workspace.")
    return case


def get_case(case_id: str, workspace_id: str) -> dict:
    """Loads a case while enforcing its workspace boundary."""
    return _get_case(case_id, workspace_id)


def _require_stage(case: dict, expected: str):
    if case["stage"] != expected:
        raise CaseStageError(
            f"This stage requires '{expected}', but case '{case['case_id']}' is at '{case['stage']}'."
        )


def _save(case: dict, stage: str, status: str = "in_progress") -> dict:
    case["stage"] = stage
    case["status"] = status
    return case_store.save_case(case)


@scoped_operation
def start_case(filename: str, workspace_id: str, *, case_id=None) -> dict:
    if case_id:
        previous = case_store.get_case(case_id,workspace_id)
        if previous:
            if previous['document']['filename']!=filename:
                raise CaseStageError('The admitted case does not match this document.')
            return previous
    chunks = _load_document_chunks(filename, workspace_id)
    if not chunks:
        raise ValueError("The requested PDF was not found in this workspace or contains no indexed text.")

    source_path = pdf_path(filename, session_id=workspace_id)
    pages = []
    if source_path is not None:
        try:
            pages = extract_pages(source_path)
        except Exception:
            pages = []

    method = chunks[0].get("method", "unknown")
    page_count = len(pages) or max(chunk["page_number"] for chunk in chunks)
    text_characters = sum(len(chunk["text"]) for chunk in chunks)
    case = {
        "case_id": case_id or uuid.uuid4().hex,
        "analysis_job_id": case_id,
        "workspace_id": workspace_id,
        "document": {
            "filename": filename,
            "method": method,
            "page_count": page_count,
            "chunk_count": len(chunks),
            "text_characters": text_characters,
            "source_file_available": source_path is not None,
            "ocr_detected": bool(pages and is_scanned(pages)),
        },
        "citations": _build_evidence(chunks),
        "document_profile": {},
        "facts": [],
        "obligations": [],
        "deadlines": [],
        "open_questions": [],
        "risks": [],
        "draft_action_pack": {},
        "audit": {},
        "final_action_pack": {},
        "warnings": [],
        "status": "in_progress",
        "stage": "started",
    }
    return case_store.create_case(case)


def run_document_dna(case_id: str, workspace_id: str) -> dict:
    case = _get_case(case_id, workspace_id)
    if _stage_completed(case, 'dna_complete'):
        return case
    _require_stage(case, "started")
    document = case["document"]
    evidence = case["citations"]
    allowed = {item["id"] for item in evidence}

    quality_reasons = []
    if document["method"] == "ocr" or document["ocr_detected"]:
        quality_reasons.append("The document required OCR; a human should verify critical excerpts.")
    if not document["source_file_available"]:
        quality_reasons.append("The original PDF file is unavailable; only indexed text can be reviewed.")
    if document["text_characters"] < 250:
        quality_reasons.append("Very little text was extracted from the PDF.")
    extraction_quality = "blocked" if document["chunk_count"] == 0 else "needs_review" if quality_reasons else "good"

    prompt = f"""You are the Document DNA and Quality agent. Use only the evidence below.
Return ONLY valid JSON with this shape:
{{
  "document_type": "contract|policy|invoice|report|tax|other",
  "language": "ISO language code or unknown",
  "parties": ["named parties or organisations"],
  "dates": ["explicit dates"],
  "topics": ["up to five topics"],
  "confidentiality": "public|internal|confidential|unknown",
  "summary": "one short source-grounded sentence",
  "confidence": "high|medium|low",
  "citation_ids": ["C1"]
}}
Never invent a party, date, or document type. Cite only IDs that exist.

Evidence:
{_evidence_context(evidence)}"""
    with traced_span("document_case.document_dna"):
        raw, warning = _json_completion(prompt, max_tokens=900)

    profile = {
        "document_type": _text(raw.get("document_type"), "other", 80).lower(),
        "language": _text(raw.get("language"), "unknown", 40).lower(),
        "parties": _strings(raw.get("parties"), 12),
        "dates": _strings(raw.get("dates"), 20),
        "topics": _strings(raw.get("topics"), 8),
        "confidentiality": _text(raw.get("confidentiality"), "unknown", 40).lower(),
        "summary": _text(raw.get("summary"), "Automatic classification requires review.", 800),
        "confidence": _confidence(raw.get("confidence")),
        "citation_ids": _citation_ids(raw.get("citation_ids"), allowed),
        "quality": {
            "extraction_quality": extraction_quality,
            "extraction_method": document["method"],
            "page_count": document["page_count"],
            "chunk_count": document["chunk_count"],
            "review_required": bool(quality_reasons or warning),
            "reasons": quality_reasons + ([warning] if warning else []),
        },
    }
    case["document_profile"] = profile
    if warning:
        case["warnings"].append({"stage": "document_dna", "message": warning})
    return _save(case, "dna_complete")


def _normalise_facts(raw: dict, allowed: set[str]) -> dict:
    facts = []
    for index, item in enumerate(raw.get("facts", []) if isinstance(raw.get("facts"), list) else [], start=1):
        if not isinstance(item, dict):
            continue
        citation_ids = _citation_ids(item.get("citation_ids"), allowed)
        statement = _text(item.get("statement"))
        if statement and citation_ids:
            facts.append({
                "id": f"F{index}",
                "statement": statement,
                "category": _text(item.get("category"), "general", 80),
                "confidence": _confidence(item.get("confidence")),
                "citation_ids": citation_ids,
            })
        if len(facts) >= MAX_ITEMS_PER_SECTION:
            break

    obligations = []
    for index, item in enumerate(raw.get("obligations", []) if isinstance(raw.get("obligations"), list) else [], start=1):
        if not isinstance(item, dict):
            continue
        citation_ids = _citation_ids(item.get("citation_ids"), allowed)
        action = _text(item.get("action"))
        if action and citation_ids:
            obligations.append({
                "id": f"O{index}",
                "owner": _text(item.get("owner"), "Unassigned", 240),
                "action": action,
                "trigger": _text(item.get("trigger"), "", 500),
                "due_date": _text(item.get("due_date"), "", 100) or None,
                "consequence_if_missed": _text(item.get("consequence_if_missed"), "", 600),
                "severity": _priority(item.get("severity")),
                "confidence": _confidence(item.get("confidence")),
                "citation_ids": citation_ids,
            })
        if len(obligations) >= MAX_ITEMS_PER_SECTION:
            break

    deadlines = []
    for index, item in enumerate(raw.get("deadlines", []) if isinstance(raw.get("deadlines"), list) else [], start=1):
        if not isinstance(item, dict):
            continue
        citation_ids = _citation_ids(item.get("citation_ids"), allowed)
        event = _text(item.get("event"))
        date = _text(item.get("date"))
        if event and date and citation_ids:
            deadlines.append({
                "id": f"D{index}",
                "event": event,
                "date": date,
                "owner": _text(item.get("owner"), "Unassigned", 240),
                "status": _text(item.get("status"), "open", 60).lower(),
                "citation_ids": citation_ids,
            })
        if len(deadlines) >= MAX_ITEMS_PER_SECTION:
            break

    return {
        "facts": facts,
        "obligations": obligations,
        "deadlines": deadlines,
        "open_questions": _strings(raw.get("open_questions")),
    }


def run_facts_obligations(case_id: str, workspace_id: str) -> dict:
    case = _get_case(case_id, workspace_id)
    if _stage_completed(case, 'facts_complete'):
        return case
    _require_stage(case, "dna_complete")
    evidence = case["citations"]
    allowed = {item["id"] for item in evidence}
    prompt = f"""You are the Facts, Obligations and Deadlines agent. Use only the evidence below.
Return ONLY valid JSON with this exact top-level shape:
{{
  "facts": [{{"statement":"...","category":"...","confidence":"high|medium|low","citation_ids":["C1"]}}],
  "obligations": [{{"owner":"... or Unassigned","action":"...","trigger":"...","due_date":"explicit date or null","consequence_if_missed":"...","severity":"critical|high|medium|low","confidence":"high|medium|low","citation_ids":["C1"]}}],
  "deadlines": [{{"event":"...","date":"only explicit date/period","owner":"... or Unassigned","status":"open","citation_ids":["C1"]}}],
  "open_questions": ["missing or ambiguous information"]
}}
Never infer an owner or deadline. Omit an item when it has no supporting citation ID.
Document profile: {json.dumps(case['document_profile'], ensure_ascii=False)}

Evidence:
{_evidence_context(evidence)}"""
    with traced_span("document_case.facts_obligations"):
        raw, warning = _json_completion(prompt, max_tokens=2200)
    result = _normalise_facts(raw, allowed)
    case.update(result)
    if warning:
        case["warnings"].append({"stage": "facts_obligations", "message": warning})
    return _save(case, "facts_complete")


def _normalise_risks(raw: dict, allowed: set[str]) -> dict:
    risks = []
    for index, item in enumerate(raw.get("risks", []) if isinstance(raw.get("risks"), list) else [], start=1):
        if not isinstance(item, dict):
            continue
        citation_ids = _citation_ids(item.get("citation_ids"), allowed)
        title = _text(item.get("title"))
        rationale = _text(item.get("rationale"))
        if title and rationale and citation_ids:
            level = _priority(item.get("level"))
            risks.append({
                "id": f"R{index}",
                "title": title,
                "level": level,
                "likelihood": _confidence(item.get("likelihood")),
                "impact": _text(item.get("impact"), "operational", 120),
                "rationale": rationale,
                "mitigation": _text(item.get("mitigation"), "Human review required.", 800),
                "related_obligation_ids": _strings(item.get("related_obligation_ids"), 10),
                "citation_ids": citation_ids,
                "human_review_required": level in {"critical", "high"},
            })
        if len(risks) >= MAX_ITEMS_PER_SECTION:
            break
    overall = _priority(raw.get("overall_risk")) if risks else "low"
    return {"overall_risk": overall, "risks": risks}


def run_risk_prioritisation(case_id: str, workspace_id: str) -> dict:
    case = _get_case(case_id, workspace_id)
    if _stage_completed(case, 'risks_complete'):
        return case
    _require_stage(case, "facts_complete")
    evidence = case["citations"]
    allowed = {item["id"] for item in evidence}
    inputs = {
        "document_profile": case["document_profile"],
        "facts": case["facts"],
        "obligations": case["obligations"],
        "deadlines": case["deadlines"],
    }
    prompt = f"""You are the Risk Prioritisation agent. Use only the structured findings and cited evidence below.
Return ONLY valid JSON:
{{
  "overall_risk":"critical|high|medium|low",
  "risks":[{{
    "title":"...","level":"critical|high|medium|low","likelihood":"high|medium|low",
    "impact":"financial|legal|operational|reputational|other","rationale":"source-grounded reason",
    "mitigation":"safe recommended next step","related_obligation_ids":["O1"],"citation_ids":["C1"]
  }}]
}}
Do not create a risk without a cited factual reason. A high or critical risk must be conservative.
Findings: {json.dumps(inputs, ensure_ascii=False)}

Evidence:
{_evidence_context(evidence)}"""
    with traced_span("document_case.risk_prioritisation"):
        raw, warning = _json_completion(prompt, max_tokens=1800)
    result = _normalise_risks(raw, allowed)
    case.update(result)
    if warning:
        case["warnings"].append({"stage": "risk_prioritisation", "message": warning})
    return _save(case, "risks_complete")


def _draft_actions(case: dict) -> list[dict]:
    actions = []
    deadline_by_owner = {deadline["owner"]: deadline for deadline in case["deadlines"] if deadline["owner"] != "Unassigned"}
    for index, obligation in enumerate(case["obligations"], start=1):
        related_deadline = deadline_by_owner.get(obligation["owner"])
        actions.append({
            "id": f"A{index}",
            "title": obligation["action"],
            "priority": obligation["severity"],
            "suggested_owner": obligation["owner"],
            "due_date": obligation["due_date"] or (related_deadline["date"] if related_deadline else None),
            "source_obligation_id": obligation["id"],
            "approval_required": True,
            "citation_ids": obligation["citation_ids"],
        })
    return actions[:MAX_ITEMS_PER_SECTION]


def _normalise_decisions(raw: dict, allowed: set[str]) -> list[dict]:
    decisions = []
    for index, item in enumerate(raw.get("decisions_required", []) if isinstance(raw.get("decisions_required"), list) else [], start=1):
        if isinstance(item, str):
            continue
        if not isinstance(item, dict):
            continue
        text = _text(item.get("decision"))
        citation_ids = _citation_ids(item.get("citation_ids"), allowed)
        if text and citation_ids:
            decisions.append({"id": f"Q{index}", "decision": text, "citation_ids": citation_ids})
    return decisions[:MAX_ITEMS_PER_SECTION]


def _build_audit_claims(case: dict, executive_summary: str) -> list[dict]:
    claims = []
    summary_citations = case["document_profile"].get("citation_ids", [])
    if not summary_citations:
        for section in (case["facts"], case["deadlines"], case["risks"]):
            if section and section[0].get("citation_ids"):
                summary_citations = section[0]["citation_ids"]
                break
    for sentence in re.split(r"(?<=[.!?])\s+", executive_summary.strip()):
        sentence = sentence.strip()
        if sentence:
            claims.append({"text": sentence, "category": "summary", "citation_ids": summary_citations})
    for fact in case["facts"][:8]:
        claims.append({"text": fact["statement"], "category": "fact", "citation_ids": fact["citation_ids"]})
    for deadline in case["deadlines"][:8]:
        claims.append({
            "text": f"{deadline['event']} is due on {deadline['date']}.",
            "category": "deadline",
            "citation_ids": deadline["citation_ids"],
        })
    for risk in case["risks"][:8]:
        claims.append({"text": risk["rationale"], "category": "risk", "citation_ids": risk["citation_ids"]})
    return claims[:30]


def run_draft_action_pack(case_id: str, workspace_id: str) -> dict:
    case = _get_case(case_id, workspace_id)
    if _stage_completed(case, 'draft_complete'):
        return case
    _require_stage(case, "risks_complete")
    evidence = case["citations"]
    allowed = {item["id"] for item in evidence}
    inputs = {
        "document_profile": case["document_profile"],
        "facts": case["facts"],
        "obligations": case["obligations"],
        "deadlines": case["deadlines"],
        "overall_risk": case["overall_risk"],
        "risks": case["risks"],
    }
    prompt = f"""You are the Decision Brief agent. Turn the verified structured findings below into a concise executive brief.
Return ONLY JSON:
{{
  "executive_summary":"maximum five factual sentences, no unsupported claims",
  "decisions_required":[{{"decision":"...","citation_ids":["C1"]}}],
  "open_questions":["..."]
}}
Every decision must cite evidence. Do not promise external actions or give legal advice.
Findings: {json.dumps(inputs, ensure_ascii=False)}
Evidence IDs available: {", ".join(sorted(allowed))}"""
    with traced_span("document_case.decision_brief"):
        raw, warning = _json_completion(prompt, max_tokens=1400)
    summary = _text(raw.get("executive_summary"), "Automatic decision brief requires human review.", 2400)
    draft = {
        "executive_summary": summary,
        "decisions_required": _normalise_decisions(raw, allowed),
        "open_questions": _strings(raw.get("open_questions")),
        "action_items": _draft_actions(case),
        "deadline_calendar": case["deadlines"],
        "risk_register": case["risks"],
        "human_review_required": True,
    }
    draft["audit_claims"] = _build_audit_claims(case, summary)
    case["draft_action_pack"] = draft
    if warning:
        case["warnings"].append({"stage": "decision_brief", "message": warning})
    return _save(case, "draft_complete")


def _strict_audit(claims: list[dict], evidence: list[dict]) -> dict:
    if not claims:
        return {
            "verification_available": False,
            "passed": False,
            "sentences": [],
            "summary": {"supported": 0, "unsupported": 0, "unverifiable": 0},
            "reason": "There were no claims to verify.",
        }
    if not evidence:
        return {
            "verification_available": False,
            "passed": False,
            "sentences": [
                {**claim, "supported": False, "reason": "No document evidence was available."}
                for claim in claims
            ],
            "summary": {"supported": 0, "unsupported": 0, "unverifiable": len(claims)},
            "reason": "No document evidence was available.",
        }

    context = _evidence_context(evidence)
    numbered_claims = "\n".join(f"{index}. {claim['text']}" for index, claim in enumerate(claims, start=1))
    prompt = f"""You are a strict evidence auditor. Verify each claim using only the document excerpts.
Return ONLY a JSON array with exactly {len(claims)} objects, in the same order:
[{{"supported": true, "reason": "short evidence-based reason"}}]
Mark supported=false if the claim is not explicitly supported. Do not use outside knowledge.

Document excerpts:
{context}

Claims:
{numbered_claims}"""
    try:
        response = complete(prompt, max_tokens=1600)
        verdicts = _extract_verdict_list(response, expected_length=len(claims))
    except Exception:
        verdicts = None
        unavailable_reason = "Verification was unavailable. The case requires human review."
    else:
        unavailable_reason = "The auditor did not return valid structured verdicts."

    if verdicts is None:
        sentences = [
            {**claim, "supported": False, "reason": unavailable_reason, "verification_unavailable": True}
            for claim in claims
        ]
        return {
            "verification_available": False,
            "passed": False,
            "sentences": sentences,
            "summary": {"supported": 0, "unsupported": 0, "unverifiable": len(sentences)},
            "reason": unavailable_reason,
        }

    sentences = [
        {
            **claim,
            "supported": verdict["supported"],
            "reason": _text(verdict.get("reason"), "", 500),
            "verification_unavailable": False,
        }
        for claim, verdict in zip(claims, verdicts)
    ]
    supported = sum(1 for sentence in sentences if sentence["supported"])
    unsupported = len(sentences) - supported
    missing_sources = sum(1 for sentence in sentences if not sentence["citation_ids"])
    return {
        "verification_available": True,
        "passed": unsupported == 0 and missing_sources == 0,
        "sentences": sentences,
        "summary": {"supported": supported, "unsupported": unsupported, "unverifiable": 0},
        "reason": "All claims were supported." if unsupported == 0 and missing_sources == 0 else "One or more claims need human review.",
    }


def run_mandatory_audit(case_id: str, workspace_id: str) -> dict:
    case = _get_case(case_id, workspace_id)
    if _stage_completed(case, 'audited'):
        return case
    _require_stage(case, "draft_complete")
    with traced_span("document_case.mandatory_audit"):
        audit = _strict_audit(case["draft_action_pack"].get("audit_claims", []), case["citations"])
    case["audit"] = audit
    return _save(case, "audited", "verified" if audit["passed"] else "needs_human_review")


def finalize_case(case_id: str, workspace_id: str) -> dict:
    case = _get_case(case_id, workspace_id)
    if _stage_completed(case, 'finalized'):
        return case
    _require_stage(case, "audited")
    audit = case["audit"]
    draft = case["draft_action_pack"]
    if audit["passed"]:
        action_pack = {
            "verification_status": "verified",
            "executive_summary": draft["executive_summary"],
            "decisions_required": draft["decisions_required"],
            "action_items": draft["action_items"],
            "deadline_calendar": draft["deadline_calendar"],
            "risk_register": draft["risk_register"],
            "open_questions": draft["open_questions"],
            "human_review_required": True,
            "next_step": "A human must approve any task, reminder, or external notification.",
        }
        status = "ready_for_human_review"
    else:
        supported_summary = " ".join(
            sentence["text"] for sentence in audit.get("sentences", [])
            if sentence["supported"] and sentence["category"] == "summary"
        )
        action_pack = {
            "verification_status": "needs_human_review",
            "executive_summary": supported_summary or "The automatic brief was withheld because the evidence gate did not pass.",
            "decisions_required": [],
            "action_items": [],
            "deadline_calendar": [],
            "risk_register": [],
            "open_questions": draft.get("open_questions", []),
            "human_review_required": True,
            "next_step": "Review the unsupported or unverifiable claims before any action is created.",
        }
        status = "needs_human_review"
    case["final_action_pack"] = action_pack
    return _save(case, "finalized", status)


def public_case(case: dict) -> dict:
    """Return the full auditable case payload without internal database fields."""
    return case


def _stage_completed(case, target):
    from services.case_stages import CASE_STAGES
    stages = CASE_STAGES
    current = case.get('stage')
    return current in stages and stages.index(current)>=stages.index(target)
