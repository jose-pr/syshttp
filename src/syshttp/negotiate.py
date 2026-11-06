"""Negotiate (SPNEGO) and NTLM authentication: which servers and proxies a
client answers a challenge for, with whose credentials, and the tokens.

Nothing here is on by default. ``HTTPTransport`` (and so ``HTTPClient`` and
``fetch``) answers a ``401`` with ``WWW-Authenticate: Negotiate`` or ``NTLM``,
or a ``407`` with ``Proxy-Authenticate``, only for a host the settings name,
and only with the ``negotiate`` extra installed (``pip install
"syshttp[negotiate]"``: pyspnego, which speaks SSPI on Windows, GSSAPI
(Kerberos) where ``gssapi`` is installed, and NTLM itself).

Settings are read through an :class:`~syshttp.env.HTTPEnv`, each name under
each of its prefixes; below they are named as written. An explicit argument of
:class:`Negotiate` beats the variable, which beats the default.

``SYSHTTP_NEGOTIATE``
    The servers whose challenge is answered: a comma list of host names, a
    ``*.suffix`` for every host below a domain, ``*`` for every host. Unset:
    none.
``SYSHTTP_PROXY_NEGOTIATE``
    The same for proxies, by the proxy's host.
``SYSHTTP_NEGOTIATE_USER`` and ``SYSHTTP_NEGOTIATE_PASSWORD`` (a secret)
    An explicit identity (``DOMAIN\\user`` or ``user@REALM``) for every host
    the lists allow. Both or neither; unset, the logon session's identity
    (SSPI) or the Kerberos credential cache is used.
``SYSHTTP_NEGOTIATE_PLAIN_HTTP``
    A boolean: also authenticate over plain http to a host that is not
    loopback. Off by default; on, each such host is logged as a weakening.
``SYSHTTP_NEGOTIATE_MAX_LEGS``
    Most authenticated requests of one handshake (default
    :data:`DEFAULT_MAX_LEGS`).
``SYSHTTP_NEGOTIATE_MAX_TOKEN``
    Most bytes of one token, sent or received (default
    :data:`DEFAULT_MAX_TOKEN`).
"""

from __future__ import annotations

import dataclasses
import ipaddress
import typing as _ty

from .env import HTTPEnv
from .exceptions import ConfigurationError, NegotiateUnavailableError, NegotiationError

__all__ = (
    "DEFAULT_MAX_LEGS",
    "DEFAULT_MAX_TOKEN",
    "NEGOTIATE",
    "NEGOTIATE_MAX_LEGS",
    "NEGOTIATE_MAX_TOKEN",
    "NEGOTIATE_PASSWORD",
    "NEGOTIATE_PLAIN_HTTP",
    "NEGOTIATE_USER",
    "PROXY_NEGOTIATE",
    "Negotiate",
    "NegotiateSettings",
    "has_negotiate",
)

NEGOTIATE = "SYSHTTP_NEGOTIATE"
PROXY_NEGOTIATE = "SYSHTTP_PROXY_NEGOTIATE"
NEGOTIATE_USER = "SYSHTTP_NEGOTIATE_USER"
NEGOTIATE_PASSWORD = "SYSHTTP_NEGOTIATE_PASSWORD"
NEGOTIATE_PLAIN_HTTP = "SYSHTTP_NEGOTIATE_PLAIN_HTTP"
NEGOTIATE_MAX_LEGS = "SYSHTTP_NEGOTIATE_MAX_LEGS"
NEGOTIATE_MAX_TOKEN = "SYSHTTP_NEGOTIATE_MAX_TOKEN"

DEFAULT_MAX_LEGS = 5
"""Authenticated requests one handshake may send. NTLM takes two, Kerberos
one or two."""

DEFAULT_MAX_TOKEN = 65536
"""Bytes of one token, sent or received: the size of the header line
`http.client` reads."""

INSTALL = 'pip install "syshttp[negotiate]"'

_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off")
_PROTOCOLS = ("negotiate", "ntlm")


def has_negotiate() -> bool:
    """Whether the library behind Negotiate and NTLM imports (the
    ``negotiate`` extra is installed and works)."""
    try:
        _spnego()
    except NegotiateUnavailableError:
        return False
    return True


