"""Loopback servers for the HTTP client, scripted at the byte level: an origin
that records what it receives and answers from a script, a proxy, and the test
certificate authority of tests/data. Nothing here leaves the loopback
interface."""

from __future__ import annotations

import base64
import functools
import os
import pathlib
import select
import secrets
import socket
import ssl
import sys
import tempfile
import threading
import time
import typing

CRLF = b"\r\n"


def wait_until(predicate, timeout: float = 15.0, interval: float = 0.02) -> bool:
    """Poll `predicate` until it is true or `timeout` seconds have passed;
    returns its last value. A test asserts the result: what must be true
    after the wait, not how long it took to get there."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


# How often a blocked accept() looks at the stop flag. Closing a listening
# socket from another thread does not wake an accept() on every platform
# (Linux leaves it blocked), so the accept loops never rely on it.
_POLL = 0.05


def _stop_listening(stop, thread, listener, sockets, lock):
    """Stop an accept loop and drop every connection it accepted."""
    stop.set()
    thread.join(timeout=10)  # a safety net: the loop sees the flag within _POLL
    try:
        listener.close()
    except OSError:
        pass
    with lock:
        accepted = list(sockets)
    for sock in accepted:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        sock.close()


class Request(typing.NamedTuple):
    """One request as the server received it."""

    method: str
    target: str
    headers: "list[tuple[str, str]]"
    body: bytes
    connection: int  # which accepted connection carried it, from 0

    def header(self, name: str):
        for key, value in self.headers:
            if key.lower() == name.lower():
                return value
        return None


class Reply(typing.NamedTuple):
    """Bytes to send, whether to close the connection after them, and bytes
    to send `delay` seconds later on the same connection."""

    raw: bytes
    close: bool = False
    later: bytes = b""
    delay: float = 0.0


class Drop:
    """Close the connection without answering."""


class Hang:
    """Never answer; the connection stays open until the server closes."""


def response(status=200, headers=None, body=b"", reason="OK", length=True) -> bytes:
    """A complete HTTP/1.1 response; `Content-Length` is added unless
    `length` is false or `headers` names one."""
    head = [f"HTTP/1.1 {status} {reason}"]
    names = {k.lower() for k in (headers or {})}
    for key, value in (headers or {}).items():
        head.append(f"{key}: {value}")
    if length and "content-length" not in names and "transfer-encoding" not in names:
        head.append(f"Content-Length: {len(body)}")
    return "\r\n".join(head).encode("latin-1") + CRLF + CRLF + body


def _read_until(sock, marker: bytes, limit=1 << 20, start: bytes = b"") -> "tuple[bytes, bytes] | None":
    data = start
    while marker not in data:
        chunk = sock.recv(65536)
        if not chunk:
            return None
        data += chunk
        if len(data) > limit:
            return None
    head, _, rest = data.partition(marker)
    return head, rest


def _read_exactly(sock, rest: bytes, count: int) -> bytes:
    while len(rest) < count:
        chunk = sock.recv(65536)
        if not chunk:
            break
        rest += chunk
    return rest


def _read_chunked(sock, rest: bytes) -> "tuple[bytes, bytes]":
    """The body, and the bytes that followed it on the connection."""
    body = b""
    while True:
        while CRLF not in rest:
            chunk = sock.recv(65536)
            if not chunk:
                return body, b""
            rest += chunk
        line, _, rest = rest.partition(CRLF)
        size = int(line.split(b";")[0], 16)
        rest = _read_exactly(sock, rest, size + 2)
        body += rest[:size]
        rest = rest[size + 2 :]
        if size == 0:
            return body, rest


class Wire:
    """An origin on a loopback port. `script(request)` returns what to send:
    `bytes`, a `Reply`, `Drop()` or `Hang()`; the default answers `200 ok`.
    `requests` lists what was received, `connections` how many connections
    were accepted, and `closed` the connections the client closed. With `tls`
    (an `ssl.SSLContext`) every connection is wrapped by the server first."""

    def __init__(self, script=None, tls: "ssl.SSLContext | None" = None):
        self.script = script or (lambda request: response(body=b"ok"))
        self.tls = tls
        self.requests: "list[Request]" = []
        self._connections = 0
        self._taking = threading.Lock()
        self.closed: "list[int]" = []
        self.handshakes_failed = 0
        self._lock = threading.Lock()
        self._sockets: "list[socket.socket]" = []
        self._stop = threading.Event()
        self._listener = socket.create_server(("127.0.0.1", 0))
        self._listener.setblocking(False)
        self.port = self._listener.getsockname()[1]
        self.host = "127.0.0.1"
        self._thread = threading.Thread(target=self._accept, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"{'https' if self.tls else 'http'}://127.0.0.1:{self.port}"

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    def close(self):
        _stop_listening(self._stop, self._thread, self._listener, self._sockets, self._lock)

    @property
    def connections(self) -> int:
        """How many connections the client has made. A connection waiting in
        the kernel's queue is taken first, so a test asking "was one made?"
        does not depend on the accept thread having run."""
        self._take()
        return self._connections

    def _accept(self):
        while not self._stop.is_set():
            try:
                select.select([self._listener], [], [], _POLL)
            except (OSError, ValueError):
                return
            self._take()

    def _take(self):
        """Accept every connection that is waiting, and start serving it."""
        with self._taking:
            while True:
                try:
                    sock, _ = self._listener.accept()
                except OSError:  # nothing waiting, or the listener is closed
                    return
                sock.setblocking(True)
                with self._lock:
                    index = self._connections
                    self._connections += 1
                    self._sockets.append(sock)
                threading.Thread(target=self._serve, args=(sock, index), daemon=True).start()

    def _serve(self, sock, index):
        try:
            if self.tls is not None:
                try:
                    sock = self.tls.wrap_socket(sock, server_side=True)
                except (OSError, ssl.SSLError):
                    with self._lock:
                        self.handshakes_failed += 1
                    return
                with self._lock:
                    self._sockets.append(sock)
            carry = b""  # what the client sent beyond the request just read
            while not self._stop.is_set():
                parsed = _read_until(sock, CRLF + CRLF, start=carry)
                if parsed is None:
                    return
                head, rest = parsed
                lines = head.decode("latin-1").split("\r\n")
                method, target, _version = lines[0].split(" ", 2)
                headers = [tuple(line.split(":", 1)) for line in lines[1:]]
                headers = [(k, v.strip()) for k, v in headers]
                length = next((int(v) for k, v in headers if k.lower() == "content-length"), 0)
                chunked = any(k.lower() == "transfer-encoding" and "chunked" in v.lower() for k, v in headers)
                if chunked:
                    body, carry = _read_chunked(sock, rest)
                else:
                    data = _read_exactly(sock, rest, length)
                    body, carry = data[:length], data[length:]
                if index is None:
                    with self._lock:
                        index = self._connections
                        self._connections += 1
                request = Request(method, target, headers, body, index)
                with self._lock:
                    self.requests.append(request)
                action = self.script(request)
                if isinstance(action, Drop):
                    return
                if isinstance(action, Hang):
                    self._stop.wait(30)
                    return
                if isinstance(action, bytes):
                    action = Reply(action)
                sock.sendall(action.raw)
                if action.later:
                    time.sleep(action.delay)
                    sock.sendall(action.later)
                if action.close:
                    return
        except (OSError, ssl.SSLError, ValueError):
            # A request line that does not parse, as after bytes the client
            # should not have sent, ends the connection as a server would.
            return
        finally:
            with self._lock:
                self.closed.append(index)
            try:
                sock.close()
            except OSError:
                pass


class Proxy:
    """An HTTP proxy on a loopback port. A request in absolute form is
    answered by `script(request)` as an origin would; `CONNECT host:port` is
    answered `200` and then relayed to `upstream` (a `(host, port)`), whatever
    the host asked for, or refused with `refuse` (a status) when given.
    `connect_script(request)` sees each `CONNECT` first: what it returns
    (`bytes` or a `Reply`) is sent and the connection kept for the next
    request, `None` leaves the `CONNECT` to the tunnel. `requests` lists what it
    received, `CONNECT`s included, each with the index of its connection (connections
    that send nothing, such as a probe, have none)."""

    def __init__(self, script=None, upstream=None, refuse=None, connect_script=None):
        self.script = script or (lambda request: response(body=b"via proxy"))
        self.upstream = upstream
        self.refuse = refuse
        self.connect_script = connect_script
        self._connections = 0
        self.requests: "list[Request]" = []
        self._lock = threading.Lock()
        self._sockets: "list[socket.socket]" = []
        self._stop = threading.Event()
        self._listener = socket.create_server(("127.0.0.1", 0))
        self._listener.settimeout(_POLL)
        self.port = self._listener.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self._accept, daemon=True)
        self._thread.start()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    def close(self):
        _stop_listening(self._stop, self._thread, self._listener, self._sockets, self._lock)

    def _accept(self):
        while not self._stop.is_set():
            try:
                sock, _ = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            sock.settimeout(None)
            with self._lock:
                self._sockets.append(sock)
            threading.Thread(target=self._serve, args=(sock,), daemon=True).start()

    def _serve(self, sock):
        index = None  # numbered at its first request: a probe that sends nothing takes no number
        try:
            while not self._stop.is_set():
                parsed = _read_until(sock, CRLF + CRLF)
                if parsed is None:
                    return
                head, rest = parsed
                lines = head.decode("latin-1").split("\r\n")
                method, target, _version = lines[0].split(" ", 2)
                headers = [(k, v.strip()) for k, v in (l.split(":", 1) for l in lines[1:])]
                length = next((int(v) for k, v in headers if k.lower() == "content-length"), 0)
                body = _read_exactly(sock, rest, length)[:length]
                if index is None:
                    with self._lock:
                        index = self._connections
                        self._connections += 1
                request = Request(method, target, headers, body, index)
                with self._lock:
                    self.requests.append(request)
                if method == "CONNECT":
                    answer = self.connect_script(request) if self.connect_script else None
                    if answer is not None:
                        # A challenge: the connection stays open for the next leg.
                        if isinstance(answer, bytes):
                            answer = Reply(answer)
                        sock.sendall(answer.raw)
                        if answer.close:
                            return
                        continue
                    if self.refuse:
                        sock.sendall(response(self.refuse, reason="Refused"))
                        return
                    self._tunnel(sock)
                    return
                action = self.script(request)
                if isinstance(action, Drop):
                    return
                if isinstance(action, bytes):
                    action = Reply(action)
                sock.sendall(action.raw)
                if action.close:
                    return
        except OSError:
            return
        finally:
            try:
                sock.close()
            except OSError:
                pass

    def _tunnel(self, client):
        upstream = socket.create_connection(self.upstream)
        with self._lock:
            self._sockets.append(upstream)
        client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")

        def pump(source, sink):
            try:
                while True:
                    data = source.recv(65536)
                    if not data:
                        break
                    sink.sendall(data)
            except OSError:
                pass
            finally:
                try:
                    sink.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

        thread = threading.Thread(target=pump, args=(upstream, client), daemon=True)
        thread.start()
        pump(client, upstream)
        # The client is gone, so nobody reads the upstream's side any more;
        # shutting it wakes the other pump however the origin behaves.
        try:
            upstream.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        thread.join(timeout=10)
        upstream.close()


def refusing_port() -> int:
    """A loopback port nothing listens on."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


