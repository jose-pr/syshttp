"""Negotiate and NTLM through the default transport: a 401 from a server and a
407 from a proxy, `CONNECT` included, answered leg after leg on the connection
the challenge came on. The server half is pyspnego's acceptor on a loopback
socket; the client's identity is made up for the test, or on Windows is the
logon session against an acceptor in this process. Nothing leaves the machine.

A test runs once for each way of running the server that works where the suite
runs: pyspnego's own NTLM (credentials made up here) and SSPI (the logon
session). A mode that cannot run here is a skip with its reason (`-rs`)."""

import base64
import logging
import os
import subprocess
import sys
import typing

import pytest

from client_wire import (
    IDLE,
    Handshake,
    Proxy,
    Reply,
    Wire,
    loopback_authority,
    pure_acceptor,
    pure_ntlm_problem,
    response,
    sspi_acceptor,
    sspi_problem,
)
from syshttp import HTTPEnv
from syshttp.client import HTTPClient, HTTPTransport
from syshttp.exceptions import ConfigurationError, NegotiateUnavailableError, NegotiationError
from syshttp.negotiate import DEFAULT_MAX_LEGS, DEFAULT_MAX_TOKEN, Negotiate, has_negotiate

TIMEOUT = (5, 5)
NOWHERE = HTTPEnv(environ={})
needs_spnego = pytest.mark.skipif(not has_negotiate(), reason="the negotiate extra (pyspnego) does not import here")


@pytest.fixture(params=["pure", "sspi"])
def acceptor(request, tmp_path, monkeypatch):
    if request.param == "pure":
        problem = pure_ntlm_problem()
        if problem:
            pytest.skip(problem)
        users = tmp_path / "ntlm_users"
        found = pure_acceptor(users)
        monkeypatch.setenv("NTLM_USER_FILE", str(users))
        return found
    problem = sspi_problem()
    if problem:
        pytest.skip(problem)
    return sspi_acceptor()


@pytest.fixture
def pure(tmp_path, monkeypatch):
    problem = pure_ntlm_problem()
    if problem:
        pytest.skip(problem)
    users = tmp_path / "ntlm_users"
    found = pure_acceptor(users)
    monkeypatch.setenv("NTLM_USER_FILE", str(users))
    return found


@pytest.fixture
def transport_for():
    made = []

    def make(proxymap=None, **kwargs):
        kwargs.setdefault("env", NOWHERE)
        transport = HTTPTransport(proxymap=proxymap, **kwargs)
        made.append(transport)
        return transport

    yield make
    for transport in made:
        transport.close()


class Provider:
    """A proxy map answering one proxy URL for every request."""

    def __init__(self, answer):
        self.answer = answer

    def __getitem__(self, url):
        return self.answer


def get(transport, url, **kwargs):
    headers = kwargs.pop("headers", {})
    return transport.send(kwargs.pop("method", "GET"), url, headers=headers, timeout=TIMEOUT, **kwargs)


def allowed(acceptor, host="127.0.0.1", **kwargs):
    """A `Negotiate` for a server at `host` with the acceptor's client identity."""
    return Negotiate(host, **acceptor.options, **kwargs)


def allowed_proxy(acceptor, host="127.0.0.1", **kwargs):
    return Negotiate(proxies=host, **acceptor.options, **kwargs)


def authorizations(requests, header="Authorization"):
    return [request.header(header) for request in requests]


# --- a server's 401 ---------------------------------------------------------------


