"""只读联网查询适配器：固定上游、有限资源、纯文本摘要与可追溯来源。"""

import asyncio
import ipaddress
import json
import math
import re
import unicodedata
import zlib
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import parse_qs, quote, urlencode, urlsplit

import httpx
from pydantic import BaseModel, Field

from . import config


class WebQueryError(Exception):
    """仅暴露稳定错误码，不包含查询、上游响应或代理凭证。"""

    def __init__(self, code: str, status: int = 502) -> None:
        super().__init__(code)
        self.code, self.status = code, status


class SearchItem(BaseModel):
    """文本和链接是外部数据；客户端不得将其作为 HTML 或指令执行。"""

    title: str
    url: str
    snippet: str


class QueryResult(BaseModel):
    """查询时间与天气观测时间分开，搜索无结果是正常的 empty 状态。"""

    status: Literal["ok", "empty"]
    query: str
    provider: str
    summary: str
    source_url: str
    fetched_at: str
    observed_at: str | None = None
    results: list[SearchItem] = Field(default_factory=list)


def clean_text(value: str, limit: int) -> str:
    """规范空白，移除终端控制及格式字符，并限制摘要长度。"""
    text = "".join(
        char for char in value if not unicodedata.category(char).startswith("C") or char.isspace()
    )
    return " ".join(text.split())[:limit]


def result_url(value: str) -> str | None:
    """仅解码 DuckDuckGo 跳转链接，不请求结果页面；剔除危险链接。"""
    if value.startswith("//"):
        value = "https:" + value
    elif value.startswith("/l/?"):
        value = "https://duckduckgo.com" + value
    try:
        parsed = urlsplit(value)
        if parsed.hostname in {"duckduckgo.com", "html.duckduckgo.com"} and parsed.path == "/l/":
            value = parse_qs(parsed.query).get("uddg", [""])[0]
            parsed = urlsplit(value)
        host = parsed.hostname
        if (
            len(value) > 2048
            or any(char.isspace() or unicodedata.category(char).startswith("C") for char in value)
            or parsed.scheme not in {"https", "http"}
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 80, 443}
            or host == "localhost"
            or host.endswith((".local", ".localhost"))
        ):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
    except ValueError:
        return None
    return value


