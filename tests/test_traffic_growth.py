"""Offline regression tests for the isolated marketing module."""
import csv
import importlib.util
import json
import os
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

    def add_draft(self, draft_id='a' * 16, source=tg.DEMO, platform='linkedin', body='A reviewed exact draft.'):
        value = {'id': draft_id, 'source': source, 'platform': platform, 'body': body,
                 'status': 'draft', 'model': 'fixture-model'}
        tg.save(self.root / 'drafts' / (draft_id + '.json'), value)
        return value

    def ga(self, rows):
        path = self.root / 'input.csv'
        with path.open('w', newline='', encoding='utf-8') as handle:
            writer = csv.writer(handle)
            writer.writerow(tg.GA_FIELDS)
            writer.writerows(rows)
        return path

    def test_atomic_json_and_campaign_writes_preserve_old_data_and_cleanup(self):
        target = self.root / 'inventory.json'
        target.write_text('["old"]', encoding='utf-8')
        cyclic = []
        cyclic.append(cyclic)
        with self.assertRaisesRegex(ValueError, 'serialize'):
            tg.save(target, cyclic)
        self.assertEqual(target.read_text(encoding='utf-8'), '["old"]')
        with patch.object(tg.os, 'replace', side_effect=OSError('simulated replace failure')):
            with self.assertRaisesRegex(ValueError, 'write inventory.json'):
                tg.save(target, ['new'])
        self.assertEqual(target.read_text(encoding='utf-8'), '["old"]')
        self.assertEqual(list(self.root.glob('.inventory.json.*.tmp')), [])

        tg.utm(self.root, tg.DEMO, 'linkedin', 'social', 'lab', 'post1')
        campaigns = (self.root / 'campaigns.csv').read_text(encoding='utf-8')
        with patch.object(tg.os, 'replace', side_effect=OSError('simulated replace failure')):
            with self.assertRaisesRegex(ValueError, 'write campaigns.csv'):
                tg.utm(self.root, tg.DEMO + '?x=1', 'reddit', 'social', 'lab', 'post2')
        self.assertEqual((self.root / 'campaigns.csv').read_text(encoding='utf-8'), campaigns)
        self.assertEqual(list(self.root.glob('.campaigns.csv.*.tmp')), [])

    def test_unique_temporary_name_avoids_predictable_collision(self):
        collision = self.root / '.inventory.json.tmp'
        collision.write_text('preserve me', encoding='utf-8')
        tg.save(self.root / 'inventory.json', ['new'])
        self.assertEqual(tg.read(self.root / 'inventory.json'), ['new'])
        self.assertEqual(collision.read_text(encoding='utf-8'), 'preserve me')
        self.assertEqual(list(self.root.glob('.inventory.json.*.tmp')), [])

    def test_symlink_data_and_destination_paths_are_refused(self):
        target = self.root / 'target.json'
        target.write_text('["safe"]', encoding='utf-8')
        link = self.root / 'linked.json'
        data_link = self.root / 'linked-data'
        def simulated_link(path):
            return path == link or path == data_link
        with patch.object(Path, 'is_symlink', simulated_link):
            with self.assertRaisesRegex(ValueError, 'symlink'):
                tg.save(link, ['unsafe'])
            with self.assertRaisesRegex(ValueError, 'symlink'):
                tg.read(data_link / 'inventory.json', [])
        self.assertEqual(target.read_text(encoding='utf-8'), '["safe"]')

    def test_json_input_limits_and_malformed_depth_are_safe(self):
        path = self.root / 'inventory.json'
        path.write_text('[' + '[' * 1100 + '0' + ']' * 1100 + ']', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'valid UTF-8 JSON'):
            tg.read(path)
        cli = subprocess.run([sys.executable, str(SCRIPT), '--data', str(self.root), 'calendar'],
                             capture_output=True, text=True)
        self.assertEqual(cli.returncode, 1)
        self.assertIn('Operation failed:', cli.stderr)
        self.assertNotIn('Traceback', cli.stderr)
        path.write_bytes(b' ' * (tg.LIMIT + 1))
        with self.assertRaisesRegex(ValueError, '2 MB input limit'):
            tg.read(path)

    def test_invalid_oversized_and_multiline_ga4_csv(self):
        tg.utm(self.root, tg.DEMO, 'linkedin', 'social', 'lab', 'post1')
        good = self.ga([['2026-10-23', 'linkedin\norganic', 'social', 'lab', 'post1', '12']])
        result = tg.import_ga4(self.root, good)
        self.assertEqual(result['rows'][0]['sessionSource'], 'linkedin\norganic')
        previous = tg.read(self.root / 'ga4.json')

        long_value = 'segment-' * 20_000 + '\nquoted continuation'
        result = tg.import_ga4(self.root, self.ga([['2026-10-23', long_value, 'social', 'lab', 'post1', '13']]))
        self.assertEqual(result['rows'][0]['sessionSource'], long_value)
        previous = tg.read(self.root / 'ga4.json')

        invalid = self.root / 'invalid.csv'
        invalid.write_text('date,sessionSource,sessionMedium,sessionCampaignName,sessionManualAdContent,sessions\n'
                           '2026-10-23,"unterminated,social,lab,post1,12', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'CSV'):
            tg.import_ga4(self.root, invalid)
        self.assertEqual(tg.read(self.root / 'ga4.json'), previous)

        huge_field = self.root / 'huge.csv'
        huge_field.write_text(','.join(tg.GA_FIELDS) + '\n2026-10-23,' + 'x' * (tg.MAX_CSV_FIELD + 1) +
                              ',social,lab,post1,12\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'CSV'):
            tg.import_ga4(self.root, huge_field)
        huge_field.write_bytes(b'x' * (tg.LIMIT + 1))
        with self.assertRaisesRegex(ValueError, '2 MB input limit'):
            tg.import_ga4(self.root, huge_field)
        self.assertEqual(tg.read(self.root / 'ga4.json'), previous)

    def test_cli_json_output_is_ascii_safe_but_saved_json_keeps_unicode(self):
        html = self.root / 'unicode.html'
        title = 'Synthetic résumé — sécurité'
        text = 'This synthetic article includes naïve Unicode characters and a sufficiently long sentence.'
        title += ' Привіт'
        text += ' Привіт'
        html.write_text(f'<article><h1>{title}</h1><p>{text}</p></article>', encoding='utf-8')
        env = dict(os.environ, PYTHONIOENCODING='cp1252')
        result = subprocess.run([sys.executable, str(SCRIPT), '--data', str(self.root), 'inventory',
                                 '--url', tg.DEMO, '--html', str(html)], capture_output=True, text=True,
                                encoding='cp1252', env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('\\u00e9', result.stdout)
        self.assertIn('\\u041f\\u0440\\u0438\\u0432\\u0456\\u0442', result.stdout)
        saved = tg.read(self.root / 'inventory.json')[0]
        self.assertEqual(saved['title'], title)
        self.assertIn('Привіт', saved['text'])
        self.assertIn('naïve', saved['text'])

    def test_inventory_preserves_nested_inline_h1_text_and_entities(self):
        html = ('<nav><h1>Navigation title</h1></nav>'
                '<article><h1><span>Wazuh</span> <em>AI</em> <strong>&amp; security</strong> lab</h1>'
                '<p>' + ('Meaningful article content in the main section. ' * 3) + '</p>'
                '<aside><article><h1>Related article title</h1><p>Unrelated sidebar text.</p></article></aside>'
                '</article>')
        item = tg.inventory(self.root, [tg.DEMO], html)[0]
        self.assertEqual(item['title'], 'Wazuh AI & security lab')
        self.assertNotIn('Navigation title', item['title'])
        self.assertNotIn('Related article title', item['text'])

        outside = ('<main><h1><span>Outside</span> <strong>main</strong> &amp; article title</h1>'
                   '<article><p>' + ('This article has its heading in the main container. ' * 3) + '</p></article></main>')
        outside_item = tg.inventory(self.root, ['https://ta551.info/blog/outside-heading/'], outside)[1]
        self.assertEqual(outside_item['title'], 'Outside main & article title')

    def test_local_html_input_limit_and_decode_failures_preserve_inventory(self):
        data = self.root / 'cli-data'
        html_path = self.root / 'bounded.html'
        address = 'https://ta551.info/blog/bounded-html/'
        prefix = ('<article><h1>Bounded fixture</h1><p>' +
                  'This valid local HTML fixture contains enough article text for the inventory parser. ' * 2 +
                  '</p></article>').encode('utf-8')
        comment_open, comment_close = b'<!--', b'-->'
        exact = prefix + comment_open + b'x' * (tg.MAX_HTML_BYTES - len(prefix) - len(comment_open) - len(comment_close)) + comment_close
        self.assertEqual(len(exact), tg.MAX_HTML_BYTES)
        html_path.write_bytes(exact)
        command = [sys.executable, '-B', str(SCRIPT), '--data', str(data), 'inventory', '--url', address, '--html', str(html_path)]
        accepted = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        inventory_path = data / 'inventory.json'
        original = inventory_path.read_bytes()

        html_path.write_bytes(exact + b' ')
        oversized = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(oversized.returncode, 1)
        self.assertIn('HTML exceeds the 2 MiB input limit', oversized.stderr)
        self.assertNotIn('Traceback', oversized.stderr)
        self.assertEqual(inventory_path.read_bytes(), original)

        html_path.write_bytes(b'<article><h1>invalid \xff</h1></article>')
        invalid_utf8 = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(invalid_utf8.returncode, 1)
        self.assertIn('Cannot read valid UTF-8 input from HTML', invalid_utf8.stderr)
        self.assertNotIn('Traceback', invalid_utf8.stderr)
        self.assertEqual(inventory_path.read_bytes(), original)

        missing = self.root / 'does-not-exist.html'
        read_error = subprocess.run(command[:-1] + [str(missing)], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(read_error.returncode, 1)
        self.assertIn('Cannot read valid UTF-8 input from HTML', read_error.stderr)
        self.assertEqual(inventory_path.read_bytes(), original)

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

    def test_inventory_excludes_nested_related_content_and_uses_main_title(self):
        main = 'The main article contains enough useful text to exceed the minimum length required by inventory.'
        fixture = ('<nav><article><h1>Navigation title</h1><p>' + QUOTE + '</p></article></nav>'
                   '<main><h1>Intended page title</h1><article class="post-body"><h1>Article title</h1>'
                   '<p>' + main + '</p><aside><article><h1>Sidebar title</h1><p>' + QUOTE +
                   '</p></article></aside><div class="related-articles"><p>' + QUOTE +
                   '</p></div><footer><p>' + QUOTE + '</p></footer></article></main>')
        article = tg.inventory(self.root, [tg.DEMO], fixture)[0]
        self.assertEqual(article['title'], 'Article title')
        self.assertIn(main, article['text'])
        self.assertNotIn('Navigation title', article['text'] + article['title'])
        self.assertNotIn('Sidebar title', article['text'] + article['title'])
        self.assertNotIn('Ignore', article['text'])
        self.assertEqual(article['text'].count(QUOTE), 0)

    def test_inventory_supports_main_heading_outside_article(self):
        text = 'The main landmark heading is part of a valid article layout and identifies its page title.'
        fixture = '<main><h1>Landmark title</h1><article><p>' + text + '</p></article></main>'
        article = tg.inventory(self.root, [tg.DEMO], fixture)[0]
        self.assertEqual(article['title'], 'Landmark title')
        self.assertIn(text, article['text'])

    def test_aliases_resolve_to_canonical_and_split_cleanly_after_content_change(self):
        text = 'A sufficiently long article paragraph demonstrates canonical alias ownership and source handling.'
        same = '<main><article><h1>Shared title</h1><p>' + text + '</p></article></main>'
        canonical_url = 'https://ta551.info/blog/canonical/'
        alias_url = 'https://ta551.info/blog/alias/'
        tg.inventory(self.root, [canonical_url], same)
        catalog = tg.inventory(self.root, [alias_url], same)
        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0]['aliases'], [alias_url])
        quote = text
        response = {'model': 'test-model', 'choices': [{'finish_reason': 'stop', 'message': {
            'content': json.dumps({'quotes': [quote]})}}]}
        with patch.object(tg, 'request', return_value=json.dumps(response)):
            draft = tg.draft(self.root, alias_url, 'linkedin', 'lmstudio', 'test-model')
        self.assertEqual(draft['source'], canonical_url)
        self.assertEqual(draft['source_sha256'], catalog[0]['sha256'])

        changed_text = 'The changed alias now contains independently distinct source text for this article.'
        changed = '<main><article><h1>New title</h1><p>' + changed_text + '</p></article></main>'
        split = tg.inventory(self.root, [alias_url], changed)
        self.assertEqual(len(split), 2)
        self.assertEqual(split[0]['aliases'], [])
        self.assertEqual(split[1]['url'], alias_url)
        self.assertNotIn(alias_url, split[0]['aliases'])
        repeated = tg.inventory(self.root, [alias_url], changed)
        self.assertEqual(repeated, split)

    def test_alias_duplicate_reimports_are_idempotent(self):
        one = tg.inventory(self.root, ['https://ta551.info/blog/one/'], HTML)
        two = tg.inventory(self.root, ['https://ta551.info/blog/two/'], HTML)
        self.assertEqual(len(two), 1)
        repeated = tg.inventory(self.root, ['https://ta551.info/blog/two/'], HTML)
        self.assertEqual(repeated, two)
        self.assertEqual(two[0]['aliases'], ['https://ta551.info/blog/two/'])

    def test_loopback_only_and_no_redirects(self):
        for value in ['https://api.example.com', 'http://127.0.0.1.evil.test', 'http://user@localhost', 'http://localhost/v1']:
            with self.assertRaises(ValueError):
                tg.local_endpoint(value)
        with self.assertRaises(ValueError):
            tg.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.test')

    def test_local_endpoint_validates_tcp_ports_before_request(self):
        self.assertEqual(tg.local_endpoint('http://localhost:1234'), 'http://localhost:1234')
        self.assertEqual(tg.local_endpoint('http://127.0.0.1:65535'), 'http://127.0.0.1:65535')
        for endpoint in ('http://localhost:bad', 'http://localhost:0', 'http://localhost:65536',
                         'http://localhost:', 'http://[::1]:99999'):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                tg.local_endpoint(endpoint)
        self.inventory()
        for endpoint in ('http://localhost:bad', 'http://localhost:65536'):
            with patch.object(tg, 'request') as call:
                with self.assertRaises(ValueError):
                    tg.draft(self.root, tg.DEMO, 'linkedin', 'lmstudio', 'test-model', endpoint=endpoint)
                call.assert_not_called()

    def test_both_model_protocols_and_platforms(self):
        self.inventory()
        content = json.dumps({'quotes': [QUOTE]})
        for provider in ('ollama', 'lmstudio'):
            response = {'model': 'local-test', 'done': True, 'message': {'content': content}} if provider == 'ollama' else {
                'model': 'local-test', 'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]}
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

    def test_conflicting_utm_tuple_rejected_before_sessions_can_duplicate(self):
        first = tg.utm(self.root, 'https://ta551.info/blog/one/', 'linkedin', 'social', 'lab', 'post1')
        with self.assertRaisesRegex(ValueError, 'different URL'):
            tg.utm(self.root, 'https://ta551.info/blog/two/', 'linkedin', 'social', 'lab', 'post1')
        with (self.root / 'campaigns.csv').open(encoding='utf-8') as handle:
            self.assertEqual(len(list(csv.DictReader(handle))), 1)
        self.assertIn('/blog/one/', first)

    def test_report_rejects_persisted_ambiguous_mapping_with_12_sessions(self):
        tg.utm(self.root, 'https://ta551.info/blog/one/', 'linkedin', 'social', 'lab', 'post1')
        campaign_file = self.root / 'campaigns.csv'
        with campaign_file.open(encoding='utf-8') as handle:
            rows = list(csv.DictReader(handle))
        rows.append({**rows[0], 'url': rows[0]['url'].replace('/one/', '/two/')})
        with campaign_file.open('w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=tg.CAMPAIGN_FIELDS)
            writer.writeheader(); writer.writerows(rows)
        self.ga([['2026-10-23', 'linkedin', 'social', 'lab', 'post1', '12']])
        with self.assertRaisesRegex(ValueError, 'Ambiguous UTM mapping'):
            tg.report(self.root)

    def test_report_rejects_duplicate_persisted_mapping_for_same_url(self):
        tg.utm(self.root, 'https://ta551.info/blog/one/', 'linkedin', 'social', 'lab', 'post1')
        path = self.root / 'campaigns.csv'
        with path.open(encoding='utf-8') as handle:
            rows = list(csv.DictReader(handle))
        rows.append(dict(rows[0]))
        with path.open('w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=tg.CAMPAIGN_FIELDS)
            writer.writeheader(); writer.writerows(rows)
        with self.assertRaisesRegex(ValueError, 'Duplicate UTM mapping'):
            tg.report(self.root)

    def test_calendar_fourteen_days_and_manual_transitions(self):
        self.inventory()
        plan = tg.calendar(self.root, '2026-12-25')
        self.assertEqual(len(plan), 14)
        self.assertEqual(plan[-1]['date'], '2027-01-07')
        with self.assertRaises(ValueError):
            tg.calendar(self.root, entry='1', status='published', reviewed=True)
        with self.assertRaises(ValueError):
            tg.calendar(self.root, entry='1', status='approved', reviewed=True, draft_id='a' * 16)
        self.add_draft()
        tg.calendar(self.root, entry='1', status='approved', reviewed=True, draft_id='a' * 16)
        tg.calendar(self.root, entry='1', status='published', reviewed=True)
        self.assertEqual(tg.calendar(self.root)[0]['status'], 'published')
        published_draft = tg.read(self.root / 'drafts' / ('a' * 16 + '.json'))
        published_draft['body'] += ' Post-publication edit.'
        tg.save(self.root / 'drafts' / ('a' * 16 + '.json'), published_draft)
        recorded = tg.calendar(self.root)[0]
        self.assertEqual(recorded['status'], 'published')
        self.assertFalse(recorded['approval']['valid'])

    def test_calendar_approval_binds_exact_draft_and_invalidates_stale_or_unbound(self):
        self.inventory()
        tg.calendar(self.root, '2026-12-25')
        with self.assertRaisesRegex(ValueError, 'missing or malformed'):
            tg.calendar(self.root, entry='1', status='approved', reviewed=True, draft_id='b' * 16)
        wrong = self.add_draft('b' * 16, source='https://ta551.info/blog/other/', platform='reddit')
        with self.assertRaisesRegex(ValueError, 'does not match'):
            tg.calendar(self.root, entry='1', status='approved', reviewed=True, draft_id=wrong['id'])

        draft = self.add_draft()
        approved = tg.calendar(self.root, entry='1', status='approved', reviewed=True, draft_id=draft['id'])[0]
        expected = __import__('hashlib').sha256(draft['body'].encode('utf-8')).hexdigest()
        self.assertEqual(approved['approval']['draft_id'], draft['id'])
        self.assertEqual(approved['approval']['content_sha256'], expected)

        draft['body'] += ' Edited after approval.'
        tg.save(self.root / 'drafts' / (draft['id'] + '.json'), draft)
        with self.assertRaisesRegex(ValueError, 'invalidated'):
            tg.calendar(self.root, entry='1', status='published', reviewed=True)
        stale = tg.calendar(self.root)[0]
        self.assertEqual(stale['status'], 'draft')
        self.assertNotIn('approval', stale)
        self.assertIn('approval_invalidated_at', stale)

        tg.calendar(self.root, entry='1', status='approved', reviewed=True, draft_id=draft['id'])
        (self.root / 'drafts' / (draft['id'] + '.json')).unlink()
        missing = tg.calendar(self.root)[0]
        self.assertEqual(missing['status'], 'draft')
        self.assertNotIn('approval', missing)

        legacy = tg.read(self.root / 'calendar.json')
        legacy[0]['status'] = 'approved'
        legacy[0].pop('approval', None)
        tg.save(self.root / 'calendar.json', legacy)
        self.assertEqual(tg.calendar(self.root)[0]['status'], 'draft')
        legacy[0]['status'] = 'approved'
        tg.save(self.root / 'calendar.json', legacy)
        report = tg.report(self.root)
        self.assertEqual(report['calendar_statuses']['approved'], 0)
        self.assertEqual(tg.read(self.root / 'calendar.json')[0]['status'], 'draft')

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
