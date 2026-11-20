"""Evaluate the structured-case review gate using development fixtures and a fake model."""
import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def evaluate(data, audit):
    cases = data.get('cases') if isinstance(data, dict) else None
    if not isinstance(cases, list) or not cases:
        raise ValueError('A nonempty fixture corpus is required')
    counts = {'cases': 0, 'unsupported_marked_supported': 0,
              'critical_review_missed': 0, 'supported_needing_review': 0}
    seen = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get('id'), str) or not case['id'] or case['id'] in seen:
            raise ValueError('Every case requires a distinct ID')
        seen.add(case['id'])
        if any(not isinstance(case.get(key), str) or not case[key].strip() for key in ('source', 'claim')):
            raise ValueError('Each case requires source and claim text')
        if any(type(case.get(key)) is not bool for key in ('source_supports_claim', 'expect_review')):
            raise ValueError('Fixture labels must be booleans')
        outcome = audit(case)
        sentences = outcome.get('sentences') if isinstance(outcome, dict) else None
        if not isinstance(sentences, list) or len(sentences) != 1 or not isinstance(sentences[0], dict):
            raise ValueError('Unexpected audit result')
        result = sentences[0]
        if type(result.get('supported')) is not bool or type(result.get('verification_unavailable')) is not bool:
            raise ValueError('Unexpected verdict fields')
        counts['cases'] += 1
        counts['unsupported_marked_supported'] += not case['source_supports_claim'] and result['supported']
        counts['critical_review_missed'] += case['expect_review'] and not result['verification_unavailable']
        counts['supported_needing_review'] += case['source_supports_claim'] and result['verification_unavailable']
    return counts


def main():
    from services import document_case
    path = Path(__file__).with_name('claim_gate_v1.json')
    raw = path.read_bytes()
    data = json.loads(raw)
    def mock_audit(case):
        claims = [{'text': case['claim'], 'citation_ids': ['C1']}]
        evidence = [{'id': 'C1', 'page': 1, 'excerpt': case['source']}]
        with patch.object(document_case, 'complete', return_value='[{"supported": true, "reason": "mock"}]'):
            return document_case._strict_audit(claims, evidence)
    counts = evaluate(data, mock_audit)
    print(json.dumps({'corpus_version': data['version'], 'corpus_sha256': hashlib.sha256(raw).hexdigest(),
                      'mode': 'synthetic development fixtures; mocked positive model', **counts,
                      'limits': ['not independently annotated', 'no PDF extraction, OCR, retrieval or provider',
                                 'review-required is not proof that a claim is false']}, indent=2))
    return 1 if counts['critical_review_missed'] or counts['unsupported_marked_supported'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
