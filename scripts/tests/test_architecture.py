import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('repository_quality', Path(__file__).resolve().parents[1] / 'quality/repository_check.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class ArchitectureTests(unittest.TestCase):
    def test_browser_cycle_fails(self):
        self.assertTrue(check.cycles({'a': ['b'], 'b': ['a']}))

    def test_diamond_is_not_a_cycle(self):
        self.assertEqual(check.cycles({'a': ['b', 'c'], 'b': ['d'], 'c': ['d'], 'd': []}), [])

    def test_domain_may_not_import_http_composition(self):
        self.assertTrue(check.inspect_sources({'backend/services/example.py': 'from routers import documents'}))

    def test_domain_may_not_import_main_lazily_either(self):
        self.assertTrue(check.inspect_sources({'backend/db/example.py': 'def f():\n    import main'}))

    def test_browser_may_not_import_node(self):
        self.assertTrue(check.inspect_sources({'frontend/src/example.ts': "import fs from 'node:fs'"}))

    def test_ui_free_transport(self):
        self.assertTrue(check.inspect_sources({
            'frontend/src/api/example.ts': "import { X } from '../components/X'",
            'frontend/src/components/X.tsx': 'export const X = 1',
        }))

    def test_removed_relative_module_is_detected(self):
        self.assertTrue(check.inspect_sources({'frontend/src/example.ts': "import x from './missing'"}))

    def test_layered_sources_are_allowed(self):
        self.assertEqual(check.inspect_sources({
            'frontend/src/api/example.ts': 'export const x = 1',
            'frontend/src/components/X.tsx': "import { x } from '../api/example'",
            'backend/services/example.py': 'from services import case_store',
        }), [])
