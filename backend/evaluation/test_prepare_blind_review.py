import hashlib
import json
from pathlib import Path
import tempfile
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


if __name__ == '__main__':
    unittest.main()