@needs_spnego
def test_a_401_ntlm_challenge_is_answered_leg_by_leg_on_one_connection(acceptor, transport_for):
    handshake = Handshake(acceptor)
    with Wire(handshake) as wire:
        reply = get(transport_for(negotiate=allowed(acceptor)), wire.url + "/secret")
        assert (reply.status, reply.read()) == (200, b"authenticated")
        assert wire.connections == 1
    assert [r.connection for r in wire.requests] == [0, 0, 0]
    first, second, third = authorizations(wire.requests)
    assert first is None
    # NTLMSSP type 1, then type 3, as the acceptor's own steps accept them.
    assert second.startswith("NTLM TlRMTVNTUAAB") and third.startswith("NTLM TlRMTVNTUAAD")
    assert len(handshake.principals) == 1
    assert [r.header("Connection") for r in wire.requests[1:]] == ["keep-alive", "keep-alive"]
    assert [r.target for r in wire.requests] == ["/secret"] * 3


@needs_spnego
def test_the_connection_stays_authenticated_for_the_next_request(acceptor, transport_for):
    handshake = Handshake(acceptor)
    with Wire(handshake) as wire:
        transport = transport_for(negotiate=allowed(acceptor))
        get(transport, wire.url + "/one").read()
        assert get(transport, wire.url + "/two").read() == b"authenticated"
    assert wire.connections == 1 and len(wire.requests) == 4
    assert wire.requests[3].header("Authorization") is None
    assert handshake.count("done") == 1


@needs_spnego
def test_a_client_answers_the_challenge_for_a_request_with_a_body(acceptor, transport_for):
    seen = []

    def ok(request):
        seen.append(request.body)
        return response(body=b"stored")

    with Wire(Handshake(acceptor, ok=ok)) as wire:
        reply = get(transport_for(negotiate=allowed(acceptor)), wire.url + "/up", method="POST", body=b"payload")
        assert reply.read() == b"stored"
    assert [r.body for r in wire.requests] == [b"payload"] * 3
    assert seen == [b"payload"]


@needs_spnego
def test_httpclient_takes_the_policy_and_follows_the_handshake(acceptor):
    with Wire(Handshake(acceptor)) as wire:
        with HTTPClient(env=NOWHERE, proxymap={}, negotiate=allowed(acceptor)) as client:
            reply = client.request("GET", wire.url + "/x")
            assert (reply.status, reply.content) == (200, b"authenticated")
    assert wire.connections == 1


@needs_spnego
def test_the_policy_can_come_from_the_settings(pure, transport_for):
    environ = {
        "SYSHTTP_NEGOTIATE": "127.0.0.1",
        "SYSHTTP_NEGOTIATE_USER": pure.options["username"],
        "SYSHTTP_NEGOTIATE_PASSWORD": pure.options["password"],
    }
    with Wire(Handshake(pure)) as wire:
        reply = get(transport_for(env=HTTPEnv(environ=environ)), wire.url + "/")
        assert reply.status == 200


@needs_spnego
def test_the_settings_are_read_under_every_prefix(pure, transport_for):
    environ = {
        "MYTOOL_SYSHTTP_NEGOTIATE": "127.0.0.1",
        "MYTOOL_SYSHTTP_NEGOTIATE_USER": pure.options["username"],
        "MYTOOL_SYSHTTP_NEGOTIATE_PASSWORD": pure.options["password"],
    }
    with Wire(Handshake(pure)) as wire:
        assert get(transport_for(env=HTTPEnv("MYTOOL_", environ=environ)), wire.url + "/").status == 200


@needs_spnego
def test_negotiate_wrapped_ntlm_completes_and_the_closing_token_is_taken(pure, transport_for):
    handshake = Handshake(pure, scheme="Negotiate")
    with Wire(handshake) as wire:
        reply = get(transport_for(negotiate=allowed(pure)), wire.url + "/")
        assert (reply.status, reply.read()) == (200, b"authenticated")
    assert wire.requests[1].header("Authorization").startswith("Negotiate ")
    assert wire.connections == 1
    assert len(handshake.principals) == 1


def test_sspi_authenticates_with_the_current_logon_and_no_credentials(transport_for):
    problem = sspi_problem()
    if problem:
        pytest.skip(problem)
    acceptor = sspi_acceptor()
    negotiate = Negotiate("127.0.0.1")
    assert negotiate.settings().explicit_credentials is False
    handshake = Handshake(acceptor)
    with Wire(handshake) as wire:
        reply = get(transport_for(negotiate=negotiate), wire.url + "/")
        assert reply.status == 200
    (principal,) = handshake.principals
    assert principal.rpartition("\\")[2].lower() == os.environ.get("USERNAME", "").lower()


