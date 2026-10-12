"""Keep credentials out of logs.

Some upstream APIs only take their key as a query parameter, and a URL is what
an HTTP error message, and so a logged traceback, prints. ``redact_secrets``
blanks the value of any key-, token- or secret-named parameter in a string;
the app logger's formatter runs every line through it as a backstop."""

from __future__ import annotations

import re

_SECRET_PARAM = re.compile(r"\b((?:api_?)?key|token|secret|signature)=[^&\s'\"]+", re.IGNORECASE)


def redact_secrets(text: str) -> str:
    return _SECRET_PARAM.sub(r"\1=REDACTED", text)
