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

    def test_checkpoint_pending_then_valid_capture(self):
        run = self.new_run()
        state = monitor.status(run)
        self.assertEqual(state['counts'], {'planned': 9, 'completed': 0, 'missing': 9, 'invalid': 0})
        first = monitor.next_request(run)
        self.assertEqual((first['state'], first['site'], first['label']),
                         ('pending', 'ta551.info', 'gsc-current7'))
        self.assertEqual(first['tool'], 'mcp__seo_traffic__analytics_query')
        self.assertEqual(first['args'], monitor.read(run/'requests-ta551.info.json')['gsc-current7']['args'])
        raw = self.root/'first.json'
        raw.write_text(json.dumps({'google': [{'clicks': 0, 'impressions': 7, 'position': 14.57}]}), encoding='utf-8')
        monitor.capture(run, 'ta551.info', 'gsc-current7', raw)
        self.assertEqual(monitor.status(run)['counts']['completed'], 1)
        self.assertEqual(monitor.next_request(run)['label'], 'gsc-previous7')
        self.assertEqual(monitor.status(run)['counts']['missing'], 8)

    def test_empty_gsc_response_is_saved_not_measured_zero(self):
        run = self.new_run()
        raw = self.root/'empty.json'
        raw.write_text('{"google":[]}', encoding='utf-8')
        monitor.capture(run, 'ta551.info', 'gsc-current7', raw)
        self.assertIn('gsc-current7', monitor.status(run)['sites']['ta551.info']['completed'])
        monitor.render(run)
        snap = monitor.read(run/'snapshot.json')
        self.assertIsNone(snap['sites']['ta551.info']['metrics']['current7'])

    def test_invalid_evidence_blocks_next_without_overwrite(self):
        run = self.new_run()
        raw = self.root/'wrong.json'
        raw.write_text(json.dumps({'google':[{'clicks': 2, 'impressions': -1, 'position': 1}]}), encoding='utf-8')
        original = monitor.capture(run, 'ta551.info', 'gsc-current7', raw)
        self.assertEqual(monitor.status(run)['counts']['invalid'], 1)
        nxt = monitor.next_request(run)
        self.assertEqual((nxt['state'], nxt['label']), ('blocked_invalid', 'gsc-current7'))
        self.assertTrue(original.exists())
        with self.assertRaisesRegex(ValueError, 'already exists'):
            monitor.capture(run, 'ta551.info', 'gsc-current7', raw)

    def test_invalid_scope_and_missing_site(self):
        run = self.new_run()
        raw = self.root/'scope.json'
        raw.write_text('{"google":[]}', encoding='utf-8')
        path = monitor.capture(run, 'ta551.info', 'gsc-current7', raw)
        obj = monitor.read(path)
        obj['args']['startDate'] = '2020-01-01'
        path.write_text(json.dumps(obj), encoding='utf-8')
        self.assertIn('gsc-current7', monitor.status(run)['sites']['ta551.info']['invalid'])
        self.assertEqual(monitor.next_request(run)['state'], 'blocked_invalid')
        with self.assertRaisesRegex(ValueError, 'Unknown site'):
            monitor.status(run, site='not-owned.example')

    def test_wrapped_native_mcp_result_is_accepted_without_changing_metrics(self):
        run = self.new_run()
        raw = self.root/'native.json'
        raw.write_text(json.dumps({'result': {'google': [
            {'clicks': 0, 'impressions': 7, 'ctr': 0, 'position': 14.5714285714}
        ]}}), encoding='utf-8')
        monitor.capture(run, 'ta551.info', 'gsc-current7', raw)
        self.assertEqual(monitor.status(run)['counts']['completed'], 1)
        monitor.render(run)
        snap = monitor.read(run/'snapshot.json')
        self.assertEqual(snap['sites']['ta551.info']['metrics']['current7']['impressions'], 7)

    def test_skip_tool_is_explicit_and_does_not_mark_completed(self):
        cfg = self.root/'with-ga4.json'
        cfg.write_text(json.dumps({'sites': {'example.org': {
            'gsc_property': 'sc-domain:example.org', 'ga4_property': '123456'
        }}}), encoding='utf-8')
        run = monitor.init(output=self.root, end=str(self.end), config=cfg, synthetic=True)
        raw = self.root/'ok.json'
        raw.write_text('{"google":[]}', encoding='utf-8')
        monitor.capture(run, 'example.org', 'gsc-current7', raw)
        self.assertEqual(monitor.next_request(run)['label'], 'ga4-current7')
        self.assertEqual(monitor.next_request(run, skip_tools=['analytics_advanced'])['label'],
                         'gsc-previous7')
        self.assertEqual(monitor.status(run)['counts']['missing'], 12)

    def test_all_planned_evidence_completed_resumes_to_complete(self):
        run = monitor.init(output=self.root, end=str(self.end), synthetic=True)
        raw = self.root/'all.json'
        raw.write_text('{"google":[]}', encoding='utf-8')
        plan = monitor.read(run/'plan.json')
        for site in plan['sites']:
            for label in monitor.requests(plan,site):
                monitor.capture(run, site, label, raw)
        result = monitor.status(run)
        self.assertEqual(result['counts']['planned'], 27)
        self.assertEqual(result['counts']['completed'], 27)
        self.assertEqual(result['counts']['missing'], 0)
        self.assertEqual(monitor.next_request(run)['state'], 'structurally_complete_unverified')
        self.assertEqual(monitor.status(run, site='siteprobelab.com')['counts']['planned'], 9)



    def test_imported_evidence_is_never_cryptographically_authenticated(self):
        run = self.new_run()
        raw = self.root/'unverified.json'
        raw.write_text('{"google":[]}', encoding='utf-8')
        path = monitor.capture(run, 'ta551.info', 'gsc-current7', raw)
        imported = monitor.read(path)
        self.assertEqual(imported['source_provenance']['capture_method'], 'file_import')
        self.assertEqual(len(imported['source_provenance']['sha256']), 64)
        self.assertFalse(imported['source_provenance']['authenticated_mcp_origin'])
        # A forged flag does not turn a model-generated file into an MCP receipt.
        imported['source_provenance']['authenticated_mcp_origin'] = True
        monitor.save(path, imported)
        summary = monitor.status(run)
        self.assertEqual(summary['counts']['completed'], 1)
        self.assertEqual(summary['provenance']['authenticated_mcp_responses'], 0)
        self.assertEqual(summary['provenance']['unverified_imports'], 1)
        monitor.render(run)
        report = (run/'summary.md').read_text(encoding='utf-8')
        self.assertIn('NOT proof that an actual MCP provider was called', report)

    def test_claim_blocks_duplicate_mcp_dispatch_until_capture(self):
        run = self.new_run()
        claimed = monitor.next_request(run, claim=True)
        self.assertEqual(claimed['state'], 'claimed')
        self.assertEqual(claimed['label'], 'gsc-current7')
        blocked = monitor.next_request(run, claim=True)
        self.assertEqual(blocked['state'], 'awaiting_capture')
        self.assertEqual(blocked['label'], 'gsc-current7')
        self.assertTrue((run/'inflight.json').exists())
        raw = self.root/'claimed.json'
        raw.write_text('{"google":[]}', encoding='utf-8')
        monitor.capture(run, 'ta551.info', 'gsc-current7', raw)
        following = monitor.next_request(run, claim=True)
        self.assertEqual(following['state'], 'claimed')
        self.assertEqual(following['label'], 'gsc-previous7')
        self.assertEqual(monitor.status(run)['counts']['completed'], 1)

    def test_release_claim_requires_explicit_call_and_preserves_evidence(self):
        run = self.new_run()
        monitor.next_request(run, claim=True)
        self.assertEqual(monitor.next_request(run)['state'], 'awaiting_capture')
        monitor.release_claim(run)
        self.assertFalse((run/'inflight.json').exists())
        self.assertEqual(monitor.next_request(run)['state'], 'pending')
        with self.assertRaisesRegex(ValueError, 'No active claim'):
            monitor.release_claim(run)


if __name__ == '__main__':
    unittest.main()
