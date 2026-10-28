"""B4 路由、外部解析与资源边界回归；所有上游由 MockTransport 接管。"""

import asyncio
import gzip
import json
import logging
import zlib
from copy import deepcopy

import httpx
import pytest
from app import config, main
from app.web_query import WebQueryClient, WebQueryError, result_url

WEATHER = {
    "current_condition": [
        {
            "temp_C": "20",
            "FeelsLikeC": "19",
            "humidity": "50",
            "weatherDesc": [{"value": "Sunny"}],
            "lang_zh": [{"value": "晴"}],
            "localObsDateTime": "2040-01-01 12:00 PM",
        }
    ],
    "nearest_area": [{"areaName": [{"value": "Beijing"}], "country": [{"value": "China"}]}],
}
SEARCH = """<html><div class="result">
<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python.org%2F3%2F&amp;rut=discard">Python <b>Docs</b></a>
<a class="result__snippet">Official <b>Python</b> documentation &amp; guides.</a></div>
<div><a class="result__a" href="https://www.python.org/">Python</a><div class="result__snippet">Language</div></div>
<a class="result__a" href="https://www.python.org/">Duplicate</a>
<a class="result__a" href="javascript:alert(1)">Unsafe</a></html>"""
HEADERS = {"X-API-Key": "test-token"}


@pytest.fixture
def web_app(monkeypatch, client):
    requests = []
    state = {"weather": WEATHER, "search": SEARCH, "status": 200}

    def upstream(request):
        requests.append(request)
        content = state["weather"] if request.url.host == "wttr.in" else state["search"]
        if isinstance(content, Exception):
            raise content
        if isinstance(content, dict):
            content = json.dumps(content, ensure_ascii=False)
        raw = content.encode("utf-8") if isinstance(content, str) else content
        return httpx.Response(
            state["status"], stream=httpx.ByteStream(raw), headers=state.get("headers", {})
        )

    adapter = WebQueryClient(httpx.MockTransport(upstream))
    monkeypatch.setattr(main.app.state, "web_query_client", adapter)
    yield client, requests, state
    client.portal.call(adapter.close)


def test_weather_summary_metadata_and_request_boundaries(web_app):
    client, calls, _ = web_app
    response = client.get("/api/tools/weather", params={"city": " 北京 "}, headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "北京"
    assert "20°C" in data["summary"] and "Beijing, China" in data["summary"]
    assert data["observed_at"] == WEATHER["current_condition"][0]["localObsDateTime"]
    assert data["fetched_at"].endswith("+00:00")
    assert response.headers["cache-control"] == "no-store"
    assert len(calls) == 1 and calls[0].url.host == "wttr.in"
    assert calls[0].url.params["format"] == "j1"
    assert "X-API-Key" not in calls[0].headers
    assert calls[0].headers["accept-encoding"] == "gzip, deflate"


def test_search_plain_summary_sources_dedup_and_limit(web_app):
    client, calls, _ = web_app
    response = client.get(
        "/api/tools/search", params={"q": " Python  docs ", "limit": 2}, headers=HEADERS
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok" and len(data["results"]) == 2
    assert data["query"] == "Python docs"
    assert data["results"][0] == {
        "title": "Python Docs",
        "url": "https://docs.python.org/3/",
        "snippet": "Official Python documentation & guides.",
    }
    assert "<b>" not in data["summary"] and "javascript" not in data["summary"]
    assert len(calls) == 1 and calls[0].url.host == "html.duckduckgo.com"
    assert calls[0].url.params["q"] == "Python docs"
    one = client.get("/api/tools/search", params={"q": "docs", "limit": 1}, headers=HEADERS)
    assert len(one.json()["results"]) == 1


@pytest.mark.parametrize("path", ["/api/tools/weather?city=Beijing", "/api/tools/search?q=docs"])
@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "invalid"}])
def test_authentication_precedes_upstream(web_app, path, headers):
    client, calls, _ = web_app
    assert client.get(path, headers=headers).status_code == 401
    assert calls == []


@pytest.mark.parametrize(
    "path,params",
    [
        ("weather", {"city": ""}),
        ("weather", {"city": "  "}),
        ("weather", {"city": "a" * 81}),
        ("weather", {"city": "http://127.0.0.1"}),
        ("weather", {"city": "@localhost"}),
        ("weather", {"city": "../:help"}),
        ("weather", {"city": "Beijing?format=html"}),
        ("weather", {"city": "127.0.0.1"}),
        ("weather", {"city": ".,-"}),
        ("search", {"q": ""}),
        ("search", {"q": "  "}),
        ("search", {"q": "a" * 201}),
        ("search", {"q": "foo\nbar"}),
        ("search", {"q": "foo\u202ebar"}),
        ("search", {"q": "docs", "limit": 0}),
        ("search", {"q": "docs", "limit": 6}),
    ],
)
def test_invalid_input_never_calls_upstream(web_app, path, params):
    client, calls, _ = web_app
    assert client.get("/api/tools/" + path, params=params, headers=HEADERS).status_code == 422
    assert calls == []


@pytest.mark.parametrize(
    "code,expected", [(202, 503), (403, 503), (429, 503), (500, 502), (302, 502)]
)
def test_upstream_status_and_redirect_not_followed(web_app, code, expected):
    client, calls, state = web_app
    state.update(status=code, headers={"location": "http://127.0.0.1/private"})
    response = client.get("/api/tools/search?q=docs", headers=HEADERS)
    assert response.status_code == expected
    assert len(calls) == 1
    assert "private" not in response.text


