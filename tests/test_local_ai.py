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

    def envelope(self, provider, content=None):
        message = {'content': content if content is not None else json.dumps({'quotes': [QUOTE]})}
        if provider == 'ollama':
            return {'model': 'test', 'done': True, 'done_reason': 'stop', 'message': message,
                    'eval_count': 30, 'prompt_eval_count': 100}
        return {'model': 'test', 'choices': [{'finish_reason': 'stop', 'message': message}],
                'usage': {'completion_tokens': 30, 'completion_tokens_details': {'reasoning_tokens': 0}}}

    def generate(self, provider, response, **kwargs):
        with patch.object(tg, 'request', return_value=json.dumps(response)) as call:
            result = tg.draft(self.root, tg.DEMO, 'linkedin', provider, 'test', **kwargs)
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
        self.assertEqual(result, second)
        self.assertEqual(len(list((self.root / 'drafts').glob('*.json'))), 1)

    def test_legacy_ollama_done_does_not_invent_finish_reason(self):
        response = self.envelope('ollama')
        del response['done_reason']
        result, _ = self.generate('ollama', response)
        self.assertIsNone(result['generation']['finish_reason'])
