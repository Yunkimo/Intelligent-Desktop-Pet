"""避免 query token 出现在 Uvicorn 握手与访问日志中。"""

import logging
import re
from copy import copy


def redact_query(message: str) -> str:
    """移除完整查询串，不依赖参数名称或编码方式。"""
    return re.sub(r"\?[^\s\"']*", "?[REDACTED]", message)


class QueryTokenFilter(logging.Filter):
    """移除日志 URL 的整个 query，兼容重复及编码后的参数名。"""

    def filter(self, record: logging.LogRecord) -> bool:
        """兼容访问日志的五字段参数和彩色日志的独立模板。"""
        if (
            record.name == "uvicorn.access"
            and isinstance(record.args, tuple)
            and len(record.args) == 5
        ):
            # AccessFormatter 还需解包这些字段；只替换请求路径中的查询串。
            client, method, path, version, status = record.args
            record.args = (client, method, redact_query(str(path)), version, status)
            return True
        if isinstance(getattr(record, "color_message", None), str):
            colored = copy(record)
            colored.msg = record.color_message
            record.color_message = redact_query(colored.getMessage())
        record.msg = redact_query(record.getMessage())
        record.args = ()
        return True


def install_log_filters() -> None:
    """为应用使用的服务器日志添加幂等过滤器。"""
    for name in ("uvicorn.error", "uvicorn.access", "httpx"):
        logger = logging.getLogger(name)
        if not any(isinstance(item, QueryTokenFilter) for item in logger.filters):
            logger.addFilter(QueryTokenFilter())
