"""Search contract and failures with a mocked HTTP transport; no robot or API calls."""
import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import realtime_web_search as search


def response_payload():
    return {"status": "completed", "output": [
        {"type": "web_search_call", "status": "completed"},
        {"type": "message", "role": "assistant", "content": [
            {"type": "output_text", "text": "Heute geöffnet. [Quelle]", "annotations": [
                {"type": "url_citation", "start_index": 16, "end_index": 24,
                 "url": "https://example.com/hours", "title": "Öffnungszeiten"}]}]},
    ]}


class SearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_forced_search_uses_server_key_and_only_query_then_preserves_citations(self):
        async def handler(request):
            self.assertEqual(str(request.url), search.RESPONSES_URL)
            self.assertEqual(request.headers['authorization'], 'Bearer private-test-key')
            body = json.loads(request.content)
            self.assertEqual(body['input'], 'Öffnungszeiten heute?')
            self.assertFalse(body['store'])
            self.assertEqual(body['tool_choice'], 'required')
            self.assertEqual(body['tools'][0]['type'], 'web_search')
            self.assertNotIn('previous_response_id', body)
            return httpx.Response(200, json=response_payload())
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch.object(search.realtime_voice, '_api_key', return_value='private-test-key'), \
             patch.object(search.httpx, 'AsyncClient', return_value=client):
            result = await search.search(' Öffnungszeiten heute? ')
        self.assertEqual(result['citations'][0]['url'], 'https://example.com/hours')
        cite = result['citations'][0]
        self.assertEqual(result['answer'][cite['start']:cite['end']], '[Quelle]')
        self.assertNotIn('private-test-key', json.dumps(result))

    async def test_http_errors_do_not_expose_provider_body_or_key(self):
        for code in (401, 429, 500):
            client = httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(code, text='secret provider details')))
            with patch.object(search.realtime_voice, '_api_key', return_value='private-test-key'), \
                 patch.object(search.httpx, 'AsyncClient', return_value=client):
                with self.assertRaises(RuntimeError) as raised:
                    await search.search('Wetter Berlin')
            self.assertNotIn('secret', str(raised.exception))
            self.assertNotIn('private-test-key', str(raised.exception))

    async def test_timeout_and_cancellation(self):
        async def slow(request):
            await asyncio.sleep(2)
        client = httpx.AsyncClient(transport=httpx.MockTransport(slow))
        with patch.object(search.realtime_voice, '_api_key', return_value='test'), \
             patch.object(search.httpx, 'AsyncClient', return_value=client), \
             patch.object(search, 'TIMEOUT_S', 0.01):
            with self.assertRaisesRegex(RuntimeError, 'Zeitlimit'):
                await search.search('Wetter')

    async def test_blank_or_oversize_query_never_reaches_network(self):
        with patch.object(search.httpx, 'AsyncClient') as client:
            for query in ('   ', 'a' * 501):
                with self.assertRaises(ValueError):
                    await search.search(query)
            client.assert_not_called()

    def test_missing_search_sources_or_incomplete_response_is_not_presented_as_success(self):
        for kind in ('no_search', 'no_citation', 'incomplete', 'unsafe_url'):
            payload = response_payload()
            if kind == 'no_search': payload['output'].pop(0)
            elif kind == 'incomplete': payload['status'] = 'incomplete'
            elif kind == 'no_citation': payload['output'][1]['content'][0]['annotations'] = []
            else: payload['output'][1]['content'][0]['annotations'][0]['url'] = 'javascript:alert(1)'
            with self.assertRaises(RuntimeError):
                search.search_result(payload, 'query')


class SearchEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_endpoint_requires_header_and_never_accesses_hardware(self):
        import asr_web
        from fastapi import HTTPException
        model = asr_web.RealtimeWebSearchRequest(query='Wetter Berlin')
        with patch.object(asr_web.realtime_web_search, 'search', new_callable=AsyncMock,
                          return_value={'status': 'ok'}) as lookup, \
             patch.object(asr_web, 'conversation_motion_status', side_effect=AssertionError('hardware')), \
             patch.object(asr_web, 'camera_session', None), \
             patch.object(asr_web, 'policy_session', None):
            with self.assertRaises(HTTPException) as denied:
                await asr_web.conversation_realtime_search(SimpleNamespace(headers={}), model)
            self.assertEqual(denied.exception.status_code, 403)
            lookup.assert_not_called()
            response = await asr_web.conversation_realtime_search(
                SimpleNamespace(headers={'x-so101-conversation': 'realtime-tool'}), model)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            lookup.assert_awaited_once_with('Wetter Berlin')


if __name__ == '__main__':
    unittest.main()
