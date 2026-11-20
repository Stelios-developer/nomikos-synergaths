from unittest.mock import patch

import pytest

from services import document_case


@pytest.mark.parametrize('citations', [[], ['C99'], ['C1', 'C99'], None, 'C1'])
def test_missing_or_unknown_case_citations_never_call_model(citations):
    claims = [{'text': 'Synthetic claim', 'citation_ids': citations}]
    evidence = [{'id': 'C1', 'page': 1, 'excerpt': 'Synthetic source'}]
    with patch.object(document_case, 'complete') as complete:
        result = document_case._strict_audit(claims, evidence)
    complete.assert_not_called()
    assert result['passed'] is False
    assert result['verification_available'] is False
    assert result['sentences'][0]['verification_unavailable'] is True
    assert result['summary']['unverifiable'] == 1


def test_invalid_citation_in_batch_withholds_all_claims_without_model_call():
    claims = [{'text': 'First', 'citation_ids': ['C1']}, {'text': 'Second', 'citation_ids': ['unknown']}]
    evidence = [{'id': 'C1', 'page': 1, 'excerpt': 'Synthetic source'}]
    with patch.object(document_case, 'complete') as complete:
        result = document_case._strict_audit(claims, evidence)
    complete.assert_not_called()
    assert result['passed'] is False
    assert result['summary']['unverifiable'] == 2


def test_uncited_excerpts_are_not_sent_to_model():
    claims = [{'text': 'First', 'citation_ids': ['C1']}]
    evidence = [{'id': 'C1', 'page': 1, 'excerpt': 'Synthetic cited source'},
                {'id': 'C2', 'page': 2, 'excerpt': 'SYNTHETIC_UNCITED_SOURCE'}]
    with patch.object(document_case, 'complete', return_value='[{"supported": true, "reason": "mock"}]') as complete:
        result = document_case._strict_audit(claims, evidence)
    prompt = complete.call_args.args[0]
    assert 'Synthetic cited source' in prompt
    assert 'SYNTHETIC_UNCITED_SOURCE' not in prompt
    assert result['passed'] is False
    assert result['sentences'][0]['verification_unavailable'] is True


@pytest.mark.parametrize('evidence', [
    [{'id': 'C1', 'page': 1, 'excerpt': 'First'}, {'id': 'C1', 'page': 2, 'excerpt': 'Conflicting'}],
    [{'id': 'C1', 'page': 0, 'excerpt': 'No valid page'}],
    [{'id': 'C1', 'page': 1, 'excerpt': '   '}],
    [{'id': 'C1', 'excerpt': 'Missing page'}],
])
def test_ambiguous_or_empty_cited_evidence_never_calls_model(evidence):
    with patch.object(document_case, 'complete') as complete:
        result = document_case._strict_audit([{'text': 'Synthetic claim', 'citation_ids': ['C1']}], evidence)
    complete.assert_not_called()
    assert result['verification_available'] is False
    assert result['sentences'][0]['verification_unavailable'] is True