DATA = pathlib.Path(__file__).parent / "data"


class Authority(typing.NamedTuple):
    """The test certificate authority of tests/data and the server certificate
    it signed, which names `localhost` and `127.0.0.1`."""

    ca_file: str
    cert_file: str
    key_file: str

    def server_context(self) -> ssl.SSLContext:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.cert_file, self.key_file)
        return context

    def client_context(self) -> ssl.SSLContext:
        return ssl.create_default_context(cafile=self.ca_file)


def loopback_authority() -> Authority:
    return Authority(str(DATA / "ca.pem"), str(DATA / "server.pem"), str(DATA / "server.key"))


# --- Negotiate and NTLM -------------------------------------------------------
#
# The server half of a handshake runs for real: pyspnego is the acceptor. The
# client is syshttp's, with credentials made up for the test or, on Windows, the
# logon session of whoever runs it, against an acceptor in this process:
# nothing leaves the machine and no domain is asked.


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


class Acceptor(typing.NamedTuple):
    """A way to run the server half of a handshake, and the client credentials
    that go with it."""

    label: str
    make: typing.Callable[[str], typing.Any]  # protocol ("ntlm" | "negotiate") -> acceptor context
    options: "dict[str, typing.Any]"  # keywords of `Negotiate` for the client's identity
    wrong: "dict[str, typing.Any] | None"  # the same with a password the acceptor refuses; None: no such thing