# --- what is left alone ---------------------------------------------------------------


def test_nothing_is_answered_unless_the_policy_names_the_server(transport_for):
    with Wire(Handshake(IDLE)) as wire:
        reply = get(transport_for(), wire.url + "/")
        assert (reply.status, reply.headers["WWW-Authenticate"]) == (401, "NTLM")
    assert len(wire.requests) == 1


def test_a_server_the_policy_does_not_name_gets_no_answer(transport_for):
    with Wire(Handshake(IDLE)) as wire:
        reply = get(transport_for(negotiate=allowed(IDLE, host="*.intranet.example")), wire.url + "/")
        assert reply.status == 401
    assert len(wire.requests) == 1


def test_an_authorization_the_caller_sets_is_not_replaced(transport_for):
    with Wire(Handshake(IDLE)) as wire:
        reply = get(transport_for(negotiate=allowed(IDLE)), wire.url + "/", headers={"Authorization": "Bearer mine"})
        assert reply.status == 401
    assert authorizations(wire.requests) == ["Bearer mine"]


def test_a_body_that_cannot_be_sent_twice_is_not_authenticated(transport_for):
    with Wire(Handshake(IDLE)) as wire:
        reply = get(transport_for(negotiate=allowed(IDLE)), wire.url + "/", method="POST", body=iter([b"a", b"b"]))
        assert reply.status == 401
    assert len(wire.requests) == 1


def test_a_server_that_offers_only_basic_is_not_answered(transport_for):
    def script(request):
        return response(401, {"WWW-Authenticate": 'Basic realm="NTLM, Negotiate"'})

    with Wire(script) as wire:
        reply = get(transport_for(negotiate=Negotiate("127.0.0.1")), wire.url + "/")
        assert reply.status == 401
    assert len(wire.requests) == 1


def test_a_missing_extra_is_an_error_naming_it_only_for_a_server_the_policy_names(transport_for, monkeypatch):
    monkeypatch.setitem(sys.modules, "spnego", None)

    def script(request):
        return response(401, {"WWW-Authenticate": "Negotiate"})

    with Wire(script) as wire:
        assert get(transport_for(), wire.url + "/").status == 401  # not asked for: the 401 is the answer
        with pytest.raises(NegotiateUnavailableError) as excinfo:
            get(transport_for(negotiate=Negotiate("127.0.0.1")), wire.url + "/")
    assert 'pip install "syshttp[negotiate]"' in str(excinfo.value)
    assert isinstance(excinfo.value, (NegotiationError, ImportError))
    assert has_negotiate() is False


# --- a handshake that fails -----------------------------------------------------------


@needs_spnego
def test_a_server_that_rejects_the_credentials_ends_the_handshake_with_an_error(acceptor, transport_for):
    handshake = Handshake(acceptor, refuse=True)
    with Wire(handshake) as wire:
        with pytest.raises(NegotiationError, match="refused the NTLM credentials") as excinfo:
            get(transport_for(negotiate=allowed(acceptor)), wire.url + "/")
    assert handshake.count("token") == 2 and len(wire.requests) == 3  # never again
    assert "127.0.0.1" in str(excinfo.value)
    for secret in acceptor.options.values():
        assert secret not in str(excinfo.value)


@needs_spnego
def test_a_wrong_password_is_refused_by_the_acceptor(pure, transport_for):
    handshake = Handshake(pure)
    with Wire(handshake) as wire:
        with pytest.raises(NegotiationError):
            get(transport_for(negotiate=Negotiate("127.0.0.1", **pure.wrong)), wire.url + "/")
    assert handshake.count("rejected") == 1 and len(wire.requests) == 3


