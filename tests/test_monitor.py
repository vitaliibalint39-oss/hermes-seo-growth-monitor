"""Offline, synthetic tests; no third-party packages or MCP/network calls."""
import datetime as dt
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'monitor.py'
spec = importlib.util.spec_from_file_location('hermes_monitor', SCRIPT)
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='hermes-seo-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.end = dt.date.today() - dt.timedelta(days=5)

    def new_run(self):
        return monitor.init(output=self.root, end=str(self.end), site='ta551.info', synthetic=True)

    def test_windows_use_inclusive_dates_and_disjoint_baselines(self):
        period = monitor.windows(self.end)
        for n in (7, 28):
            current = period[f'current{n}']
            previous = period[f'previous{n}']
            self.assertEqual((dt.date.fromisoformat(current['endDate']) - dt.date.fromisoformat(current['startDate'])).days, n-1)
            self.assertEqual((dt.date.fromisoformat(previous['endDate']) - dt.date.fromisoformat(previous['startDate'])).days, n-1)
            self.assertLess(dt.date.fromisoformat(previous['endDate']), dt.date.fromisoformat(current['startDate']))

    def test_plan_does_not_contain_private_ga4_ids_by_default(self):
        run = self.new_run()
        plan = monitor.read(run / 'plan.json')
        self.assertIsNone(plan['sites']['ta551.info']['ga4_property'])
        requests = monitor.read(run / 'requests-ta551.info.json')
        self.assertFalse(any(label.startswith('ga4-') for label in requests))
        self.assertEqual(requests['gsc-current28']['args']['engine'], 'google')

    def test_custom_config_supports_own_domain(self):
        path = self.root / 'config.json'
        path.write_text(json.dumps({'sites': {'example.org': {'gsc_property': 'sc-domain:example.org', 'ga4_property': '123456'}}}), encoding='utf-8')
        run = monitor.init(output=self.root, end=str(self.end), config=path, site='example.org', synthetic=True)
        requests = monitor.read(run / 'requests-example.org.json')
        self.assertEqual(requests['ga4-current28']['args']['propertyId'], '123456')
        self.assertEqual(requests['inspection-google']['args']['urls'], ['https://example.org/'])

    def test_config_rejects_off_domain_gsc_scope(self):
        path = self.root / 'bad.json'
        path.write_text(json.dumps({'sites': {'example.org': {'gsc_property': 'sc-domain:notexample.org'}}}), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'property must belong'):
            monitor.site_config(path)

    def test_capture_and_render_preserve_metrics_and_missing_values(self):
        run = self.new_run()
        raw = self.root / 'raw.json'
        raw.write_text(json.dumps({'google': [{'clicks': 12, 'impressions': 300, 'position': 8.4}]}), encoding='utf-8')
        monitor.capture(run, 'ta551.info', 'gsc-current28', raw)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            monitor.capture(run, 'ta551.info', 'gsc-current28', raw)
        report = monitor.render(run)
        site = (run / 'ta551.info.md').read_text(encoding='utf-8')
        self.assertTrue(report.exists())
        self.assertIn('SYNTHETIC TEST DATA', site)
        self.assertIn('300', site)
        self.assertIn('12', site)
        self.assertIn('Unavailable', site)
        self.assertEqual(monitor.read(run / 'snapshot.json')['sites']['ta551.info']['metrics']['current28']['impressions'], 300)

    def test_invalid_ungrouped_metrics_not_misreported_as_zero(self):
        run = self.new_run()
        bad = self.root / 'negative.json'
        bad.write_text(json.dumps({'google': [{'clicks': 2, 'impressions': -10, 'position': 1.0}]}), encoding='utf-8')
        monitor.capture(run, 'ta551.info', 'gsc-current28', bad)
        monitor.render(run)
        report = (run / 'ta551.info.md').read_text(encoding='utf-8')
        self.assertIn('Invalid ungrouped metrics', report)
        self.assertIsNone(monitor.read(run/'snapshot.json')['sites']['ta551.info']['metrics']['current28'])

    def test_mcp_error_is_unavailable_not_zero(self):
        run = self.new_run()
        error = self.root / 'error.json'
        error.write_text(json.dumps({'isError': True, 'content': [{'type':'text', 'text':'Authentication failed'}]}), encoding='utf-8')
        monitor.capture(run, 'ta551.info', 'gsc-current28', error)
        monitor.render(run)
        self.assertIn('Unavailable: invalid scope, dates, envelope, or provider error', (run/'ta551.info.md').read_text(encoding='utf-8'))

    def test_set_property_refuses_cross_domain_or_late_changes(self):
        run = self.new_run()
        with self.assertRaisesRegex(ValueError,'property must belong'):
            monitor.set_property(run, 'ta551.info', 'sc-domain:another-site.com')
        monitor.set_property(run, 'ta551.info', 'https://www.ta551.info/')
        prop = monitor.read(run/'plan.json')['sites']['ta551.info']['gsc_property']
        self.assertEqual(prop, 'https://www.ta551.info/')
        raw = self.root / 'raw.json'
        raw.write_text(json.dumps({'google': []}), encoding='utf-8')
        monitor.capture(run, 'ta551.info', 'gsc-current28', raw)
        with self.assertRaisesRegex(ValueError, 'after evidence'):
            monitor.set_property(run, 'ta551.info', 'sc-domain:ta551.info')

    def test_missing_evidence_is_not_a_measured_zero(self):
        run = self.new_run()
        monitor.render(run)
        snapshot = monitor.read(run/'snapshot.json')
        self.assertIsNone(snapshot['sites']['ta551.info']['metrics']['current7'])
        self.assertIn('Unavailable', (run/'ta551.info.md').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