def _exchange(client, server) -> None:
    token = None
    for _ in range(8):
        out = client.step(token)
        if out is None:
            break
        token = server.step(out)
        if client.complete and server.complete:
            return
    if not (client.complete and server.complete):
        raise RuntimeError("the exchange did not complete")


@functools.lru_cache(maxsize=None)
def pure_ntlm_problem() -> "str | None":
    """`None` when pyspnego's own NTLM completes a client and an acceptor in
    this process, else why it cannot (its cipher library may lack RC4)."""
    try:
        import spnego
        from spnego import NegotiateOptions
    except ImportError as error:
        return "pyspnego does not import (%s)" % error
    with tempfile.TemporaryDirectory() as directory:
        users = pathlib.Path(directory, "users")
        users.write_text("PROBE:probe:probe-password-1\n")
        before = os.environ.get("NTLM_USER_FILE")
        os.environ["NTLM_USER_FILE"] = str(users)
        try:
            _exchange(
                spnego.client(
                    "PROBE\\probe",
                    "probe-password-1",
                    hostname="localhost",
                    protocol="ntlm",
                    options=NegotiateOptions.use_ntlm,
                    context_req=spnego.ContextReq.mutual_auth,
                ),
                spnego.server(protocol="ntlm", options=NegotiateOptions.use_ntlm),
            )
        except Exception as error:
            return "pyspnego's own NTLM does not run here (%s: %s)" % (type(error).__name__, error)
        finally:
            if before is None:
                os.environ.pop("NTLM_USER_FILE", None)
            else:
                os.environ["NTLM_USER_FILE"] = before
    return None


