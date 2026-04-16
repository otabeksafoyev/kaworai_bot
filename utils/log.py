"""
Logging helpers.

The project uses the stdlib :mod:`logging` module. Root logging is configured
in ``bot.py`` at startup; every other module should obtain a module-scoped
logger via ``logging.getLogger(__name__)``.

This file exists as a single place to centralize future logging policy
(e.g. JSON logs, Sentry handlers) without having to edit every call site.
For now it is intentionally minimal.
"""

import logging


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped :class:`logging.Logger`.

    Thin wrapper around :func:`logging.getLogger` — kept so the rest of the
    codebase can swap in structured logging, Sentry, etc. without edits.
    """
    return logging.getLogger(name)
