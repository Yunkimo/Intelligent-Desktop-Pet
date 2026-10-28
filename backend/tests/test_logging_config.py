"""使用 Uvicorn 真实格式器验证终端日志和查询脱敏的兼容性。"""

import logging

import pytest
from app.logging_config import QueryTokenFilter
from uvicorn.logging import AccessFormatter, DefaultFormatter


@pytest.mark.parametrize("use_colors", [False, True])
@pytest.mark.parametrize(
    "message,color_message,args,expected",
    [
        (
            "Started server process [%d]",
            "Started server process [\x1b[36m%d\x1b[0m]",
            (12345,),
            "12345",
        ),
        (
            "Uvicorn running on %s://%s:%d",
            "Uvicorn running on \x1b[1m%s://%s:%d\x1b[0m",
            ("http", "127.0.0.1", 18004),
            "http://127.0.0.1:18004",
        ),
    ],
)
def test_startup_interpolation_with_terminal_colors(
    use_colors: bool, message: str, color_message: str, args: tuple, expected: str
) -> None:
    record = logging.LogRecord("uvicorn.error", logging.INFO, "", 0, message, args, None)
    record.color_message = color_message
    log_filter = QueryTokenFilter()
    assert log_filter.filter(record)
    assert log_filter.filter(record)
    output = DefaultFormatter("%(levelprefix)s %(message)s", use_colors=use_colors).format(record)
    assert expected in output
    assert "%s" not in output and "%d" not in output


@pytest.mark.parametrize("use_colors", [False, True])
@pytest.mark.parametrize(
    "path,expected_path",
    [
        ("/api/health", "/api/health"),
        ("/ws?%74oken=private-value&token=private-value", "/ws?[REDACTED]"),
        ("/api/tools/search?q=private-value", "/api/tools/search?[REDACTED]"),
    ],
)
def test_access_formatter_preserves_request_fields_and_redacts_queries(
    use_colors: bool, path: str, expected_path: str
) -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:12345", "GET", path, "1.1", 200),
        None,
    )
    log_filter = QueryTokenFilter()
    assert log_filter.filter(record)
    assert log_filter.filter(record)
    output = AccessFormatter(
        '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
        use_colors=use_colors,
    ).format(record)
    assert record.args == ("127.0.0.1:12345", "GET", expected_path, "1.1", 200)
    assert f"GET {expected_path} HTTP/1.1" in output
    assert "200 OK" in output and "127.0.0.1:12345" in output
    assert "private-value" not in output
    assert "private-value" not in repr(record.__dict__)


@pytest.mark.parametrize("use_colors", [False, True])
def test_colored_message_cannot_bypass_query_redaction(use_colors: bool) -> None:
    record = logging.LogRecord(
        "uvicorn.error",
        logging.INFO,
        "",
        0,
        'Request "%s"',
        ("https://example.com/?q=private-value",),
        None,
    )
    record.color_message = '\x1b[32mRequest "%s"\x1b[0m'
    QueryTokenFilter().filter(record)
    output = DefaultFormatter("%(message)s", use_colors=use_colors).format(record)
    assert "https://example.com/?[REDACTED]" in output
    assert "private-value" not in output
    assert "private-value" not in repr(record.__dict__)
