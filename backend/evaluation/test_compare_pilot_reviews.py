import copy
import unittest

from compare_pilot_reviews import compare


class PilotComparisonTests(unittest.TestCase):
    def setUp(self):
        self.first = {'reviewer': 'one', 'documents': [{'id': 'pilot-01', 'fields': {
            'owner': {'status': 'present', 'value': 'A', 'page': 1, 'quote': 'A'},
            'approver': {'status': 'absent', 'reviewed_pages': [1, 2]},
            'deadline': {'status': 'uncertain', 'reason': 'unclear'}}}]}
        self.second = copy.deepcopy(self.first); self.second['reviewer'] = 'two'

    def test_reports_fields_without_exposing_values_or_quotes(self):
        self.second['documents'][0]['fields']['owner']['value'] = 'B'
        self.second['documents'][0]['fields']['approver'] = {'status': 'uncertain', 'reason': 'x'}
        result = compare(self.first, self.second)
        self.assertEqual(result['fields_compared'], 3)
        self.assertEqual(result['disagreements'], [
            {'id': 'pilot-01', 'field': 'owner', 'status_differs': False},
            {'id': 'pilot-01', 'field': 'approver', 'status_differs': True}])
        self.assertNotIn('quote', str(result))

    def test_same_reviewer_identifier_is_rejected(self):
        self.second['reviewer'] = ' ONE '
        with self.assertRaisesRegex(ValueError, 'distinct'):
            compare(self.first, self.second)


if __name__ == '__main__':
    unittest.main()
