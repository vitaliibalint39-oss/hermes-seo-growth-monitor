"""Offline regression tests for the isolated marketing module."""
import csv
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'marketing/traffic-growth/traffic_growth.py'
spec = importlib.util.spec_from_file_location('traffic_growth', SCRIPT)
tg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tg)
QUOTE = 'This synthetic article describes a local lab and does not establish production readiness.'
HTML = '<nav>Ignore</nav><article><h1>Synthetic lab</h1><p>' + QUOTE + '</p><script>bad()</script></article>'


class TrafficTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def inventory(self):
        return tg.inventory(self.root, [tg.DEMO], HTML)[0]

    def ga(self, rows):
        path = self.root / 'input.csv'
        with path.open('w', newline='', encoding='utf-8') as handle:
            writer = csv.writer(handle)
            writer.writerow(tg.GA_FIELDS)
            writer.writerows(rows)
        return path

    def test_inventory_normalizes_urls_and_deduplicates_content(self):
        self.inventory()
        tg.inventory(self.root, [tg.DEMO + '?utm_source=test#x'], HTML)
        catalog = tg.inventory(self.root, ['https://ta551.info/blog/alias/'], HTML)
        self.assertEqual(len(catalog), 1)
        self.assertEqual(len(catalog[0]['aliases']), 1)
        self.assertNotIn('bad()', catalog[0]['text'])
        self.assertNotIn('Ignore', catalog[0]['text'])

    def test_inventory_updates_source_revision(self):
        old = self.inventory()
        updated = tg.inventory(self.root, [tg.DEMO], HTML.replace('local lab', 'isolated lab'))
        self.assertEqual(old['id'], updated[0]['id'])
        self.assertNotEqual(old['sha256'], updated[0]['sha256'])

    def test_inventory_rejects_empty_or_wrong_host(self):
        for address, html in [(tg.DEMO, '<h1>Not an article</h1>'), ('https://evil.test/blog/x/', HTML)]:
            with self.assertRaises(ValueError):
                tg.inventory(self.root, [address], html)
        self.assertFalse((self.root / 'inventory.json').exists())

    def test_loopback_only_and_no_redirects(self):
        for value in ['https://api.example.com', 'http://127.0.0.1.evil.test', 'http://user@localhost', 'http://localhost/v1']:
            with self.assertRaises(ValueError):
                tg.local_endpoint(value)
        with self.assertRaises(ValueError):
            tg.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.test')

    def test_both_model_protocols_and_platforms(self):
        self.inventory()
        content = json.dumps({'quotes': [QUOTE]})
        for provider in ('ollama', 'lmstudio'):
            response = {'done': True, 'message': {'content': content}} if provider == 'ollama' else {
                'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]}
            for platform in tg.PLATFORMS:
                with patch.object(tg, 'request', return_value=json.dumps(response)) as call:
                    result = tg.draft(self.root, tg.DEMO, platform, provider, 'local-test')
                self.assertEqual(result['status'], 'draft')
                self.assertIn(QUOTE, result['body'])
                self.assertFalse(call.call_args.args[1]['stream'])
                self.assertIn('/api/chat' if provider == 'ollama' else '/v1/chat/completions', call.call_args.args[0])

    def test_fabricated_claim_and_partial_quote_rejected(self):
        article = self.inventory()
        for result in [{'quotes': ['Traffic increased by 999 percent.']}, {'quotes': [QUOTE[:40]]},
                       {'quotes': [QUOTE], 'body': 'Invented result'}, {'quotes': [QUOTE, QUOTE]}]:
            with self.assertRaises(ValueError):
                tg.validate_quotes(result, article)

    def test_truncated_or_invalid_model_output_not_saved(self):
        self.inventory()
        for response in [{'done': False}, {'done': True, 'message': {'content': 'not JSON'}}]:
            with patch.object(tg, 'request', return_value=json.dumps(response)):
                with self.assertRaises(ValueError):
                    tg.draft(self.root, tg.DEMO, 'linkedin', 'ollama', 'test')
        self.assertFalse((self.root / 'drafts').exists())

    def test_utm_idempotence_and_validation(self):
        for _ in range(2):
            value = tg.utm(self.root, tg.DEMO + '?old=1', 'linkedin', 'social', 'lab', 'post1')
        self.assertIn('utm_campaign=lab', value)
        self.assertNotIn('old=', value)
        with (self.root / 'campaigns.csv').open() as handle:
            self.assertEqual(len(list(csv.DictReader(handle))), 1)
        with self.assertRaises(ValueError):
            tg.utm(self.root, tg.DEMO, '=formula', 'social', 'lab', 'post1')

    def test_calendar_fourteen_days_and_manual_transitions(self):
        self.inventory()
        plan = tg.calendar(self.root, '2026-12-25')
        self.assertEqual(len(plan), 14)
        self.assertEqual(plan[-1]['date'], '2027-01-07')
        with self.assertRaises(ValueError):
            tg.calendar(self.root, entry='1', status='published', reviewed=True)
        with self.assertRaises(ValueError):
            tg.calendar(self.root, entry='1', status='approved')
        tg.calendar(self.root, entry='1', status='approved', reviewed=True)
        tg.calendar(self.root, entry='1', status='published', reviewed=True)
        self.assertEqual(tg.calendar(self.root)[0]['status'], 'published')

    def test_ga_import_is_snapshot_and_missing_is_unknown(self):
        tg.utm(self.root, tg.DEMO, 'linkedin', 'social', 'lab', 'post1')
        self.assertIsNone(tg.report(self.root)['campaigns'][0]['sessions'])
        path = self.ga([['20261023', 'linkedin', 'social', 'lab', 'post1', '12']])
        for _ in range(2):
            result = tg.report(self.root, path)
        self.assertEqual(result['campaigns'][0]['sessions'], 12)
        path = self.ga([['2026-10-23', 'reddit', 'social', 'lab', 'post1', '0']])
        self.assertIsNone(tg.report(self.root, path)['campaigns'][0]['sessions'])

    def test_ga_rejects_duplicates_invalid_dates_negative_and_missing(self):
        valid = ['2026-10-23', 'linkedin', 'social', 'lab', 'post1', '12']
        for rows in [[valid, valid], [valid[:-1] + ['-1']], [valid[:-1] + ['']],
                     [['2026-99-23'] + valid[1:]]]:
            with self.assertRaises(ValueError):
                tg.import_ga4(self.root, self.ga(rows))

    def test_ga_display_headers_bom_comments_and_zero(self):
        path = self.root / 'display.csv'
        path.write_text('# GA4 export\n' + ','.join(tg.GA_ALIASES) +
                        '\n20261023,linkedin,social,lab,post1,0\n', encoding='utf-8-sig')
        tg.utm(self.root, tg.DEMO, 'linkedin', 'social', 'lab', 'post1')
        self.assertEqual(tg.report(self.root, path)['campaigns'][0]['sessions'], 0)

    def test_cli_offline_inventory_calendar_report(self):
        html = self.root / 'article.html'
        html.write_text(HTML, encoding='utf-8')
        for args in [('inventory', '--url', tg.DEMO, '--html', str(html)),
                     ('calendar', '--start', '2026-10-23'), ('report',)]:
            result = subprocess.run([sys.executable, str(SCRIPT), '--data', str(self.root), *args],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            json.loads(result.stdout)


if __name__ == '__main__':
    unittest.main()