@pytest.mark.parametrize(
    "error,status", [(httpx.ReadTimeout("sensitive"), 504), (httpx.ConnectError("sensitive"), 502)]
)
def test_network_failures_are_sanitized_without_retries(web_app, error, status):
    client, calls, state = web_app
    state["search"] = error
    response = client.get("/api/tools/search?q=docs", headers=HEADERS)
    assert response.status_code == status
    assert "sensitive" not in response.text and len(calls) == 1


@pytest.mark.parametrize(
    "content,expected,code",
    [
        ('<div class="no-results">No results</div>', 200, "empty"),
        ('<form id="challenge-form">Captcha</form>', 503, "search_challenge"),
        ("<html>maintenance</html>", 502, "search_invalid_response"),
        (
            '<a class="result__a" href="file:///etc/passwd">Unsafe</a>',
            502,
            "search_invalid_response",
        ),
        (b"\xff\xfe", 502, "upstream_invalid_encoding"),
    ],
)
def test_empty_challenge_and_invalid_search_are_distinct(web_app, content, expected, code):
    client, _, state = web_app
    state["search"] = content
    response = client.get("/api/tools/search?q=docs", headers=HEADERS)
    assert response.status_code == expected
    assert response.json().get("status", response.json().get("detail")) == code


@pytest.mark.parametrize("value", [None, True, "NaN", "inf", "bad", "999"])
def test_bad_weather_numbers_rejected(web_app, value):
    client, _, state = web_app
    state["weather"] = deepcopy(WEATHER)
    state["weather"]["current_condition"][0]["temp_C"] = value
    response = client.get("/api/tools/weather?city=Beijing", headers=HEADERS)
    assert response.status_code == 502 and response.json()["detail"] == "weather_invalid_response"


@pytest.mark.parametrize(
    "content",
    ["not json", "[]", "{}", '{"current_condition": []}', '{"current_condition": [null]}'],
)
def test_weather_structure_failure_is_clear(web_app, content):
    client, _, state = web_app
    state["weather"] = content
    assert client.get("/api/tools/weather?city=Beijing", headers=HEADERS).status_code == 502


def test_response_budget_and_encoding(web_app, monkeypatch):
    client, _, state = web_app
    monkeypatch.setattr(config, "WEB_QUERY_MAX_BYTES", 100)
    assert (
        client.get("/api/tools/search?q=docs", headers=HEADERS).json()["detail"]
        == "upstream_response_too_large"
    )
    state.update(search=b"", headers={"content-encoding": "br"})
    assert (
        client.get("/api/tools/search?q=docs", headers=HEADERS).json()["detail"]
        == "upstream_unsupported_encoding"
    )


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "https://user:password@example.com/",  # pragma: allowlist secret -- Fake URL for rejection test
        "https://127.0.0.1/",
        "http://localhost/",
        "https://host.local/",
        "https://example.com:9000/",
        "https://[broken/",
        "https://example.com/\nfoo",
    ],
)
def test_unsafe_links_are_discarded(value):
    assert result_url(value) is None


def test_query_log_redaction(web_app, caplog):
    client, _, _ = web_app
    with caplog.at_level(logging.INFO, logger="httpx"):
        client.get("/api/tools/search?q=private-example-query", headers=HEADERS)
    assert "private-example-query" not in caplog.text
    assert "[REDACTED]" in caplog.text


def test_total_timeout_releases_connection_slot(monkeypatch):
    monkeypatch.setattr(config, "WEB_QUERY_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(config, "WEB_QUERY_MAX_CONCURRENT", 1)

    async def scenario():
        async def slow(request):
            await asyncio.Event().wait()

        adapter = WebQueryClient(httpx.MockTransport(slow))
        try:
            results = await asyncio.gather(
                adapter.search("one", 1), adapter.search("two", 1), return_exceptions=True
            )
            assert all(
                isinstance(result, WebQueryError) and result.code == "upstream_timeout"
                for result in results
            )
            assert not adapter._slots.locked()
        finally:
            await adapter.close()

    asyncio.run(scenario())


def test_streaming_limit_closes_body(monkeypatch):
    monkeypatch.setattr(config, "WEB_QUERY_MAX_BYTES", 100)
    closed = []

    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(100):
                yield b"x" * 60

        async def aclose(self):
            closed.append(True)

    async def scenario():
        adapter = WebQueryClient(
            httpx.MockTransport(lambda request: httpx.Response(200, stream=Chunks()))
        )
        try:
            with pytest.raises(WebQueryError, match="upstream_response_too_large"):
                await adapter.search("docs", 1)
            assert closed == [True]
        finally:
            await adapter.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("encoding,compress", [("gzip", gzip.compress), ("deflate", zlib.compress)])
def test_compressed_search_is_decoded_with_size_budget(web_app, monkeypatch, encoding, compress):
    client, _, state = web_app
    state.update(search=compress(SEARCH.encode()), headers={"content-encoding": encoding})
    assert client.get("/api/tools/search?q=docs", headers=HEADERS).status_code == 200
    monkeypatch.setattr(config, "WEB_QUERY_MAX_BYTES", 1000)
    state["search"] = compress(b"x" * 100_000)
    response = client.get("/api/tools/search?q=docs", headers=HEADERS)
    assert response.status_code == 502
    assert response.json()["detail"] == "upstream_response_too_large"


@pytest.mark.parametrize(
    "content",
    [b"not gzip", gzip.compress(SEARCH.encode())[:-5], gzip.compress(SEARCH.encode()) + b"junk"],
)
def test_corrupted_compression_is_rejected(web_app, content):
    client, _, state = web_app
    state.update(search=content, headers={"content-encoding": "gzip"})
    response = client.get("/api/tools/search?q=docs", headers=HEADERS)
    assert response.status_code == 502
    assert response.json()["detail"] == "upstream_invalid_compression"