@needs_spnego
def test_a_handshake_that_needs_more_legs_than_allowed_stops(acceptor, transport_for):
    handshake = Handshake(acceptor)
    with Wire(handshake) as wire:
        with pytest.raises(NegotiationError, match="more than 1 legs"):
            get(transport_for(negotiate=allowed(acceptor, max_legs=1)), wire.url + "/")
    assert len(wire.requests) == 2 and handshake.count("token") == 1


@needs_spnego
def test_a_token_over_the_limit_is_an_error(acceptor, transport_for):
    with Wire(Handshake(acceptor)) as wire:
        with pytest.raises(NegotiationError, match="over the limit of 100 bytes"):
            get(transport_for(negotiate=allowed(acceptor, max_token=100)), wire.url + "/")
    assert len(wire.requests) == 2


@needs_spnego
def test_a_token_that_is_not_base64_is_an_error(acceptor, transport_for):
    with Wire(Handshake(acceptor, junk=True)) as wire:
        with pytest.raises(NegotiationError, match="not valid base64"):
            get(transport_for(negotiate=allowed(acceptor)), wire.url + "/")
    assert len(wire.requests) == 2


@needs_spnego
def test_a_server_that_closes_the_connection_after_a_challenge_is_an_error(acceptor, transport_for):
    with Wire(Handshake(acceptor, close_challenge=True)) as wire:
        with pytest.raises(NegotiationError, match="closed the connection"):
            get(transport_for(negotiate=allowed(acceptor)), wire.url + "/")
    assert len(wire.requests) == 1


@needs_spnego
def test_a_garbage_challenge_token_is_the_librarys_error_not_a_loop(acceptor, transport_for):
    def script(request):
        if request.header("Authorization") is None:
            return response(401, {"WWW-Authenticate": "NTLM"})
        return response(401, {"WWW-Authenticate": "NTLM " + base64.b64encode(b"not an ntlm message").decode()})

    with Wire(script) as wire:
        with pytest.raises(NegotiationError, match="NTLM authentication with the server"):
            get(transport_for(negotiate=allowed(acceptor)), wire.url + "/")
    assert len(wire.requests) == 2


@needs_spnego
def test_a_server_that_rejects_with_a_token_after_the_exchange_is_complete_is_refused_not_followed(
    acceptor, transport_for
):
    handshake = Handshake(acceptor, refuse="token")
    with Wire(handshake) as wire:
        with pytest.raises(NegotiationError, match="refused the NTLM credentials"):
            get(transport_for(negotiate=allowed(acceptor)), wire.url + "/")
    assert len(wire.requests) == 3


# --- mutual authentication -------------------------------------------------------------


class _Context:
    """A security context that wants the server's closing token, as Kerberos
    does."""

    negotiated_protocol = "kerberos"

    def __init__(self, ticket=b"ticket"):
        self.complete = False
        self.seen = []
        self.ticket = ticket

    def step(self, token=None):
        self.seen.append(token)
        if token is None:
            return self.ticket
        self.complete = token == b"proof"
        return None


class _Kerberos(Negotiate):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.contexts = []
        self.ticket = b"ticket"

    def _context(self, host, protocol):
        self.contexts.append((host, protocol, _Context(self.ticket)))
        return self.contexts[-1][2]


def _kerberos_server(closing):
    def script(request):
        if request.header("Authorization") is None:
            return response(401, {"WWW-Authenticate": "Negotiate"})
        headers = {"WWW-Authenticate": "Negotiate " + base64.b64encode(closing).decode()} if closing else {}
        return response(200, headers, b"hello")

    return script


def test_the_servers_closing_token_is_checked_where_the_mechanism_has_one(transport_for):
    negotiate = _Kerberos("127.0.0.1")
    with Wire(_kerberos_server(b"proof")) as wire:
        reply = get(transport_for(negotiate=negotiate), wire.url + "/")
        assert (reply.status, reply.read()) == (200, b"hello")
    ((host, protocol, context),) = negotiate.contexts
    assert (host, protocol, context.complete, context.seen) == ("127.0.0.1", "negotiate", True, [None, b"proof"])
    assert wire.requests[1].header("Authorization") == "Negotiate " + base64.b64encode(b"ticket").decode()