class SearchParser(HTMLParser):
    """解析无 JavaScript 的 HTML 结果；结构变化或验证码不能冒充零结果。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, str]] = []
        self.empty = False
        self.blocked = False
        self._current: dict[str, str] | None = None
        self._field: str | None = None
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """只接收结果标题和摘要，不将任意页面文本作为搜索答案。"""
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        if values.get("id") in {"challenge-form", "anomaly-form"} or "anomaly-modal" in classes:
            self.blocked = True
        if "no-results" in classes or "result--no-result" in classes:
            self.empty = True
        if self._field:
            if tag not in {"br", "img", "hr", "input", "meta", "link", "wbr"}:
                self._depth += 1
            return
        if tag == "a" and "result__a" in classes:
            url = result_url(values.get("href") or "")
            self._current = {"title": "", "url": url, "snippet": ""} if url else None
            if self._current is not None:
                self.items.append(self._current)
                self._field, self._depth = "title", 1
        elif "result__snippet" in classes and self._current is not None:
            self._field, self._depth = "snippet", 1

    def handle_endtag(self, tag: str) -> None:
        """保留嵌套强调标签中的文字，外层结束才停止收集。"""
        if self._field:
            self._depth -= 1
            if self._depth <= 0:
                self._field = None

    def handle_data(self, data: str) -> None:
        """HTML 标记不会进入文本摘要。"""
        if self._field and self._current is not None:
            self._current[self._field] += data


def _weather_text(value: object) -> str:
    """读取 wttr 的文本数组，非法结构返回空值供调用处拒绝。"""
    if isinstance(value, list) and value and isinstance(value[0], dict):
        text = value[0].get("value")
        if isinstance(text, str):
            return clean_text(text, 120)
    return ""


def _number(value: object, minimum: float, maximum: float) -> str:
    """拒绝缺失、布尔、非有限和明显非法的天气数值。"""
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise WebQueryError("weather_invalid_response")
    try:
        number = float(value)
    except (ValueError, OverflowError):
        raise WebQueryError("weather_invalid_response") from None
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise WebQueryError("weather_invalid_response")
    return f"{number:g}"


class WebQueryClient:
    """复用 HTTP 连接；并发、排队与读取均受总超时约束，没有自动重试。"""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport
        self._http: httpx.AsyncClient | None = None
        self._slots = asyncio.Semaphore(config.WEB_QUERY_MAX_CONCURRENT)

    async def close(self) -> None:
        """随应用 lifespan 释放连接。"""
        if self._http is not None:
            await self._http.aclose()

    async def _read(self, url: str, params: dict[str, str]) -> str:
        async with self._slots:
            if self._http is None:
                self._http = httpx.AsyncClient(
                    transport=self._transport,
                    timeout=config.WEB_QUERY_TIMEOUT_SECONDS,
                    follow_redirects=False,
                    limits=httpx.Limits(max_connections=config.WEB_QUERY_MAX_CONCURRENT),
                    headers={
                        "User-Agent": "Intelligent-Desktop-Pet/1.0 (course project)",
                        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
                        "Accept-Encoding": "gzip, deflate",
                    },
                )
            async with self._http.stream("GET", url, params=params) as response:
                if response.status_code in {202, 403, 429}:
                    raise WebQueryError("upstream_unavailable", 503)
                if response.status_code != 200:
                    raise WebQueryError("upstream_http_error")
                encoding = response.headers.get("content-encoding", "identity").lower()
                if encoding not in {"identity", "gzip", "deflate"}:
                    raise WebQueryError("upstream_unsupported_encoding")
                decoder = (
                    None
                    if encoding == "identity"
                    else zlib.decompressobj(31 if encoding == "gzip" else 15)
                )
                body = bytearray()
                raw_size = 0
                # 使用原始流和有输出上限的解压，避免先无限解压再检查大小。
                try:
                    async for chunk in response.aiter_raw():
                        raw_size += len(chunk)
                        if raw_size > config.WEB_QUERY_MAX_BYTES:
                            raise WebQueryError("upstream_response_too_large")
                        if decoder is not None:
                            chunk = decoder.decompress(
                                chunk, config.WEB_QUERY_MAX_BYTES - len(body) + 1
                            )
                        body.extend(chunk)
                        if len(body) > config.WEB_QUERY_MAX_BYTES:
                            raise WebQueryError("upstream_response_too_large")
                    if decoder is not None and (not decoder.eof or decoder.unused_data):
                        raise WebQueryError("upstream_invalid_compression")
                except zlib.error:
                    raise WebQueryError("upstream_invalid_compression") from None
                try:
                    return body.decode("utf-8")
                except UnicodeError:
                    raise WebQueryError("upstream_invalid_encoding") from None

    async def _fetch(self, url: str, params: dict[str, str]) -> str:
        try:
            return await asyncio.wait_for(self._read(url, params), config.WEB_QUERY_TIMEOUT_SECONDS)
        except (asyncio.TimeoutError, httpx.TimeoutException):
            raise WebQueryError("upstream_timeout", 504) from None
        except httpx.RequestError:
            raise WebQueryError("upstream_network_error") from None

    async def weather(self, city: str) -> QueryResult:
        """天气 JSON 转摘要，明确显示上游解析的位置及观测时间。"""
        url = config.WEB_WEATHER_URL + "/" + quote(city, safe="")
        body = await self._fetch(url, {"format": "j1", "lang": "zh", "m": ""})
        try:
            data = json.loads(body)
            current = data["current_condition"][0]
            area = data["nearest_area"][0]
            place = _weather_text(area.get("areaName"))
            country = _weather_text(area.get("country"))
            description = _weather_text(current.get("lang_zh")) or _weather_text(
                current.get("weatherDesc")
            )
            temperature = _number(current.get("temp_C"), -100, 70)
            feels = _number(current.get("FeelsLikeC"), -150, 100)
            humidity = _number(current.get("humidity"), 0, 100)
            observed = current.get("localObsDateTime") or current.get("observation_time")
            if (
                not place
                or not description
                or not isinstance(observed, str)
                or not observed.strip()
            ):
                raise WebQueryError("weather_invalid_response")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError, RecursionError):
            raise WebQueryError("weather_invalid_response") from None
        location = ", ".join(part for part in (place, country) if part)
        return QueryResult(
            status="ok",
            query=city,
            provider="wttr.in",
            summary=f"{location}：{description}，气温 {temperature}°C，体感 {feels}°C，湿度 {humidity}%。",
            source_url=url,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            observed_at=clean_text(observed, 80),
        )

    async def search(self, query: str, limit: int) -> QueryResult:
        """提取 DuckDuckGo HTML 标题、摘要及来源，不抓取搜索结果页面。"""
        body = await self._fetch(config.WEB_SEARCH_URL, {"q": query})
        parser = SearchParser()
        parser.feed(body)
        if parser.blocked:
            raise WebQueryError("search_challenge", 503)
        items = []
        seen = set()
        for item in parser.items:
            title = clean_text(item["title"], 200)
            if title and item["url"] not in seen:
                seen.add(item["url"])
                items.append(
                    SearchItem(
                        title=title, url=item["url"], snippet=clean_text(item["snippet"], 500)
                    )
                )
            if len(items) >= limit:
                break
        if not items and not parser.empty:
            raise WebQueryError("search_invalid_response")
        summary = "\n".join(
            f"{index}. {item.title}：{item.snippet}\n{item.url}"
            for index, item in enumerate(items, 1)
        )
        return QueryResult(
            status="ok" if items else "empty",
            query=query,
            provider="DuckDuckGo",
            summary=summary or "未找到相关结果。",
            results=items,
            source_url=config.WEB_SEARCH_URL + "?" + urlencode({"q": query}),
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )


def validate_input(value: str, *, city: bool = False) -> str:
    """城市只允许地名字符，拒绝 wttr 特殊路径；关键词禁止控制字符。"""
    if any(unicodedata.category(char).startswith("C") for char in value):
        raise ValueError("输入不能包含控制字符")
    value = " ".join(value.split())
    if not value:
        raise ValueError("输入不能为空")
    if city and not all(char.isalpha() or char.isspace() or char in "-'.," for char in value):
        raise ValueError("city 仅接受城市名，不接受 URL、IP 或特殊路径")
    if city and not re.search(r"[^\W\d_]", value, re.UNICODE):
        raise ValueError("city 必须包含城市名称")
    return value