@functools.lru_cache(maxsize=None)
def sspi_problem() -> "str | None":
    """`None` when SSPI completes NTLM between the logon session and an
    acceptor in this process, else why it cannot."""
    if sys.platform != "win32":
        return "SSPI is Windows only"
    try:
        import spnego
        from spnego import NegotiateOptions
    except ImportError as error:
        return "pyspnego does not import (%s)" % error
    try:
        _exchange(
            spnego.client(
                None,
                None,
                hostname="localhost",
                protocol="ntlm",
                options=NegotiateOptions.use_sspi,
                context_req=spnego.ContextReq.mutual_auth,
            ),
            spnego.server(protocol="ntlm", options=NegotiateOptions.use_sspi),
        )
    except Exception as error:
        return "SSPI NTLM does not run here (%s: %s)" % (type(error).__name__, error)
    return None


def pure_acceptor(users_file) -> Acceptor:
    """pyspnego's own acceptor with one user whose name and password are made
    up here and written to `users_file`, its credential store: the caller sets
    `NTLM_USER_FILE` to that path."""
    import spnego
    from spnego import NegotiateOptions

    domain, user, password = "SYSHTTPTEST", "tester", secrets.token_hex(12)
    pathlib.Path(users_file).write_text("%s:%s:%s\n" % (domain, user, password))
    name = "%s\\%s" % (domain, user)

    def make(protocol: str):
        return spnego.server(
            protocol=protocol,
            options=NegotiateOptions.use_negotiate if protocol == "negotiate" else NegotiateOptions.use_ntlm,
            context_req=spnego.ContextReq.mutual_auth,
        )

    return Acceptor(
        "pure",
        make,
        {"username": name, "password": password},
        {"username": name, "password": password + "x"},
    )


def sspi_acceptor() -> Acceptor:
    """An SSPI acceptor in this process. The client is the logon session of the
    process, with no password to give or to get wrong."""
    import spnego
    from spnego import NegotiateOptions

    def make(protocol: str):
        return spnego.server(protocol=protocol, options=NegotiateOptions.use_sspi)

    return Acceptor("sspi", make, {}, None)