def test_a_token_from_the_server_over_the_limit_is_refused(transport_for):
    def script(request):
        if request.header("Authorization") is None:
            return response(401, {"WWW-Authenticate": "Negotiate"})
        return response(401, {"WWW-Authenticate": "Negotiate " + base64.b64encode(b"x" * 200).decode()})

    with Wire(script) as wire:
        with pytest.raises(NegotiationError, match="sent a Negotiate token over the limit of 100 bytes"):
            get(transport_for(negotiate=_Kerberos("127.0.0.1", max_token=100)), wire.url + "/")
    assert len(wire.requests) == 2


def test_a_token_the_library_makes_over_the_limit_is_not_sent(transport_for):
    negotiate = _Kerberos("127.0.0.1", max_token=100)
    negotiate.ticket = b"x" * 200
    with Wire(_kerberos_server(b"proof")) as wire:
        with pytest.raises(NegotiationError, match="made a token over the limit of 100 bytes"):
            get(transport_for(negotiate=negotiate), wire.url + "/")
    assert len(wire.requests) == 1


def test_a_server_that_does_not_prove_itself_is_an_error(transport_for):
    with Wire(_kerberos_server(None)) as wire:
        with pytest.raises(NegotiationError, match="did not prove itself"):
            get(transport_for(negotiate=_Kerberos("127.0.0.1")), wire.url + "/")


def test_a_closing_token_that_does_not_complete_the_exchange_is_an_error(transport_for):
    with Wire(_kerberos_server(b"forged")) as wire:
        with pytest.raises(NegotiationError, match="does not complete"):
            get(transport_for(negotiate=_Kerberos("127.0.0.1")), wire.url + "/")


# --- plain http ----------------------------------------------------------------------


def test_plain_http_to_a_host_that_is_not_loopback_is_refused_before_a_token_is_made(transport_for):
    negotiate = _Kerberos("backend.test")
    with Proxy(script=_kerberos_server(b"proof")) as proxy:
        transport = transport_for(Provider(proxy.url), negotiate=negotiate)
        with pytest.raises(NegotiationError, match="SYSHTTP_NEGOTIATE_PLAIN_HTTP") as excinfo:
            get(transport, "http://backend.test/")
    assert "plain http" in str(excinfo.value)
    assert len(proxy.requests) == 1 and negotiate.contexts == []


def test_plain_http_allowed_by_the_setting_is_logged_as_a_weakening(transport_for, caplog):
    negotiate = _Kerberos("backend.test", plain_http=True)
    with caplog.at_level(logging.WARNING):
        with Proxy(script=_kerberos_server(b"proof")) as proxy:
            transport = transport_for(Provider(proxy.url), negotiate=negotiate)
            assert get(transport, "http://backend.test/").status == 200
            assert get(transport, "http://backend.test/again").status == 200
    weakened = [r for r in caplog.records if "weakened" in r.getMessage()]
    assert len(weakened) == 1  # once for the host
    assert "backend.test" in weakened[0].getMessage()
    assert len(negotiate.contexts) == 2


def test_the_plain_http_setting_is_read_from_the_environment(transport_for):
    environ = {"SYSHTTP_NEGOTIATE_PLAIN_HTTP": "yes"}
    negotiate = _Kerberos("backend.test", env=HTTPEnv(environ=environ))
    with Proxy(script=_kerberos_server(b"proof")) as proxy:
        transport = transport_for(Provider(proxy.url), negotiate=negotiate)
        assert get(transport, "http://backend.test/").status == 200


# --- a proxy's 407 ---------------------------------------------------------------------


