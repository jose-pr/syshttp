"""The client: a transport, the headers and timeout every request is sent with,
the redirect rules above the transport, and what a client keeps between
requests (cookies, tokens, hooks, retries)."""

from __future__ import annotations

import os as _os
import ssl as _ssl
import threading as _threading
import time as _time
import typing as _ty

from .. import __version__
from .. import hooks as _hooks
from ..env import HTTPEnv
from ..jar import CookieJar, TokenJar
from ..negotiate import Negotiate
from ..retry import TRANSIENT_STATUSES, retry_after
from . import _follow, _settings
from ._deadline import Deadline, check_deadline
from ._default import transport_source
from ._headers import check_headers, check_url, has_header, merge_headers
from ._response import HTTPResponse, too_large
from ._state import StateTransport, cookie_aliases, make_cookies, make_tokens

if _ty.TYPE_CHECKING:
    from ..auth import AuthProvider

DEFAULT_TIMEOUT = (10, 60)
"""`(connect, read)` timeout, in seconds, a client sends with every request
unless it is given `timeout` (`HTTPClient(timeout=...)` or per request);
`timeout=None` waits without a limit."""

_UNSET: _ty.Any = object()
"""The `timeout` or `deadline` of a call that did not give one: the client's own."""

_RETRIED_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE", "TRACE", "PROPFIND"})
"""Methods a status or a failed connection is retried for: the ones that are
safe to send twice."""

_REQUEST_OPTIONS = frozenset({"data", "headers", "stream", "allow_redirects", "timeout", "deadline", "auth"})
"""The keyword arguments of `request()`, which a hook may change."""

MAX_RETRY_WAIT = 120.0
"""Most seconds a client waits before a retry, whatever `Retry-After` asks."""


def _retry_wait(attempt: int, backoff: float, headers: "_ty.Mapping[str, str] | None") -> float:
    """Seconds to wait before retry number `attempt` (1 is the first): none
    before the first, then `backoff` doubled each time; never less than a
    `Retry-After` that `headers` carry; at most `MAX_RETRY_WAIT`."""
    wait = 0.0 if attempt <= 1 else backoff * 2 ** (attempt - 1)
    asked = retry_after(headers.items()) if headers else None
    if asked is not None:
        wait = max(wait, asked)
    return min(wait, MAX_RETRY_WAIT)