class Handshake:
    """The server half of a Negotiate or NTLM exchange: a `script` for `Wire`
    (401) or `Proxy` (407), and with `tunnel=True` a `connect_script` for a
    `CONNECT` that the proxy then tunnels.

    Each connection has an acceptor of its own, as NTLM binds the identity to
    the connection. A request without a token is challenged, a token is
    stepped through the acceptor and answered with the next challenge, the
    request that completes it is served by `ok(request)` (default: `200`), and
    so is every later request on that connection. `events` lists
    `(connection, what)` in order: `challenge`, `token`, `done`, `rejected`,
    `served`; `principals` the names that authenticated.

    `refuse` answers the completing token with a challenge (carrying a token when
    it is `"token"`), as a server that
    rejects the credentials does; `close_challenge` sends `Connection: close`
    with each challenge; `junk` answers a token with a challenge whose token is
    not base64 (a token of characters that are not in its alphabet)."""

    def __init__(
        self,
        acceptor: Acceptor,
        *,
        scheme="NTLM",
        proxy=False,
        tunnel=False,
        ok=None,
        refuse=False,
        close_challenge=False,
        junk=False,
        body=b"authentication required",
    ):
        self.acceptor = acceptor
        self.scheme = scheme
        self.status, self.challenge, self.answer, self.reason = (
            (407, "Proxy-Authenticate", "Proxy-Authorization", "Proxy Authentication Required")
            if proxy
            else (401, "WWW-Authenticate", "Authorization", "Unauthorized")
        )
        self.tunnel = tunnel
        self.ok = ok
        self.refuse = refuse
        self.close_challenge = close_challenge
        self.junk = junk
        self.body = body
        self.events: "list[tuple[int, str]]" = []
        self.principals: "list[str]" = []
        self._contexts: "dict[int, typing.Any]" = {}
        self._done: "set[int]" = set()
        self._lock = threading.Lock()

    def count(self, what: str) -> int:
        """How many times `what` happened."""
        with self._lock:
            return sum(1 for _, event in self.events if event == what)

    def _note(self, connection: int, what: str) -> None:
        with self._lock:
            self.events.append((connection, what))

    def _challenge(self, connection: int, token, what="challenge") -> Reply:
        value = (
            self.scheme if token is None else "%s %s" % (self.scheme, token if isinstance(token, str) else _b64(token))
        )
        headers = {self.challenge: value, "Connection": "close" if self.close_challenge else "keep-alive"}
        self._note(connection, what)
        return Reply(response(self.status, headers, self.body, reason=self.reason), close=self.close_challenge)

    def _served(self, request: Request):
        self._note(request.connection, "served")
        if self.tunnel:
            return None
        return self.ok(request) if self.ok else response(body=b"authenticated")

    def __call__(self, request: Request):
        connection = request.connection
        if connection in self._done:
            return self._served(request)
        value = request.header(self.answer)
        if value is None:
            return self._challenge(connection, None)
        scheme, _, token = value.partition(" ")
        if scheme.lower() != self.scheme.lower():
            return self._challenge(connection, None)
        self._note(connection, "token")
        context = self._contexts.get(connection)
        if context is None:
            context = self._contexts[connection] = self.acceptor.make(self.scheme.lower())
        try:
            out = context.step(base64.b64decode(token))
        except Exception:
            self._contexts.pop(connection, None)
            return self._challenge(connection, None, "rejected")
        if self.junk:
            return self._challenge(connection, "AAAA-_-_")
        if not context.complete:
            return self._challenge(connection, out)
        if self.refuse:
            self._contexts.pop(connection, None)
            return self._challenge(connection, b"try again" if self.refuse == "token" else None, "rejected")
        self._done.add(connection)
        self._note(connection, "done")
        self.principals.append(str(getattr(context, "client_principal", "")))
        served = self._served(request)
        if out and isinstance(served, bytes):
            # The server's closing token rides on the reply that succeeds.
            head, _, rest = served.partition(CRLF)
            closing = ("%s: %s %s" % (self.challenge, self.scheme, _b64(out))).encode("ascii")
            served = head + CRLF + closing + CRLF + rest
        return served


IDLE = Acceptor("idle", lambda protocol: None, {}, None)
"""An acceptor that is never asked: for a test whose server challenges and is
never answered."""