@needs_spnego
def test_a_proxys_407_is_answered_on_the_connection_it_came_on(acceptor, transport_for):
    handshake = Handshake(acceptor, proxy=True)
    with Proxy(script=handshake) as proxy:
        transport = transport_for(Provider(proxy.url), negotiate=allowed_proxy(acceptor))
        reply = get(transport, "http://backend.test/page")
        assert (reply.status, reply.read()) == (200, b"authenticated")
    assert len({r.connection for r in proxy.requests}) == 1 and len(proxy.requests) == 3
    first, second, third = authorizations(proxy.requests, "Proxy-Authorization")
    assert first is None
    assert second.startswith("NTLM TlRMTVNTUAAB") and third.startswith("NTLM TlRMTVNTUAAD")
    assert {r.target for r in proxy.requests} == {"http://backend.test/page"}


def test_a_proxy_with_a_credential_of_its_own_is_not_answered_with_negotiate(transport_for):
    with Proxy(script=Handshake(IDLE, proxy=True)) as proxy:
        transport = transport_for(Provider(f"http://u:p@127.0.0.1:{proxy.port}"), negotiate=allowed_proxy(IDLE))
        assert get(transport, "http://backend.test/").status == 407
    assert len(proxy.requests) == 1


@needs_spnego
def test_a_proxys_challenge_and_then_the_servers_are_each_answered_on_plain_http(acceptor, transport_for):
    server = Handshake(acceptor)
    gate = Handshake(acceptor, proxy=True, ok=server)
    with Proxy(script=gate) as proxy:
        negotiate = Negotiate("127.0.0.1", "127.0.0.1", **acceptor.options)
        reply = get(transport_for(Provider(proxy.url), negotiate=negotiate), "http://127.0.0.1:9/page")
        assert (reply.status, reply.read()) == (200, b"authenticated")
    assert len({r.connection for r in proxy.requests}) == 1 and len(proxy.requests) == 5
    assert gate.count("done") == 1 and server.count("done") == 1


def test_a_gateway_is_not_asked_to_negotiate(transport_for):
    import proxylib

    with Wire(Handshake(IDLE)) as gate:
        entry = proxylib.Proxy("prefix+http", "127.0.0.1", gate.port, path="/fetch/")
        transport = transport_for(Provider(entry), negotiate=Negotiate("*", "*"))
        assert get(transport, "http://backend.test/").status == 401
    assert len(gate.requests) == 1


@pytest.fixture
def secure_origin():
    authority = loopback_authority()
    with Wire(lambda r: response(body=b"secure"), tls=authority.server_context()) as wire:
        yield authority, wire


@needs_spnego
def test_a_connect_the_proxy_challenges_is_answered_and_the_tunnel_then_opens(acceptor, transport_for, secure_origin):
    authority, origin = secure_origin
    handshake = Handshake(acceptor, proxy=True, tunnel=True)
    with Proxy(upstream=("127.0.0.1", origin.port), connect_script=handshake) as proxy:
        transport = transport_for(
            Provider(proxy.url), ssl_context=authority.client_context(), negotiate=allowed_proxy(acceptor)
        )
        assert get(transport, f"https://localhost:{origin.port}/secret").read() == b"secure"
    assert [r.method for r in proxy.requests] == ["CONNECT"] * 3 and len({r.connection for r in proxy.requests}) == 1
    first, second, third = authorizations(proxy.requests, "Proxy-Authorization")
    assert first is None and second.startswith("NTLM TlRMTVNTUAAB") and third.startswith("NTLM TlRMTVNTUAAD")
    (request,) = origin.requests
    assert request.header("Proxy-Authorization") is None and request.header("Authorization") is None