class HTTPClient:
    """A transport with the settings every request is sent with, the rules for
    what happens after a redirect, and the state that belongs to a client.

    `transport` is any object with a `send()` method as `HTTPTransport.send()`;
    one it is given stays the caller's. Without one the client builds the
    transport the `SYSHTTP_DEFAULT_TRANSPORT` setting names, else an
    `HTTPTransport`, when it is made, and closes it with `close()` or at the
    end of a `with` block. `proxymap`, `ssl_context`, `proxy_ssl_context` and
    `verify` configure that `HTTPTransport` and are `ValueError` beside a
    transport of your own; `env` (default `HTTPEnv()`) is where the client and
    its transport read their settings. `headers` are sent with every request,
    request-specific headers merged over them by name, over a `User-Agent` of
    `user_agent` (`syshttp/<version>` by default) and `Accept: */*`.
    Every request gets `timeout=DEFAULT_TIMEOUT` (`(10, 60)` seconds) unless
    `timeout` here or in the call says otherwise (`None` waits without limit).
    `timeout` bounds each wait; `deadline` (seconds, `None` for no limit, the
    default) bounds the whole request: redirects, retries and the reading of
    the body included, each wait's timeout is held to the time that remains,
    and `TimeoutError` is raised once it has passed. A read already blocked can
    overrun it by at most the timeout of that wait.

    The client, not the transport, follows redirects. `GET`, `HEAD` and
    `OPTIONS` follow up to 30; a redirect that changes the scheme, host or
    port drops `Authorization`, `Cookie` and `Proxy-Authorization` (and nothing
    else; the jar's cookies are chosen again for each hop). Any other method is sent
    without following: a 307 or 308 (for `PROPFIND` also a 301, 302 or 303) to
    the same scheme, host and port is sent once more with the same method and
    body, and any other 3xx, a redirect to another origin or a second redirect
    raises `OSError(EIO)`.

    **State**, chosen by the host of the URL asked for (the origin), never by a
    proxy's or a gateway's. A client keeps the cookies its responses set, in
    memory and, with `cookies`, in a jar: `True` is a file jar under
    `jar.store_root()` by host, a string one key for every host, a jar object
    is used as given. `cookie_hosts` (default `SYSHTTP_COOKIE_HOSTS`) declares
    groups of hosts that share cookies. `tokens` is read the same way and
    becomes a per-request `Authorization` (`Bearer <token>`, or verbatim when
    it names a scheme) that follows no redirect to another origin. In
    `request()` (not in `redirect()`): `auth_provider.ensure(client, url)` runs
    first, its errors swallowed; the `SYSHTTP_HOOKS_<KEY>_PY` hooks run on the
    caller's URL, and a request a hook makes through the client runs none of
    them again (the guard is per thread); a status in `status_forcelist`, or a
    failed connection (`ConnectionError`), is retried up to `retries` times for
    a method that is safe to send twice, after `backoff` seconds doubled each
    time and never less than the `Retry-After` of the reply, and a status that
    outlasts the retries is returned, not raised."""

    def __init__(
        self,
        transport: "_ty.Any" = None,
        *,
        headers: "_ty.Mapping[str, str] | None" = None,
        timeout: "float | tuple | None" = DEFAULT_TIMEOUT,
        deadline: "float | None" = None,
        user_agent: "str | None" = None,
        env: "HTTPEnv | None" = None,
        proxymap: "_ty.Any" = None,
        ssl_context: "_ssl.SSLContext | None" = None,
        proxy_ssl_context: "_ssl.SSLContext | None" = None,
        verify: "bool | str | _os.PathLike[str]" = True,
        cookies: "bool | str | CookieJar | None" = False,
        tokens: "bool | str | TokenJar | None" = False,
        auth_provider: "AuthProvider | None" = None,
        retries: int = 3,
        backoff: float = 1,
        status_forcelist: "_ty.Iterable[int]" = TRANSIENT_STATUSES,
        cookie_hosts: "_ty.Iterable[_ty.Iterable[str]] | None" = None,
        negotiate: "Negotiate | None" = None,
    ):
        if transport is not None and not callable(getattr(transport, "send", None)):
            raise TypeError("a transport is an object with a send() method")
        if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0:
            raise ValueError("retries is a count of retries, zero or more")
        if isinstance(backoff, bool) or not isinstance(backoff, (int, float)) or not 0 <= backoff < float("inf"):
            raise ValueError("backoff is a number of seconds, zero or more")
        self._env = HTTPEnv() if env is None else env
        options = {
            "proxymap": proxymap,
            "ssl_context": ssl_context,
            "proxy_ssl_context": proxy_ssl_context,
            "verify": verify,
            "negotiate": negotiate,
        }
        self._transport = transport
        self._built = None
        self._transport_lock = _threading.Lock()
        if transport is not None:
            if any(value is not (True if name == "verify" else None) for name, value in options.items()):
                raise ValueError(
                    "proxymap, ssl_context, proxy_ssl_context, verify and negotiate configure the default transport: "
                    "a client given a transport leaves them to it"
                )
        else:
            self._make, self._owned = transport_source(self._env, options)
            self.transport  # made now, so a setting that cannot be used is refused now
        self._cookies = make_cookies(cookies, self._env, cookie_aliases(cookie_hosts, self._env))
        self._tokens = make_tokens(tokens, self._env)
        self._auth_provider = auth_provider
        self._retries = retries
        self._backoff = float(backoff)
        self._status_forcelist = frozenset(status_forcelist)
        self._busy = _threading.local()
        self.headers = dict(headers or {})
        self.timeout = timeout
        self.deadline = check_deadline(deadline)
        self.user_agent = user_agent or f"syshttp/{__version__}"

    def __repr__(self) -> str:
        # Headers are left out: they carry credentials.
        return f"{type(self).__name__}()"

    @property
    def transport(self):
        """The transport: the one the client was given, or the one it made
        (again, after `close()`). Read once per request."""
        transport = self._transport
        if transport is None:
            with self._transport_lock:
                if self._transport is None:
                    self._transport = self._make()
                    if self._owned:
                        self._built = self._transport
                transport = self._transport
        return transport

    def close(self) -> None:
        """Closes the transport this client built for itself; one it was given
        stays the caller's. Harmless when called again."""
        with self._transport_lock:
            built, self._built = self._built, None
            if built is not None:
                self._transport = None
        if built is not None:
            built.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def _sent_headers(self, headers, auth) -> "dict[str, str]":
        """The headers every request starts from: the base ones, the client's,
        the call's, and the `Authorization` that `auth` stands for."""
        base = {"User-Agent": self.user_agent, "Accept": "*/*"}
        sent = merge_headers(base, self.headers, headers)
        if auth is not None and not has_header(sent, "Authorization"):
            sent["Authorization"] = auth if isinstance(auth, str) else _follow.basic_authorization(auth)
        return sent

    def _clock(self, deadline, method, url, first=None) -> "Deadline | None":
        """The deadline of a request: the call's, else the client's."""
        seconds = self.deadline if deadline is _UNSET else check_deadline(deadline)
        return None if seconds is None else Deadline(seconds, f"{method} {_follow.shown(first or url)}")

    def _dispatch(
        self,
        method,
        url,
        sent,
        data,
        allow_redirects,
        stream,
        timeout,
        deadline,
        first=None,
    ) -> HTTPResponse:
        check_url(url)
        check_headers(sent)
        if timeout is _UNSET:
            timeout = self.timeout
        if isinstance(data, str):
            data = data.encode("utf-8")
        transport = StateTransport(self.transport, self._cookies)
        # Always streamed from the transport, so that no reply is read whole
        # before it is known to be small enough (see `stream` below).
        if method.upper() in _follow.FOLLOWED_METHODS and data is None:
            if allow_redirects is False and first is None:
                resp = transport.send(
                    method,
                    url,
                    headers=sent,
                    timeout=timeout if deadline is None else deadline.cap(timeout),
                    stream=True,
                )
            else:
                resp = _follow.send_following(
                    transport,
                    method,
                    url,
                    headers=sent,
                    timeout=timeout,
                    stream=True,
                    first=first,
                    deadline=deadline,
                )
        else:
            resp = _follow.send_once(
                transport,
                method,
                url,
                headers=sent,
                body=data,
                timeout=timeout,
                stream=True,
                deadline=deadline,
            )
        if deadline is not None:
            deadline.bound(resp)
        if not stream:
            limit = _settings.MAX_REPLY_BYTES
            resp._buffered(limit, too_large(_follow.shown(url), limit))
        return resp

    def _retried(self, method: str, data) -> bool:
        """Whether this request may be sent again after it failed."""
        return self._retries > 0 and method.upper() in _RETRIED_METHODS and _follow.can_resend_body(data)

    def _send(self, method, url, data, headers, stream, allow_redirects, timeout, deadline, auth) -> HTTPResponse:
        """One request with its token, retries and deadline."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        if auth is None and self._tokens is not None:
            auth = self._tokens.authorization(url)
        sent = self._sent_headers(headers, auth)
        clock = self._clock(deadline, method, url)
        retried = self._retried(method, data)
        attempt = 0
        while True:
            try:
                resp = self._dispatch(method, url, sent, data, allow_redirects, stream, timeout, clock)
            except ConnectionError:
                if not retried or attempt >= self._retries:
                    raise
                reply_headers = None
            else:
                if not (retried and attempt < self._retries and resp.status in self._status_forcelist):
                    return resp
                reply_headers = resp.headers
                _follow.discard(resp)
            attempt += 1
            wait = _retry_wait(attempt, self._backoff, reply_headers)
            if clock is not None:
                wait = min(wait, clock.check())
            if wait > 0:
                _time.sleep(wait)

    def _guarded(self, name: str) -> bool:
        return bool(getattr(self._busy, name, False))

    def _ensure(self, url: str) -> None:
        """Runs the auth provider for `url`, unless this thread is inside it."""
        if self._auth_provider is None or self._guarded("ensuring"):
            return
        self._busy.ensuring = True
        try:
            self._auth_provider.ensure(self, url)
        except Exception:
            pass
        finally:
            self._busy.ensuring = False

    def request(
        self,
        method: str,
        url: str,
        *,
        data=None,
        headers: "_ty.Mapping[str, str] | None" = None,
        stream: bool = False,
        allow_redirects: "bool | None" = None,
        timeout=_UNSET,
        deadline=_UNSET,
        auth: "tuple[str | bytes, str | bytes] | str | None" = None,
    ) -> HTTPResponse:
        """Send `method` to `url` and return the final response. A `data` that
        is not `bytes` (a file, an iterable) cannot be sent twice, so it is not
        re-sent after a redirect, a dropped connection or a retry.
        `allow_redirects=False` returns the first answer of a `GET`, `HEAD` or
        `OPTIONS` as it is. `auth` is a `(user, password)` pair sent as
        `Authorization: Basic`, or a `str` sent as the `Authorization` value
        (`"Bearer <token>"`), to the origin of `url` unless a header names an
        `Authorization`; it beats a token of the client. `ValueError` for a URL
        (credentials in it included) or a header with a control character,
        before anything is sent.

        The auth provider, the hooks, the token and the retries of the client
        apply here. A hook is called as `hook(client, method, url, kwargs)` with
        the keyword arguments given (`data`, `headers`, `stream`,
        `allow_redirects`, `timeout`, `deadline`, `auth`), which it may change
        in place, and may return a response to be used instead of sending.

        With `stream=False` the body is read before this returns, and a decoded
        body over `MAX_REPLY_BYTES` is `OSError(EFBIG)`; with `stream=True` the
        caller reads it, and closes the response."""
        given: "dict[str, _ty.Any]" = {
            name: value
            for name, value, default in (
                ("data", data, None),
                ("headers", headers, None),
                ("stream", stream, False),
                ("allow_redirects", allow_redirects, None),
                ("timeout", timeout, _UNSET),
                ("deadline", deadline, _UNSET),
                ("auth", auth, None),
            )
            if value is not default
        }
        self._ensure(url)
        if not self._guarded("in_hook"):
            self._busy.in_hook = True
            try:
                hooked = _hooks.call_py_hooks(self, method, url, given, env=self._env)
            finally:
                self._busy.in_hook = False
            if hooked is not None:
                return hooked
        unknown = sorted(set(given) - _REQUEST_OPTIONS)
        if unknown:
            raise TypeError("a hook set %s, which request() does not take" % ", ".join(unknown))
        return self._send(
            method,
            url,
            given.get("data"),
            given.get("headers"),
            given.get("stream", False),
            given.get("allow_redirects"),
            given.get("timeout", _UNSET),
            given.get("deadline", _UNSET),
            given.get("auth"),
        )

    def redirect(
        self,
        method: str,
        url: str,
        resp: HTTPResponse,
        *,
        headers: "_ty.Mapping[str, str] | None" = None,
        stream: bool = False,
        timeout=_UNSET,
        deadline=_UNSET,
        auth: "tuple[str | bytes, str | bytes] | str | None" = None,
    ) -> HTTPResponse:
        """Send `method` to where `resp`, the answer to a request for `url`,
        redirects to, and follow what it redirects to in turn. The request
        carries what `url` is sent with, except that `Authorization`, `Cookie`
        and `Proxy-Authorization` are left off whenever it goes to another
        scheme, host or port than `url`'s. A
        redirect with no usable `Location` is `OSError(EIO)`. Cookies apply to
        every hop; the token, hooks and retries belong to `request()`."""
        sent = self._sent_headers(headers, auth)
        location = _follow.redirect_location(url, resp)
        if location is None:
            raise _follow.refused_redirect(method, url, resp, None, "no usable Location")
        clock = self._clock(deadline, method, location, first=url)
        return self._dispatch(method, location, sent, None, None, stream, timeout, clock, first=url)
