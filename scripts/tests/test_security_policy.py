import importlib.util
from pathlib import Path
import unittest


def module(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / 'security' / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


osv, sarif = module('audit_python'), module('sarif_gate')
image = module('image_gate')


class SecurityPolicyTests(unittest.TestCase):
    def image_report(self):
        return {'SchemaVersion':2,'ArtifactType':'container_image','ArtifactID':'sha256:fixture',
                'Metadata':{'ImageID':'sha256:'+'b'*64,'OS':{'Family':'debian','Name':'13'}},
                'Results':[{'Class':'os-pkgs'}, {'Class':'lang-pkgs'}]}

    def test_complete_image_inventory_without_findings_passes(self):
        self.assertEqual(image.evaluate(self.image_report())['gate'],'PASSED')

    def test_scan_identity_uses_docker_image_not_internal_scanner_artifact(self):
        report = self.image_report()
        result = image.evaluate(report)
        self.assertEqual(result['image'], report['Metadata']['ImageID'])
        self.assertEqual(result['scanner_artifact_id'], report['ArtifactID'])
        for value in (None, '', 'latest', 'sha256:short', 42):
            report['Metadata']['ImageID'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                image.evaluate(report)

    def test_image_scan_cannot_pass_with_missing_coverage(self):
        for report in ({}, {**self.image_report(),'Results':[]},
                       {**self.image_report(),'Results':[{'Class':'os-pkgs'}]},
                       {**self.image_report(),'ArtifactID':''}):
            with self.subTest(report=report), self.assertRaises(ValueError):
                image.evaluate(report)

    def test_unfixed_image_advisories_and_eol_os_remain_blocked(self):
        report=self.image_report()
        report['Results'][0]['Vulnerabilities']=[{'VulnerabilityID':'CVE-fixture','PkgName':'fixture',
                                                 'InstalledVersion':'1','Severity':'HIGH'}]
        self.assertEqual(image.evaluate(report)['gate'],'FAILED')
        report=self.image_report(); report['Metadata']['OS']['Eosl']=True
        self.assertEqual(image.evaluate(report)['gate'],'FAILED')

    def test_invalid_image_records_are_not_ignored(self):
        report=self.image_report(); report['Results'][1]['Vulnerabilities']=[{}]
        with self.assertRaises(ValueError):image.evaluate(report)

    def test_osv_complete_empty_report_passes(self):
        self.assertEqual(osv.evaluate([{'name': 'fixture', 'version': '1'}], {'results': [{}]}), [])

    def test_osv_incomplete_report_is_not_a_pass(self):
        for report in ({}, {'results': []}, {'results': [{'next_page_token': 'more'}]}, {'results': [{'vulns': [{'id': ''}]}]}):
            with self.subTest(report=report), self.assertRaises(ValueError):
                osv.evaluate([{'name': 'fixture', 'version': '1'}], report)

    def test_osv_advisories_block_without_a_suppression_path(self):
        result = osv.evaluate([{'name': 'fixture', 'version': '1'}], {'results': [{'vulns': [{'id': 'GHSA-test'}]}]})
        self.assertEqual(result[0]['advisory_records'], ['GHSA-test'])

    def test_other_projects_and_system_python_cannot_be_sent(self):
        self.assertFalse(osv.project_environment(osv.ROOT.parent / 'padel/.venv'))
        self.assertFalse(osv.project_environment('/usr'))
        self.assertTrue(osv.project_environment(osv.ROOT / 'backend/.venv'))

    def report(self, score='8.0', level='warning'):
        return {'version': '2.1.0', 'runs': [{'tool': {'driver': {'name': 'CodeQL', 'rules': [{'id': 'rule', 'properties': {'security-severity': score}}]}}, 'results': [{'ruleId': 'rule', 'level': level, 'message': {'text': 'private source snippet'}}]}]}

    def test_high_security_findings_block(self):
        result = sarif.evaluate(self.report())
        self.assertEqual(result['gate'], 'FAILED')
        self.assertNotIn('private source snippet', str(result))

    def test_sarif_location_excludes_snippets_and_external_paths(self):
        report = self.report()
        finding = report['runs'][0]['results'][0]
        finding['locations'] = [{'physicalLocation': {'artifactLocation': {'uri': 'backend/app.py'}, 'region': {'startLine': 42, 'snippet': {'text': 'secret'}}}}]
        result = sarif.evaluate(report)['findings'][0]
        self.assertEqual(result['location'], {'path': 'backend/app.py', 'line': 42})
        self.assertNotIn('secret', str(result))
        finding['locations'][0]['physicalLocation']['artifactLocation']['uri'] = '../private'
        self.assertNotIn('location', sarif.evaluate(report)['findings'][0])

    def test_lower_findings_are_not_hidden(self):
        result = sarif.evaluate(self.report('4.0'))
        self.assertEqual(result['gate'], 'PASSED')
        self.assertEqual(len(result['findings']), 1)

    def test_error_level_blocks_without_security_score(self):
        self.assertEqual(sarif.evaluate(self.report('0', 'error'))['gate'], 'FAILED')

    def test_missing_or_failed_analysis_blocks(self):
        with self.assertRaises(ValueError):
            sarif.evaluate({})
        report = self.report()
        report['runs'][0]['invocations'] = [{'executionSuccessful': False}]
        with self.assertRaises(ValueError):
            sarif.evaluate(report)

    def test_unknown_rules_and_invalid_scores_block(self):
        report = self.report()
        report['runs'][0]['results'][0]['ruleId'] = 'unknown'
        with self.assertRaises(ValueError):
            sarif.evaluate(report)
        with self.assertRaises(ValueError):
            sarif.evaluate(self.report('nan'))