@needs_spnego
def test_a_proxy_and_the_server_behind_it_are_each_answered(acceptor, transport_for):
    authority = loopback_authority()
    server = Handshake(acceptor)
    with Wire(server, tls=authority.server_context()) as origin:
        proxy_side = Handshake(acceptor, proxy=True, tunnel=True)
        with Proxy(upstream=("127.0.0.1", origin.port), connect_script=proxy_side) as proxy:
            transport = transport_for(
                Provider(proxy.url),
                ssl_context=authority.client_context(),
                negotiate=Negotiate("localhost", "127.0.0.1", **acceptor.options),
            )
            reply = get(transport, f"https://localhost:{origin.port}/")
            assert (reply.status, reply.read()) == (200, b"authenticated")
    assert len(proxy.requests) == 3 and len(origin.requests) == 3
    assert [r.connection for r in origin.requests] == [0, 0, 0]
    assert origin.requests[1].header("Authorization").startswith("NTLM ")
    assert all(r.header("Proxy-Authorization") is None for r in origin.requests)


def test_a_connect_challenge_is_a_refusal_when_the_policy_does_not_name_the_proxy(transport_for, secure_origin):
    authority, origin = secure_origin
    with Proxy(upstream=("127.0.0.1", origin.port), connect_script=Handshake(IDLE, proxy=True, tunnel=True)) as proxy:
        transport = transport_for(Provider(proxy.url), ssl_context=authority.client_context())
        with pytest.raises(ConnectionError, match="refused CONNECT"):
            get(transport, f"https://localhost:{origin.port}/")
    assert len(proxy.requests) == 1


# --- credentials stay out of sight ----------------------------------------------------------


def test_the_password_is_in_no_repr_message_or_log(transport_for, caplog):
    secret = "pa55-" + "w0rd-never-shown"
    negotiate = Negotiate("127.0.0.1", username="DOM\\someone", password=secret)
    transport = transport_for(negotiate=negotiate)
    shown = [repr(negotiate), repr(negotiate.settings()), repr(transport), str(negotiate.settings())]
    assert all(secret not in text for text in shown)
    assert negotiate.settings().explicit_credentials is True
    with pytest.raises(ValueError) as excinfo:
        Negotiate(username="DOM\\someone", password=secret + "\r\nX: y")
    assert secret not in str(excinfo.value)
    with pytest.raises(ValueError) as excinfo:
        Negotiate(password=secret)
    assert secret not in str(excinfo.value)
    environ = {"SYSHTTP_NEGOTIATE_PASSWORD": secret}
    with pytest.raises(ConfigurationError) as excinfo:
        HTTPTransport(env=HTTPEnv(environ=environ))
    assert "SYSHTTP_NEGOTIATE_USER" in str(excinfo.value) and secret not in str(excinfo.value)
    assert secret not in caplog.text


# --- the policy and its settings -------------------------------------------------------------


def test_nothing_is_allowed_by_default():
    negotiate = Negotiate(env=NOWHERE)
    settings = negotiate.settings()
    assert (settings.hosts, settings.proxies, settings.plain_http) == ((), (), False)
    assert (settings.max_legs, settings.max_token) == (DEFAULT_MAX_LEGS, DEFAULT_MAX_TOKEN)
    assert not negotiate.wants("intranet.example") and not negotiate.wants("proxy.example", proxy=True)


def test_hosts_match_by_name_by_domain_or_all():
    negotiate = Negotiate("wiki.example.com, *.corp.example, ::1", proxies="gw.example")
    assert negotiate.wants("wiki.example.com") and negotiate.wants("WIKI.example.com.")
    assert negotiate.wants("a.b.corp.example") and not negotiate.wants("corp.example")
    assert not negotiate.wants("evilcorp.example") and not negotiate.wants("example.com")
    assert negotiate.wants("[::1]") and not negotiate.wants("wiki.example.com", proxy=True)
    assert negotiate.wants("GW.example", proxy=True) and Negotiate(proxies="*").wants("any.example", proxy=True)


