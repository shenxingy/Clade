import logging
import io
from config import DEFAULT_LOG_FORMAT

def test_default_log_format_includes_name():
    assert "%(name)s" in DEFAULT_LOG_FORMAT
    logger = logging.getLogger("test.module")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter(DEFAULT_LOG_FORMAT))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.info("msg")
    assert "test.module" in stream.getvalue()
