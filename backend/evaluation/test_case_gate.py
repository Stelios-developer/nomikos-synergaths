import unittest

from run_case_gate import evaluate


class CaseGateMetricsTests(unittest.TestCase):
    def test_counts_false_certification_and_review_of_supported_claims(self):
        data = {'cases': [
            {'id': 'x', 'source': 'source', 'claim': 'false claim', 'source_supports_claim': False, 'expect_review': True},
            {'id': 'y', 'source': 'source', 'claim': 'true claim', 'source_supports_claim': True, 'expect_review': False},
        ]}
        def fake(case):
            return {'sentences': [{'supported': case['id'] == 'x', 'verification_unavailable': case['id'] == 'y'}]}
        self.assertEqual(evaluate(data, fake), {'cases': 2, 'unsupported_marked_supported': 1,
                                                'critical_review_missed': 1, 'supported_needing_review': 1})

    def test_rejects_empty_duplicate_and_non_boolean_labels(self):
        case = {'id': 'x', 'source': 'source', 'claim': 'claim', 'source_supports_claim': False, 'expect_review': True}
        for data in ({'cases': []}, {'cases': [case, case]}, {'cases': [{**case, 'expect_review': 'true'}]}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                evaluate(data, lambda _case: {'sentences': [{'supported': False, 'verification_unavailable': True}]})


if __name__ == '__main__':
    unittest.main()
