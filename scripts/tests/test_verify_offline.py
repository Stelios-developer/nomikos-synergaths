import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile


spec = importlib.util.spec_from_file_location('verify_offline', Path(__file__).parents[1] / 'quality' / 'verify_offline.py')
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


class OfflineVerificationTests(unittest.TestCase):
    def test_dirty_tree_is_rejected_before_revision_read(self):
        with patch.object(verify, 'run', return_value=' M important.py') as run:
            with self.assertRaisesRegex(ValueError, 'working-tree'):
                verify.clean_revision()
            self.assertEqual(run.call_count, 1)

    def test_clean_revision_must_be_a_git_hash(self):
        with patch.object(verify, 'run', side_effect=['', 'a' * 40]):
            self.assertEqual(verify.clean_revision(), 'a' * 40)
        with patch.object(verify, 'run', side_effect=['', 'not-a-hash']):
            with self.assertRaisesRegex(ValueError, 'Invalid Git revision'):
                verify.clean_revision()

    def test_archive_rejects_traversal_and_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); destination = root / 'source'; destination.mkdir()
            archive = root / 'test.zip'
            with zipfile.ZipFile(archive, 'w') as bundle:
                bundle.writestr('../escape', 'unsafe')
            with self.assertRaisesRegex(ValueError, 'Unsafe archive'):
                verify.extract_archive(archive, destination)
            info = zipfile.ZipInfo('link'); info.create_system = 3; info.external_attr = (0o120777 << 16)
            with zipfile.ZipFile(archive, 'w') as bundle:
                bundle.writestr(info, 'target')
            with self.assertRaisesRegex(ValueError, 'Unsafe archive'):
                verify.extract_archive(archive, destination)
            self.assertFalse((root / 'escape').exists())

    def test_archive_extracts_regular_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); destination = root / 'source'; destination.mkdir()
            archive = root / 'test.zip'
            with zipfile.ZipFile(archive, 'w') as bundle:
                bundle.writestr('dir/file.txt', 'safe')
            verify.extract_archive(archive, destination)
            self.assertEqual((destination / 'dir' / 'file.txt').read_text(), 'safe')


if __name__ == '__main__':
    unittest.main()