def _spnego() -> _ty.Any:
    """The pyspnego module; `NegotiateUnavailableError` naming the extra when it
    is missing, and the import's own error when it is there and fails."""
    try:
        import spnego
    except ModuleNotFoundError as error:
        if error.name not in ("spnego", None) and not str(error.name).startswith("spnego."):
            raise NegotiateUnavailableError(
                "Negotiate cannot load pyspnego: %s is missing (%s)" % (error.name, INSTALL)
            ) from error
        raise NegotiateUnavailableError("Negotiate and NTLM need the 'negotiate' extra: %s" % INSTALL) from None
    except ImportError as error:
        raise NegotiateUnavailableError(
            "Negotiate cannot load pyspnego although it is installed (%s: %s)" % (type(error).__name__, error)
        ) from error
    return spnego


def is_loopback(host: str) -> bool:
    """Whether `host` is `localhost` or a loopback address."""
    host = host.strip("[]").rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _canonical(host: str) -> str:
    return host.strip().strip("[]").rstrip(".").lower()


def _pattern(text: str, source: str, error: _ty.Type[ValueError]) -> str:
    pattern = _canonical(text)
    bare = pattern[2:] if pattern.startswith("*.") else pattern
    if pattern != "*" and (not bare or "*" in bare or any(ch.isspace() or ch in "/@,;" for ch in bare)):
        raise error("%s lists host names, '*.suffix' or '*', not %r" % (source, text))
    return pattern


def _patterns(value: "str | _ty.Iterable[str]", source: str, error: _ty.Type[ValueError]) -> "tuple[str, ...]":
    if isinstance(value, str):
        value = value.split(",")
    found: "list[str]" = []
    for item in value:
        if not isinstance(item, str):
            raise TypeError("%s lists host names" % source)
        if item.strip():
            pattern = _pattern(item, source, error)
            if pattern not in found:
                found.append(pattern)
    return tuple(found)


def _matches(patterns: "tuple[str, ...]", host: str) -> bool:
    host = _canonical(host)
    for pattern in patterns:
        if pattern == "*" or pattern == host:
            return True
        if pattern.startswith("*.") and host.endswith(pattern[1:]) and len(host) > len(pattern) - 1:
            return True
    return False


def _flag(value: str, variable: str) -> bool:
    lowered = value.lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise ConfigurationError("%s must be one of %s, not %r" % (variable, "/".join(_TRUE + _FALSE), value))


def _count(value: str, variable: str, minimum: int) -> int:
    try:
        number = int(value)
    except ValueError:
        number = minimum - 1
    if number < minimum:
        raise ConfigurationError("%s must be a whole number of %d or more, not %r" % (variable, minimum, value))
    return number


@dataclasses.dataclass(frozen=True)
class NegotiateSettings:
    """What a :class:`Negotiate` decides by, read once: the host patterns
    answered for servers and for proxies, whether plain http to a host that is
    not loopback is allowed, the leg and token limits, and whether an explicit
    identity is set (never the identity itself)."""

    hosts: "tuple[str, ...]"
    proxies: "tuple[str, ...]"
    plain_http: bool
    max_legs: int
    max_token: int
    explicit_credentials: bool


