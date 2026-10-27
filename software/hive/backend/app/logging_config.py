import logging

from app.services.redact import redact_secrets


def configure_app_logging() -> None:
    """Give the ``app`` logger somewhere to write.

    uvicorn configures its own loggers and deliberately leaves the root logger
    alone, so nothing in this package had a handler and all 50-odd logger calls
    under app/ went nowhere — including the background workers announcing
    themselves at startup, and warnings like "color model has no usable classes"
    that were meant to be the first sign something was wrong. None of it has
    ever appeared in `docker logs`.

    Configured on the ``app`` logger rather than the root on purpose: root would
    also unmute botocore and friends, and this box does not need that volume.
    uvicorn's own loggers do not propagate, so its access lines are unaffected.
    Called by both entrypoints: the web app (app.main) and the worker process
    (app.worker), which has no uvicorn at all.
    """
    app_logger = logging.getLogger("app")
    app_logger.setLevel(logging.INFO)
    if not app_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
        app_logger.addHandler(handler)


class RedactingFormatter(logging.Formatter):
    """Blanks key=/token= values in every line, tracebacks included: an HTTP
    error from an API that takes its key in the URL prints that URL."""

    def format(self, record: logging.LogRecord) -> str:
        return redact_secrets(super().format(record))
