"""The Negotiate and NTLM exchange: reading a challenge and running the legs.

The transport says how one leg is sent (on the connection the challenge came
on) and this module decides what to send and when to stop. A leg is one
request carrying a token."""

from __future__ import annotations

import base64 as _base64
import binascii as _binascii
import re as _re
import typing as _ty

from ..exceptions import NegotiationError
from ..negotiate import Negotiate, NegotiateSettings
from ._headers import peer_text

Pairs = _ty.Sequence["tuple[str, str]"]
View = _ty.Tuple[int, Pairs]
"""A reply as the exchange reads it: its status and its header fields."""

SERVER = ("WWW-Authenticate", "Authorization")
PROXY = ("Proxy-Authenticate", "Proxy-Authorization")

_QUOTED = _re.compile(r'"(?:\\.|[^"\\])*"')
_CHALLENGE = _re.compile(r"(?:^|,)\s*(Negotiate|NTLM)(?:[ \t]+([A-Za-z0-9+/=_.~-]+))?[ \t]*(?=,|$)", _re.IGNORECASE)
_SCHEMES = {"negotiate": "Negotiate", "ntlm": "NTLM"}


def challenges(pairs: Pairs, header: str) -> "list[tuple[str, str | None]]":
    """The Negotiate and NTLM challenges among the `header` fields of a reply,
    as `(scheme, token)` with the scheme as it is sent and the token still
    base64 (`None` when the challenge has none). Quoted strings of other
    challenges (`Basic realm="a, NTLM"`) are not read."""
    found: "list[tuple[str, str | None]]" = []
    name = header.lower()
    for field, value in pairs:
        if field.lower() != name:
            continue
        for match in _CHALLENGE.finditer(_QUOTED.sub('""', value)):
            found.append((_SCHEMES[match.group(1).lower()], match.group(2)))
    return found


def offered(pairs: Pairs, header: str) -> "str | None":
    """The scheme to answer, `Negotiate` before `NTLM`, or `None` when the
    reply offers neither."""
    schemes = {scheme for scheme, _ in challenges(pairs, header)}
    for scheme in ("Negotiate", "NTLM"):
        if scheme in schemes:
            return scheme
    return None


def _decode(token: "str | None", scheme: str, where: str, limit: int) -> "bytes | None":
    if token is None:
        return None
    # base64 is 4 characters per 3 bytes
    if len(token) > (limit * 4) // 3 + 4:
        raise NegotiationError("%s sent a %s token over the limit of %d bytes" % (where, scheme, limit))
    try:
        raw = _base64.b64decode(token, validate=True)
    except (_binascii.Error, ValueError):
        raise NegotiationError("%s sent a %s token that is not valid base64" % (where, scheme)) from None
    if len(raw) > limit:
        raise NegotiationError("%s sent a %s token over the limit of %d bytes" % (where, scheme, limit))
    return raw


def _token(pairs: Pairs, header: str, scheme: str) -> "str | None":
    return next((token for found, token in challenges(pairs, header) if found == scheme and token), None)


def _step(context: _ty.Any, token: "bytes | None", scheme: str, where: str) -> "bytes | None":
    try:
        return context.step(token)
    except Exception as error:
        raise NegotiationError(
            "%s authentication with %s failed (%s: %s)" % (scheme, where, type(error).__name__, peer_text(error))
        ) from error


def authenticate(
    negotiate: Negotiate,
    settings: NegotiateSettings,
    host: str,
    first: View,
    send: "_ty.Callable[[str, str], View]",
    *,
    proxy: bool,
    where: str,
) -> View:
    """Answers the challenge in `first` (a 401, or a 407 when `proxy`) and
    returns the reply that ended the exchange.

    `send(header, value)` sends the request again with that header, on the
    connection the challenge came on, and returns the reply. Raises
    `NegotiationError` when the credentials are refused, when the legs or a
    token pass the limits, when a token is not valid, when the library fails or
    when mutual authentication was asked for and the server did not prove
    itself; it sends no more than `settings.max_legs` requests and never
    repeats one that was answered."""
    challenge, answer = PROXY if proxy else SERVER
    scheme = offered(first[1], challenge)
    if scheme is None:
        return first
    context = negotiate._context(host, scheme.lower())
    limit = settings.max_token
    incoming = _decode(_token(first[1], challenge, scheme), scheme, where, limit)
    status = first[0]
    legs = 0
    while True:
        if legs >= settings.max_legs:
            raise NegotiationError(
                "%s authentication with %s needed more than %d legs" % (scheme, where, settings.max_legs)
            )
        outgoing = _step(context, incoming, scheme, where)
        if not outgoing:
            raise NegotiationError("%s authentication with %s produced no token to send" % (scheme, where))
        if len(outgoing) > limit:
            raise NegotiationError(
                "%s authentication with %s made a token over the limit of %d bytes" % (scheme, where, limit)
            )
        legs += 1
        reply = send(answer, "%s %s" % (scheme, _base64.b64encode(outgoing).decode("ascii")))
        status, pairs = reply
        if status == first[0]:
            # Challenged again: more to do only when the server sent a token
            # and the context has more to say.
            incoming = _decode(_token(pairs, challenge, scheme), scheme, where, limit)
            if incoming is None or getattr(context, "complete", False):
                raise NegotiationError("%s refused the %s credentials (HTTP %d)" % (where, scheme, status))
            continue
        _finish(context, pairs, challenge, scheme, status, where, limit)
        return reply


def _finish(context: _ty.Any, pairs: Pairs, challenge: str, scheme: str, status: int, where: str, limit: int) -> None:
    """Takes the server's closing token, which proves the server to the
    client where the mechanism has mutual authentication (Kerberos). A reply of
    400 or more is the server's own answer and is not checked; NTLM has no
    closing token."""
    if status >= 400 or getattr(context, "complete", False):
        return
    closing = _decode(_token(pairs, challenge, scheme), scheme, where, limit)
    if closing is None:
        if getattr(context, "negotiated_protocol", None) == "ntlm":
            return
        raise NegotiationError("%s did not prove itself: its %s reply has no closing token" % (where, scheme))
    _step(context, closing, scheme, where)
    if not getattr(context, "complete", False) and getattr(context, "negotiated_protocol", None) != "ntlm":
        raise NegotiationError("%s did not prove itself: its %s token does not complete the exchange" % (where, scheme))