class Negotiate:
    """The Negotiate and NTLM policy of a transport: which hosts and proxies
    it answers a challenge for, and with which identity.

    `hosts` and `proxies` are comma lists or iterables of host names
    (``*.suffix`` for a domain, ``*`` for all); `username` and `password` an
    explicit identity, both or neither; `plain_http` allows a host that is not
    loopback over plain http; `max_legs` and `max_token` bound a handshake. An
    argument left at `None` reads its variable (see the module), then the
    default, at each use. A caller's bad argument is `ValueError` or
    `TypeError`; a bad variable is `ConfigurationError` naming it.

    The password is held and never shown: not in `repr()`, a message or a log.
    Nothing is read, imported or sent until a server or proxy challenges."""

    def __init__(
        self,
        hosts: "str | _ty.Iterable[str] | None" = None,
        proxies: "str | _ty.Iterable[str] | None" = None,
        *,
        username: "str | None" = None,
        password: "str | None" = None,
        plain_http: "bool | None" = None,
        max_legs: "int | None" = None,
        max_token: "int | None" = None,
        env: "HTTPEnv | None" = None,
    ):
        self._hosts = None if hosts is None else _patterns(hosts, "hosts", ValueError)
        self._proxies = None if proxies is None else _patterns(proxies, "proxies", ValueError)
        if (username is None) != (password is None):
            raise ValueError("username and password are given together or not at all")
        for name, value in (("username", username), ("password", password)):
            if value is not None:
                if not isinstance(value, str):
                    raise TypeError("%s is a str" % name)
                if any(ch in value for ch in "\r\n\0"):
                    raise ValueError("%s contains a carriage return, line feed or NUL character" % name)
        if plain_http is not None and not isinstance(plain_http, bool):
            raise TypeError("plain_http is a bool")
        for name, limit in (("max_legs", max_legs), ("max_token", max_token)):
            if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
                raise ValueError("%s is a whole number of 1 or more" % name)
        self._username = username
        self._password = password
        self._plain_http = plain_http
        self._max_legs = max_legs
        self._max_token = max_token
        self._env = HTTPEnv() if env is None else env

    def __repr__(self) -> str:
        return "Negotiate(hosts=%r, proxies=%r, credentials=%s)" % (
            self._hosts,
            self._proxies,
            "explicit" if self._username is not None else "logon",
        )

    def _variable(self, setting: str) -> str:
        found = self._env.find(setting)
        return found[0] if found else self._env.name(setting)

    def _identity(self) -> "tuple[str, str] | None":
        if self._username is not None:
            return self._username, _ty.cast(str, self._password)
        user = self._env.find(NEGOTIATE_USER)
        secret = self._env.find(NEGOTIATE_PASSWORD)
        if user is None and secret is None:
            return None
        if user is None or secret is None:
            raise ConfigurationError(
                "%s and %s are set together or not at all"
                % (self._variable(NEGOTIATE_USER), self._variable(NEGOTIATE_PASSWORD))
            )
        for found in (user, secret):
            if any(ch in found[1] for ch in "\r\n\0"):
                raise ConfigurationError("%s contains a carriage return, line feed or NUL character" % found[0])
        return user[1], secret[1]

    def _listed(self, given: "tuple[str, ...] | None", setting: str) -> "tuple[str, ...]":
        if given is not None:
            return given
        found = self._env.find(setting)
        return () if found is None else _patterns(found[1], found[0], ConfigurationError)

    def settings(self) -> NegotiateSettings:
        """The policy as it reads now: the arguments, else the variables, else
        the defaults. `ConfigurationError` for a variable that cannot be used."""
        plain = self._plain_http
        if plain is None:
            found = self._env.find(NEGOTIATE_PLAIN_HTTP)
            plain = _flag(found[1], found[0]) if found else False
        legs, token = self._max_legs, self._max_token
        if legs is None:
            found = self._env.find(NEGOTIATE_MAX_LEGS)
            legs = _count(found[1], found[0], 1) if found else DEFAULT_MAX_LEGS
        if token is None:
            found = self._env.find(NEGOTIATE_MAX_TOKEN)
            token = _count(found[1], found[0], 1) if found else DEFAULT_MAX_TOKEN
        return NegotiateSettings(
            hosts=self._listed(self._hosts, NEGOTIATE),
            proxies=self._listed(self._proxies, PROXY_NEGOTIATE),
            plain_http=plain,
            max_legs=legs,
            max_token=token,
            explicit_credentials=self._identity() is not None,
        )

    def wants(self, host: str, *, proxy: bool = False) -> bool:
        """Whether a challenge from `host` (a proxy's host when `proxy`) is
        answered."""
        settings = self.settings()
        return _matches(settings.proxies if proxy else settings.hosts, host)

    def _context(self, host: str, protocol: str) -> _ty.Any:
        """A pyspnego client context for ``HTTP/<host>``, speaking `protocol`
        (``negotiate`` or ``ntlm``), asking for mutual authentication where the
        mechanism has it. Explicit credentials when set, else the logon
        session or credential cache. `NegotiateUnavailableError` without
        pyspnego, `NegotiationError` when it cannot make a context."""
        if protocol not in _PROTOCOLS:
            raise ValueError("protocol is 'negotiate' or 'ntlm'")
        spnego = _spnego()
        identity = self._identity()
        username, password = identity if identity else (None, None)
        try:
            return spnego.client(
                username,
                password,
                hostname=host.strip("[]"),
                service="HTTP",
                protocol=protocol,
                context_req=spnego.ContextReq.mutual_auth,
            )
        except Exception as error:
            raise NegotiationError(
                "%s authentication for %s could not start (%s: %s)" % (protocol, host, type(error).__name__, error)
            ) from error
