import contextlib
import importlib.util
import io
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("index_check", Path(__file__).resolve().parents[1] / "check_git_index.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class IndexSafetyTests(unittest.TestCase):
    def test_runtime_exports_and_test_links_are_rejected(self):
        for path in (
            "n8n/active-workflow.export.json",
            "n8n/exported-workflow.json",
            "backend/.codex-pytest-brand/current",
            "backend/.env", "frontend/.env.production", "backend/storage/file.pdf",
            "output/security-backups/backup.aesgcm", "backend/local.sqlite",
        ):
            with self.subTest(path=path):
                self.assertTrue(check.forbidden_path(path))

    def test_examples_and_canonical_workflows_are_allowed(self):
        for path in (
            "backend/.env.example", "frontend/.env.production.example",
            "n8n/agent-orchestrator.workflow.json",
            "n8n/manual-pdf-upload-workflow.template.json", "frontend/src/App.tsx",
        ):
            with self.subTest(path=path):
                self.assertFalse(check.forbidden_path(path))

    def run_check(self, entries, blobs, secrets=()):
        calls = []

        def fake_git(*args):
            calls.append(args)
            if args == ("ls-files", "--stage", "-z"):
                return entries
            if args[:2] == ("cat-file", "blob"):
                return blobs[args[2]]
            raise AssertionError(args)

        output = io.StringIO()
        with patch.object(check, "git", side_effect=fake_git), patch.object(check, "configured_secrets", return_value=secrets), contextlib.redirect_stdout(output):
            status = check.main()
        return status, output.getvalue(), calls

    def test_reads_the_index_blob_not_the_working_file(self):
        status, output, calls = self.run_check(b"100644 abc 0\tfrontend/src/App.tsx\0", {"abc": b"safe staged code"})
        self.assertEqual(status, 0)
        self.assertIn(("cat-file", "blob", "abc"), calls)
        self.assertIn("0 findings", output)

    def test_secret_findings_never_print_values(self):
        secret = b"fixture-only-" * 4
        status, output, _ = self.run_check(b"100644 abc 0\tREADME.md\0", {"abc": secret}, [("BETTER_AUTH_SECRET", secret)])
        self.assertEqual(status, 1)
        self.assertIn("configured secret match", output)
        self.assertNotIn("BETTER_AUTH_SECRET", output)
        self.assertNotIn(secret.decode(), output)

    def test_recognizable_provider_token_is_blocked(self):
        token = b"sk-proj-" + b"a" * 40
        status, output, _ = self.run_check(b"100644 abc 0\tREADME.md\0", {"abc": token})
        self.assertEqual(status, 1)
        self.assertIn("provider token", output)
        self.assertNotIn(token.decode(), output)

    def test_private_key_is_blocked(self):
        key = b"-----BEGIN " + b"PRIVATE KEY-----"
        status, output, _ = self.run_check(b"100644 abc 0\tREADME.md\0", {"abc": key})
        self.assertEqual(status, 1)
        self.assertIn("private key", output)

    def test_symlinks_are_not_followed(self):
        status, output, calls = self.run_check(b"120000 abc 0\tcurrent\0", {})
        self.assertEqual(status, 1)
        self.assertIn("symlink", output)
        self.assertEqual(len(calls), 1)

    def test_unresolved_conflicts_block_release(self):
        status, output, _ = self.run_check(b"100644 abc 2\tREADME.md\0", {})
        self.assertEqual(status, 1)
        self.assertIn("merge conflict", output)


if __name__ == "__main__":
    unittest.main()
