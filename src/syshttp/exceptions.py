"""What syshttp raises when something goes wrong at run time.

A caller's mistake -- a bad argument, two options that contradict -- is a plain
``ValueError`` or ``TypeError``, not one of these. Every message names the
setting or the key involved and never a secret's value."""

from __future__ import annotations

__all__ = (
    "ConfigurationError",
    "HookError",
    "NegotiateUnavailableError",
    "NegotiationError",
    "ResponseError",
    "SysHTTPError",
)


class SysHTTPError(Exception):
    """The base of every error syshttp raises for what went wrong at run time
    (proxylib's own errors pass through as they are)."""


class ConfigurationError(SysHTTPError, ValueError):
    """A setting, or a stored credential, that cannot be used: a malformed
    environment variable, a hook that is not loadable, a token with a line
    break in it. The message names the variable or the key."""


class HookError(SysHTTPError, RuntimeError):
    """A ``_PY`` URL hook failed. The hook's own exception is the ``__cause__``."""


class ResponseError(SysHTTPError, ValueError):
    """A response whose body is not what the helper was asked for (JSON that is
    not JSON)."""


class NegotiationError(SysHTTPError):
    """A Negotiate or NTLM handshake that did not authenticate: the server or
    proxy refused the credentials, answered out of turn, closed the
    connection, sent a token that is too large or not valid, or asked for more
    legs than ``SYSHTTP_NEGOTIATE_MAX_LEGS`` allows, or the library that makes
    the tokens failed; also a handshake that would cross plain http without
    ``SYSHTTP_NEGOTIATE_PLAIN_HTTP``, refused before any token is made. The
    message names the host and never a credential or a token."""


class NegotiateUnavailableError(NegotiationError, ImportError):
    """A Negotiate or NTLM handshake was asked for and the library behind it
    cannot be used: the ``negotiate`` extra is not installed (or its library
    does not import). The message names the extra to install."""