def test_an_argument_beats_the_variable():
    env = HTTPEnv(environ={"SYSHTTP_NEGOTIATE": "from-env.example", "SYSHTTP_NEGOTIATE_MAX_LEGS": "9"})
    assert Negotiate(env=env).wants("from-env.example")
    argument = Negotiate("arg.example", max_legs=2, env=env)
    assert argument.wants("arg.example") and not argument.wants("from-env.example")
    assert (Negotiate(env=env).settings().max_legs, argument.settings().max_legs) == (9, 2)
    assert Negotiate([], env=env).wants("from-env.example") is False


def test_the_variables_are_read_when_used_not_when_the_policy_is_made():
    environ: typing.Dict[str, str] = {}
    negotiate = Negotiate(env=HTTPEnv(environ=environ))
    assert not negotiate.wants("late.example")
    environ["SYSHTTP_NEGOTIATE"] = "late.example"
    assert negotiate.wants("late.example")


@pytest.mark.parametrize(
    "variable, value",
    [
        ("SYSHTTP_NEGOTIATE", "bad host!"),
        ("SYSHTTP_NEGOTIATE", "a.*.example"),
        ("SYSHTTP_PROXY_NEGOTIATE", "http://proxy.example"),
        ("SYSHTTP_NEGOTIATE_PLAIN_HTTP", "maybe"),
        ("SYSHTTP_NEGOTIATE_MAX_LEGS", "0"),
        ("SYSHTTP_NEGOTIATE_MAX_LEGS", "many"),
        ("SYSHTTP_NEGOTIATE_MAX_TOKEN", "-5"),
        ("SYSHTTP_NEGOTIATE_USER", "someone"),
    ],
)
def test_a_setting_that_cannot_be_used_is_refused_when_the_transport_is_made(variable, value):
    with pytest.raises(ConfigurationError, match=variable):
        HTTPTransport(env=HTTPEnv(environ={variable: value}))


@pytest.mark.parametrize(
    "kwargs, error",
    [
        ({"username": "u"}, ValueError),
        ({"password": "p"}, ValueError),
        ({"username": "u", "password": "p\n"}, ValueError),
        ({"username": b"u", "password": "p"}, TypeError),
        ({"max_legs": 0}, ValueError),
        ({"max_token": True}, ValueError),
        ({"plain_http": "yes"}, TypeError),
        ({"hosts": "bad host"}, ValueError),
        ({"hosts": [1]}, TypeError),
    ],
)
def test_a_callers_bad_argument_is_a_plain_error(kwargs, error):
    with pytest.raises(error):
        Negotiate(**kwargs)


def test_a_client_given_its_own_transport_leaves_negotiation_to_it():
    with pytest.raises(ValueError, match="negotiate"):
        HTTPClient(transport=object.__new__(type("T", (), {"send": lambda *a, **k: None})), negotiate=Negotiate())
    with pytest.raises(TypeError):
        HTTPTransport(env=NOWHERE, negotiate="127.0.0.1")


def test_a_reply_is_not_changed_when_nothing_is_negotiated(transport_for):
    with Wire(lambda r: Reply(response(200, {"WWW-Authenticate": "Negotiate"}, b"fine"))) as wire:
        reply = get(transport_for(negotiate=Negotiate("127.0.0.1")), wire.url + "/")
        assert (reply.status, reply.read()) == (200, b"fine")
    assert len(wire.requests) == 1


def test_importing_the_package_the_client_and_the_policy_loads_no_pyspnego(tmp_path):
    code = (
        "import sys, syshttp, syshttp.negotiate, syshttp.client; "
        "sys.exit(1 if any(name == 'spnego' or name.startswith('spnego.') for name in sys.modules) else 0)"
    )
    done = subprocess.run([sys.executable, "-I", "-c", code], cwd=tmp_path, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_the_root_exports_the_negotiation_errors():
    import syshttp

    assert (
        syshttp.NegotiationError is NegotiationError and syshttp.NegotiateUnavailableError is NegotiateUnavailableError
    )
    assert issubclass(NegotiateUnavailableError, NegotiationError) and issubclass(
        NegotiationError, syshttp.SysHTTPError
    )
