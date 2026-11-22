import hashlib
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest

from prepare_blind_review import prepare


class BlindReviewPacketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.corpus = self.root / 'corpus'; self.corpus.mkdir()
        self.output = self.root / 'output'; self.output.mkdir()
        self.manifest = {'version': 'pilot-1', 'documents': []}
        for number in range(1, 31):
            identifier = f'pilot-{number:02}'
            data = f'synthetic {number}'.encode()
            (self.corpus / f'{identifier}.pdf').write_bytes(data)
            self.manifest['documents'].append({
                'id': identifier, 'filename': f'{identifier}.pdf', 'language': 'el',
                'format': 'scanned' if number % 5 == 1 else 'digital', 'split': 'development_only',
                'sha256': hashlib.sha256(data).hexdigest(),
                'expected': {'owner': 'SECRET_LABEL', 'approver': 'PERSON', 'deadline': '2027-01-01',
                             'page': 1, 'budget': None, 'untrusted_instruction_page': 2}})
        self.write_manifest()

    def write_manifest(self):
        (self.corpus / 'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')

    def test_packet_contains_no_labels_and_requires_manual_review(self):
        target = self.output / 'blind'
        self.assertEqual(prepare(self.corpus, target, self.output), 30)
        documents = json.loads((target / 'documents.json').read_text(encoding='utf-8'))
        review = json.loads((target / 'review-template.json').read_text(encoding='utf-8'))
        self.assertEqual(len(documents['documents']), 30)
        self.assertNotIn('SECRET_LABEL', json.dumps(documents))
        self.assertNotIn('SECRET_LABEL', json.dumps(review))
        self.assertEqual(len(list((target / 'pdfs').glob('*.pdf'))), 30)
        self.assertFalse((target / 'pdfs' / 'manifest.json').exists())
        self.assertEqual(review['reviewer'], '')
        self.assertTrue(all(value is None for doc in review['documents'] for value in doc['fields'].values()))
        with self.assertRaises(FileExistsError):
            prepare(self.corpus, target, self.output)

    def test_tampered_corpus_and_destination_outside_output_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'designated output'):
            prepare(self.corpus, self.root / 'outside', self.output)
        (self.corpus / 'pilot-01.pdf').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            prepare(self.corpus, self.output / 'blind', self.output)
        self.assertFalse((self.output / 'blind').exists())

    def test_ambiguous_manifest_is_rejected_before_creating_packet(self):
        path = self.corpus / 'manifest.json'
        raw = path.read_text(encoding='utf-8')
        path.write_text(raw.replace('"version": "pilot-1"', '"version": "other", "version": "pilot-1"', 1), encoding='utf-8')
        target = self.output / 'blind'
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON key'):
            prepare(self.corpus, target, self.output)
        self.assertFalse(target.exists())

    def test_comparison_cli_validates_complete_reviews_and_corpus(self):
        digest = hashlib.sha256((self.corpus / 'manifest.json').read_bytes()).hexdigest()
        fields = {'owner': {'status': 'uncertain', 'reason': 'fixture'},
                  'approver': {'status': 'absent', 'reviewed_pages': [1, 2]},
                  'deadline': {'status': 'present', 'value': 'test', 'quote': 'test', 'page': 1}}
        review = {'reviewer': 'one', 'manifest_sha256': digest,
                  'documents': [{'id': item['id'], 'fields': fields} for item in self.manifest['documents']]}
        first, second = self.output / 'one.json', self.output / 'two.json'
        first.write_text(json.dumps(review), encoding='utf-8')
        review['reviewer'] = 'two'; second.write_text(json.dumps(review), encoding='utf-8')
        command = [sys.executable, str(Path(__file__).with_name('compare_pilot_reviews.py')),
                   '--corpus', str(self.corpus), '--first', str(first), '--second', str(second)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['fields_compared'], 90)
        review['documents'].pop(); second.write_text(json.dumps(review), encoding='utf-8')
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)


if __name__ == '__main__':
    unittest.main()
