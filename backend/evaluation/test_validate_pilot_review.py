import copy
import unittest

from validate_pilot_review import strict_json, validate_review


class PilotHumanReviewTests(unittest.TestCase):
    def test_review_json_cannot_hide_duplicate_fields_or_nonfinite_numbers(self):
        for raw in (b'{"reviewer":"one","reviewer":"two"}',
                    b'{"documents":[{"fields":{"owner":1,"owner":2}}]}',
                    b'{"page":NaN}', b'{"page":Infinity}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                strict_json(raw)
        self.assertEqual(strict_json(b'\xef\xbb\xbf{"page":1}'), {'page': 1})

    def setUp(self):
        self.manifest = {'documents': [{'id': 'pilot-01'}, {'id': 'pilot-02'}]}
        fields = {'owner': {'status': 'present', 'value': 'A', 'page': 1, 'quote': 'Owner A'},
                  'approver': {'status': 'absent', 'reviewed_pages': [1, 2]},
                  'deadline': {'status': 'uncertain', 'reason': 'Not clear'}}
        self.review = {'reviewer': 'test-reviewer', 'manifest_sha256': 'hash',
                       'documents': [{'id': entry['id'], 'fields': copy.deepcopy(fields)} for entry in self.manifest['documents']]}

    def test_complete_review_is_structurally_valid(self):
        self.assertEqual(validate_review(self.review, self.manifest, 'hash'), 2)

    def test_rejects_stale_incomplete_or_duplicate_review(self):
        with self.assertRaisesRegex(ValueError, 'manifest'):
            validate_review(self.review, self.manifest, 'different')
        for change in ('incomplete', 'duplicate'):
            review = copy.deepcopy(self.review)
            if change == 'incomplete': review['documents'].pop()
            else: review['documents'][1]['id'] = review['documents'][0]['id']
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_review(review, self.manifest, 'hash')

    def test_rejects_unknown_top_level_and_document_metadata(self):
        for target in ('review', 'document'):
            review = copy.deepcopy(self.review)
            (review if target == 'review' else review['documents'][0])['confidence'] = 'unverified'
            with self.subTest(target=target), self.assertRaises(ValueError):
                validate_review(review, self.manifest, 'hash')

    def test_rejects_unsubstantiated_structural_annotations(self):
        for change in ('bad_page', 'empty_quote', 'partial_absence', 'boolean_page', 'missing_reason', 'contradictory'):
            review = copy.deepcopy(self.review)
            fields = review['documents'][0]['fields']
            if change == 'bad_page': fields['owner']['page'] = 3
            elif change == 'empty_quote': fields['owner']['quote'] = ''
            elif change == 'partial_absence': fields['approver']['reviewed_pages'] = [1]
            elif change == 'boolean_page': fields['approver']['reviewed_pages'] = [True, 2]
            elif change == 'missing_reason': fields['deadline']['reason'] = ''
            else: fields['approver']['value'] = 'contradiction'
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_review(review, self.manifest, 'hash')


if __name__ == '__main__':
    unittest.main()
