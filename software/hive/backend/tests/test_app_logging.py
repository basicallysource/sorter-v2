"""The `app` logger must have somewhere to write.

Until 2026-08-20 it did not. uvicorn configures its own loggers and leaves the
root alone, so every logger call under app/ was dropped on the floor — five
workers announcing themselves at startup, and warnings like "color model has no
usable classes" that were supposed to be the first sign of trouble. Nothing had
ever reached `docker logs`, and nobody noticed because absence of a log line
looks exactly like absence of a problem.
"""

from __future__ import annotations

import io
import logging

import app.main  # noqa: F401  — configures app logging on import


def test_app_logger_has_a_handler():
    logger = logging.getLogger("app")
    assert logger.handlers, "no handler means every app log line is silently dropped"
    assert logger.level <= logging.INFO


def test_app_log_lines_actually_come_out():
    # Swap the handler's own stream rather than using capsys: the handler binds
    # to stderr at import time, long before capsys replaces it, so capsys never
    # sees these lines even when they are emitted correctly.
    logger = logging.getLogger("app")
    handler = next(h for h in logger.handlers if isinstance(h, logging.StreamHandler))
    original, buffer = handler.stream, io.StringIO()
    handler.setStream(buffer)
    try:
        logging.getLogger("app.services.server_health").info("canary-%s", 42)
    finally:
        handler.setStream(original)

    written = buffer.getvalue()
    assert "canary-42" in written, "a child of `app` must reach the handler"
    assert "app.services.server_health" in written, "the formatter should name the logger"


def test_only_the_app_logger_was_configured():
    # Configuring root instead would unmute botocore and friends on a box that
    # does not need the volume, so the handler must live on `app` and nowhere
    # else. Asserted by identity rather than by counting handlers elsewhere:
    # pytest owns root, and libraries legitimately install their own NullHandler.
    logger = logging.getLogger("app")
    handler = next(h for h in logger.handlers if isinstance(h, logging.StreamHandler))
    assert handler not in logging.getLogger().handlers
    assert handler not in logging.getLogger("botocore").handlers
