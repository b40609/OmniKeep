"""A keyless connection sends no Authorization header; a real key is sent as a bearer token.

The OpenAI SDK builds requests with its own httpx variant, so the hook is checked directly
and the real-key path through a mock transport.
"""
import asyncio

import httpx
from openai import AsyncOpenAI

from app.providers.openai_compatible import (PLACEHOLDER_KEY, OpenAICompatibleProvider, _drop_placeholder_auth,
                                             client_auth)


def test_placeholder_auth_header_is_dropped_before_sending():
    request = httpx.Request("GET", "https://gateway.test/v1/models",
                            headers={"Authorization": f"Bearer {PLACEHOLDER_KEY}"})
    asyncio.run(_drop_placeholder_auth(request))
    assert "authorization" not in request.headers


def test_a_real_bearer_is_left_alone_by_the_hook():
    request = httpx.Request("GET", "https://gateway.test/v1/models", headers={"Authorization": "Bearer sk-real"})
    asyncio.run(_drop_placeholder_auth(request))
    assert request.headers["authorization"] == "Bearer sk-real"


def test_keyless_clients_get_the_hook_and_real_keys_do_not():
    for key in (PLACEHOLDER_KEY, ""):
        auth = client_auth(key)
        assert auth["api_key"] == PLACEHOLDER_KEY
        assert _drop_placeholder_auth in auth["http_client"].event_hooks["request"]
    assert client_auth("sk-test-1234567890") == {"api_key": "sk-test-1234567890"}


def test_real_key_is_sent_as_bearer():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization"))
        return httpx.Response(200, json={"object": "list", "data": []})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = AsyncOpenAI(base_url="https://gateway.test/v1", max_retries=0, http_client=http,
                                 **client_auth("sk-test-1234567890"))
            await client.models.list()

    asyncio.run(run())
    assert seen == ["Bearer sk-test-1234567890"]


def test_keyless_provider_uses_the_placeholder():
    provider = OpenAICompatibleProvider(base_url="http://127.0.0.1:11434/v1", api_key=PLACEHOLDER_KEY, model="m")
    assert provider.api_key == PLACEHOLDER_KEY
