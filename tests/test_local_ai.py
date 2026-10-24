"""Provider compatibility and fail-closed local inference regressions."""
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from test_traffic_growth import tg, HTML, QUOTE


class LocalAITests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        tg.inventory(self.root, [tg.DEMO], HTML)

    def envelope(self, provider, content=None, model='test'):
        message = {'content': content if content is not None else json.dumps({'quotes': [QUOTE]})}
        if provider == 'ollama':
            return {'model': model, 'done': True, 'done_reason': 'stop', 'message': message,
                    'eval_count': 30, 'prompt_eval_count': 100}
        return {'model': model, 'choices': [{'finish_reason': 'stop', 'message': message}],
                'usage': {'completion_tokens': 30, 'completion_tokens_details': {'reasoning_tokens': 0}}}

    def generate(self, provider, response, model='test', **kwargs):
        with patch.object(tg, 'request', return_value=json.dumps(response)) as call:
            result = tg.draft(self.root, tg.DEMO, 'linkedin', provider, model, **kwargs)
        return result, call.call_args

    def test_provider_format_and_thinking_matrix(self):
        for provider in ('lmstudio', 'ollama'):
            for mode in ('json_schema', 'json', 'text'):
                for thinking in ('default', 'off', 'on'):
                    with self.subTest(provider=provider, mode=mode, thinking=thinking):
                        _, call = self.generate(provider, self.envelope(provider), response_format=mode,
                                                thinking=thinking, max_tokens=4096, timeout=45)
                        payload = call.args[1]
                        self.assertEqual(call.kwargs['timeout'], 45)
                        if provider == 'lmstudio':
                            self.assertEqual(payload['max_tokens'], 4096)
                            self.assertEqual(payload.get('reasoning_effort'),
                                             {'default': None, 'off': 'none', 'on': 'on'}[thinking])
                            self.assertEqual(payload['response_format']['type'],
                                             'json_object' if mode == 'json' else mode)
                            self.assertNotIn('think', payload)
                        else:
                            self.assertEqual(payload['options']['num_predict'], 4096)
                            self.assertEqual(payload.get('think'),
                                             {'default': None, 'off': False, 'on': True}[thinking])
                            self.assertNotIn('reasoning_effort', payload)
                            if mode == 'text':
                                self.assertNotIn('format', payload)
                            elif mode == 'json':
                                self.assertEqual(payload['format'], 'json')
                            else:
                                self.assertEqual(payload['format']['properties']['quotes']['items']['enum'], [QUOTE])

    def test_nonstop_and_missing_completion_rejected_without_saving(self):
        for provider in ('lmstudio', 'ollama'):
            for reason in ('length', 'tool_calls', 'error', ''):
                response = self.envelope(provider)
                if provider == 'lmstudio':
                    response['choices'][0]['finish_reason'] = reason
                else:
                    response['done_reason'] = reason
                with self.assertRaises(ValueError):
                    self.generate(provider, response)
            for response in ({}, [], {'error': 'unsupported format'}):
                with self.assertRaises(ValueError):
                    self.generate(provider, response)
        self.assertFalse((self.root / 'drafts').exists())

    def test_model_id_requires_exact_match_and_presence(self):
        for provider in ('lmstudio', 'ollama'):
            for returned in ('other-model', 'test:latest'):
                with self.assertRaisesRegex(ValueError, 'Model ID mismatch'):
                    self.generate(provider, self.envelope(provider, model=returned))
            response = self.envelope(provider)
            response.pop('model')
            with self.assertRaisesRegex(ValueError, 'omitted its model ID'):
                self.generate(provider, response)
        self.assertFalse((self.root / 'drafts').exists())

    def test_identical_content_from_different_models_is_one_draft_with_both_provenances(self):
        first, _ = self.generate('lmstudio', self.envelope('lmstudio', model='model-a'), model='model-a')
        second, _ = self.generate('lmstudio', self.envelope('lmstudio', model='model-b'), model='model-b')
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(first['body'], second['body'])
        self.assertEqual(first['model'], 'model-a')
        self.assertEqual([r['requested_model'] for r in second['model_provenance']], ['model-a', 'model-b'])
        self.assertEqual(len(list((self.root / 'drafts').glob('*.json'))), 1)

    def test_duplicate_text_from_distinct_source_urls_keeps_distinct_identity(self):
        body = 'Same rendered text.'
        self.assertNotEqual(tg.draft_identity('https://ta551.info/blog/one/', 'a' * 64, 'linkedin', body),
                            tg.draft_identity('https://ta551.info/blog/two/', 'a' * 64, 'linkedin', body))
        self.assertNotEqual(tg.draft_identity('https://ta551.info/blog/one/', 'a' * 64, 'linkedin', body),
                            tg.draft_identity('https://ta551.info/blog/one/', 'b' * 64, 'linkedin', body))

    def test_schema_constraints_enforced_in_every_format(self):
        invalid = ['{"quotes": [], "quotes": ["duplicate key"]}', '{', 'null',
                   json.dumps({'quotes': [QUOTE], 'extra': True}), json.dumps({'quotes': []}),
                   json.dumps({'quotes': [QUOTE] * 4}), json.dumps({'quotes': [123]}),
                   json.dumps({'quotes': [QUOTE, QUOTE]}), json.dumps({'quotes': [QUOTE[:30]]})]
        for provider in ('lmstudio', 'ollama'):
            for mode in ('json_schema', 'json', 'text'):
                for content in invalid:
                    with self.assertRaises(ValueError):
                        self.generate(provider, self.envelope(provider, content), response_format=mode)
        self.assertFalse((self.root / 'drafts').exists())

    def test_thinking_off_must_be_honored(self):
        for provider in ('lmstudio', 'ollama'):
            response = self.envelope(provider)
            message = response['message'] if provider == 'ollama' else response['choices'][0]['message']
            message['thinking' if provider == 'ollama' else 'reasoning_content'] = 'reasoning'
            with self.assertRaisesRegex(ValueError, 'not honored'):
                self.generate(provider, response, thinking='off')
        response = self.envelope('lmstudio')
        response['usage']['completion_tokens_details']['reasoning_tokens'] = 50
        with self.assertRaisesRegex(ValueError, 'not honored'):
            self.generate('lmstudio', response, thinking='off')
        self.assertFalse((self.root / 'drafts').exists())

    def test_empty_refused_tool_and_malformed_message_rejected(self):
        for provider in ('lmstudio', 'ollama'):
            for message in ({'content': ''}, {'content': ' ', 'refusal': 'no'},
                            {'content': '{}', 'tool_calls': [{}]}, None, {'content': 10}):
                response = self.envelope(provider)
                if provider == 'ollama':
                    response['message'] = message
                else:
                    response['choices'][0]['message'] = message
                with self.assertRaises(ValueError):
                    self.generate(provider, response)
        self.assertFalse((self.root / 'drafts').exists())

    def test_http_timeout_and_connection_errors_never_save_draft(self):
        errors = [(urllib.error.HTTPError('http://localhost', 400, 'Bad request', {}, io.BytesIO(b'secret')), 'HTTP 400'),
                  (TimeoutError(), 'timed out'),
                  (urllib.error.URLError(TimeoutError()), 'timed out'),
                  (urllib.error.URLError(ConnectionRefusedError()), 'Connection failed')]
        for provider in ('lmstudio', 'ollama'):
            for error, expected in errors:
                opener = MagicMock()
                opener.open.side_effect = error
                with patch.object(tg.http, 'build_opener', return_value=opener):
                    with self.assertRaisesRegex(ValueError, expected) as caught:
                        tg.draft(self.root, tg.DEMO, 'linkedin', provider, 'test')
                self.assertNotIn('secret', str(caught.exception))
        self.assertFalse((self.root / 'drafts').exists())

    def test_invalid_configuration_fails_before_request(self):
        for kwargs in ({'thinking': 'low'}, {'response_format': 'yaml'}, {'timeout': 0},
                       {'timeout': 601}, {'max_tokens': 0}, {'max_tokens': 32769}):
            with patch.object(tg, 'request') as call:
                with self.assertRaises(ValueError):
                    tg.draft(self.root, tg.DEMO, 'linkedin', 'lmstudio', 'test', **kwargs)
                call.assert_not_called()

    def test_dedup_preserves_original_status_and_provenance(self):
        result, _ = self.generate('lmstudio', self.envelope('lmstudio'), thinking='off')
        self.assertEqual(result['generation']['finish_reason'], 'stop')
        self.assertEqual(result['generation']['usage']['completion_tokens'], 30)
        self.assertEqual(result['status'], 'draft')
        path = self.root / 'drafts' / (result['id'] + '.json')
        result['status'] = 'approved'
        tg.save(path, result)
        second, _ = self.generate('lmstudio', self.envelope('lmstudio'), thinking='off')
        self.assertEqual(second['status'], 'approved')
        self.assertEqual(second['id'], result['id'])
        self.assertEqual(len(second['model_provenance']), 2)
        self.assertEqual(len(list((self.root / 'drafts').glob('*.json'))), 1)

    def test_legacy_ollama_done_does_not_invent_finish_reason(self):
        response = self.envelope('ollama')
        del response['done_reason']
        result, _ = self.generate('ollama', response)
        self.assertIsNone(result['generation']['finish_reason'])

    def test_valid_source_hash_is_verified_before_model_call(self):
        item = tg.read(self.root / 'inventory.json')[0]
        self.assertEqual(item['sha256'], __import__('hashlib').sha256(item['text'].encode('utf-8')).hexdigest())
        with patch.object(tg, 'request', return_value=json.dumps(self.envelope('lmstudio'))) as call:
            result = tg.draft(self.root, tg.DEMO, 'linkedin', 'lmstudio', 'test')
        self.assertEqual(result['source_sha256'], item['sha256'])
        call.assert_called_once()

    def test_modified_source_text_fails_before_inference_or_saving(self):
        path = self.root / 'inventory.json'
        item = tg.read(path)[0]
        item['text'] += '\nTampered source text.'
        path.write_text(json.dumps([item]), encoding='utf-8')
        with patch.object(tg, 'request') as call:
            with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch.*rerun inventory'):
                tg.draft(self.root, tg.DEMO, 'linkedin', 'lmstudio', 'test')
        call.assert_not_called()
        self.assertFalse((self.root / 'drafts').exists())

    def test_malformed_inventory_records_fail_before_inference(self):
        path = self.root / 'inventory.json'
        for item in ({'url': tg.DEMO}, {'url': tg.DEMO, 'title': 'Missing body'},
                     {'url': tg.DEMO, 'title': 'Title', 'text': 9, 'sha256': 'abc'},
                     {'url': tg.DEMO, 'title': 'Title', 'text': 'x' * 100,
                      'sha256': '0' * 64, 'aliases': 'not-a-list'}):
            path.write_text(json.dumps([item]), encoding='utf-8')
            with patch.object(tg, 'request') as call:
                with self.assertRaisesRegex(ValueError, 'inventory'):
                    tg.draft(self.root, tg.DEMO, 'linkedin', 'lmstudio', 'test')
            call.assert_not_called()
        self.assertFalse((self.root / 'drafts').exists())
