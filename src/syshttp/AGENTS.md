# `syshttp` — public API header

Header-file-style reference for the `syshttp` package: every public export with
its signature, arguments, contract and gotchas, so the package can be used
without reading its source. It ships inside the package and is
self-contained. Development documentation lives with the source at
<https://github.com/jose-pr/syshttp>.

Import names from their modules: `syshttp.env`, `syshttp.proxy`,
`syshttp.client`, `syshttp.negotiate`, `syshttp.jar`, `syshttp.cookies`, `syshttp.hooks`,
`syshttp.tls`, `syshttp.retry`, `syshttp.auth`, `syshttp.exceptions`,
`syshttp.autopatch`. Each declares `__all__`: a name outside it is not API,
and a module whose name starts with `_` is private. The root re-exports
`HTTPEnv`, the exceptions, `NoReachableProxyError`, `proxy_map`,
`configured_proxy`, `proxy_type` and `fetch` (the function of
`syshttp.client`, imported when it is asked for); there is no `syshttp.fetch`
module.

`pip install syshttp` brings proxylib 2.0.2+ (proxy routing and the system's proxy configuration),
sslcontext (the system's TLS client; truststore on Python 3.10+) and
importpatch (import-time patching of other HTTP clients, off unless
`SYSHTTP_IMPORTPATCH` asks for it). The extras: `pac`
adds a JavaScript engine for PAC scripts proxylib evaluates itself (Linux
without libproxy); `negotiate` adds pyspnego for Negotiate and NTLM
(`syshttp.negotiate`); `kerberos` adds `gssapi` to it for the Kerberos
credential cache on Linux and macOS. The client needs nothing else: `requests` is no dependency
of any feature; only `syshttp.autopatch` touches it, in a program that imports
it, when `SYSHTTP_IMPORTPATCH` asks for it.

`syshttp.__version__` is the installed distribution's version.

## Settings (`syshttp.env`)

Every setting is a variable with a full name: syshttp's own carry
`SYSHTTP_` (`SYSHTTP_PROXY`, `SYSHTTP_HOME`, `SYSHTTP_HOOKS_<KEY>`),
conventional ones keep theirs (`HTTPS_PROXY`, `NO_PROXY`, `CA_BUNDLE`). Each
is read as `<PREFIX><NAME>` for every prefix in turn, the first one set (and
not blank) winning, each name on its own. The prefixes are the `prefixes`
argument of an `HTTPEnv`, else `SYSHTTP_PREFIX` (a `:`-separated list), else
one empty prefix: the names as written. A prefix is used literally, so it
carries its own separator (`AGENTS_`). Order: an explicit argument, then the
variable, then the built-in default. Nothing is read at import; each call
reads the environment as it is then. Below, every name is given as written,
under the empty prefix.

```python
class HTTPEnv:
    def __init__(self, prefixes: str | Iterable[str] | None = None,
                 environ: Mapping[str, str] | None = None) -> None
    environ: Mapping[str, str]          # property: the mapping read (os.environ when None)
    prefixes: tuple[str, ...]           # property: the prefixes in force, in lookup order
    def name(self, name: str) -> str
    def find(self, *names: str) -> tuple[str, str] | None
    def get(self, *names: str) -> str | None
    def family(self, stem: str) -> Iterator[tuple[str, str, str]]
PREFIX_VAR = "SYSHTTP_PREFIX"
```

- `SYSHTTP_PREFIX=MYTOOL_` reads `MYTOOL_SYSHTTP_PROXY`, `MYTOOL_HTTPS_PROXY`,
  `MYTOOL_CA_BUNDLE` and so on, and nothing unprefixed: a tool opts out of
  the defaults. `MYTOOL_:` reads `MYTOOL_<NAME>` first, then `<NAME>`: a tool
  layers its own settings over them. `SYSHTTP_PREFIX` itself has no prefix.
- `prefixes=None` reads `SYSHTTP_PREFIX` at every lookup; blank or unset is
  `("",)`. A string is split at `:`; an iterable is taken as the list; an
  empty iterable reads nothing. A prefix is letters, digits and underscores
  (possibly none), upper-cased; one listed twice counts once. A malformed
  argument raises `ValueError` in the constructor; a malformed
  `SYSHTTP_PREFIX` raises `ConfigurationError` naming it at the first lookup.
- A CGI program receives every request header as an `HTTP_*` variable, so a
  client could set `HTTP_PROXY`, `HTTP_PROXY_AUTH` and the like: under CGI,
  set a prefix list without the empty entry.
- `environ` isolates an instance: two `HTTPEnv`s with different prefixes or
  mappings never see each other's settings.
- `find(*names)` returns `(variable, value)` for the first of `names` set
  under the first prefix that has one (every name tried under a prefix before
  the next prefix), the value stripped; `None` when none is. `get` returns
  the value only. `name(name)` is `name` under the first prefix: what a
  message names when nothing is set, and what a child process is given.
- `family(stem)` yields `(rest, value, variable)` for every variable named
  `<PREFIX><stem><rest>` with a non-empty `rest` and a value that is not
  blank, the first prefix winning for a `rest` (compared upper-cased).

Every function below that reads a setting takes `env: HTTPEnv | None = None`
(keyword-only) and uses `HTTPEnv()` when it is `None`.

## Proxy (`syshttp.proxy`)

Routing is proxylib's (2.x): syshttp turns its settings into one proxylib
proxy map, and proxylib's client integrations send through it. Read an
answer with `proxylib.lookup(m, url)`; every proxylib integration takes the
map (`ProxyMapAdapter`, `ProxyMapHandler`, `ProxyTransport`, `ProxySession`).

```python
def proxy_map(proxy: str | None = None, noproxy: str | None = None, proxy_user: str | None = None,
              *, env=None) -> proxylib.ProxyMap
def configured_proxy(*, env=None) -> proxylib.Proxy | None
def system_map() -> proxylib.ProxyMap | None
def system_proxy_enabled(*, env=None) -> bool
def auth_header(*, env=None) -> str
def proxy_type(*, env=None) -> tuple[str, str | None]
NoReachableProxyError = proxylib.NoReachableProxyError
SYSTEM_PROXY_MAX_AGE = 60
PROXY = "PROXY"; PROXY_AUTH = "PROXY_AUTH"; PROXY_AUTH_HEADER = "PROXY_AUTH_HEADER"
PROXY_TYPE = "PROXY_TYPE"; SYSTEM_PROXY = "SYSTEM_PROXY"   # setting names, as `SYSHTTP_<NAME>`
DEFAULT_AUTH_HEADER = "Proxy-Authorization"; MACHINE_AUTH_VAR = "HTTP_PROXY_AUTH"
```

- `proxy_map()` reads the settings at every lookup, so one map serves a
  long-lived client, and always answers (never `KeyError`). Its answer is a
  tuple of entries to try in order, `None` for DIRECT:
  1. `NO_PROXY` / `no_proxy` hosts: DIRECT (proxylib's `BypassRules`:
     suffixes, CIDR, ports, `*`; loopback always).
  2. `SYSHTTP_PROXY` (`configured_proxy()`), alone.
  3. Else the machine's proxy: when any of `HTTP_PROXY`, `HTTPS_PROXY`,
     `FTP_PROXY`, `WS_PROXY`, `WSS_PROXY`, `ALL_PROXY` is set (either case),
     those variables alone decide, per scheme (proxylib's `EnvProxyConfig`:
     the lowercase spelling first under each prefix, a PAC result such as
     `PROXY a:1; DIRECT` read as a list); else the system's
     configuration for the URL (`system_map()`), unless `SYSHTTP_SYSTEM_PROXY`
     is off. `HTTP_PROXY_AUTH`, when set, is every such proxy's
     `Proxy-Authorization` (SOCKS entries excepted).
  4. Else DIRECT.
- `proxy` (curl's `-x`) replaces 2 and 3 with that proxy, a plain one whose
  credential is only its userinfo; `""` is DIRECT. `noproxy` (`--noproxy`)
  replaces `NO_PROXY`, the variables' own included; listing `<-loopback>`
  turns proxylib's implicit loopback bypass off, as curl has none. `proxy_user` (`-U user:password`) becomes the
  credential of whichever proxy answers.
- A malformed `SYSHTTP_PROXY`, `SYSHTTP_PROXY_TYPE` or `SYSHTTP_PROXY_AUTH_HEADER`
  raises `ConfigurationError` (proxylib's `ProxyParseError` for a URL) at
  lookup, only when `SYSHTTP_PROXY` is set (the header name only when
  `SYSHTTP_PROXY_AUTH` is too); a bad `SYSHTTP_SYSTEM_PROXY` only when the system
  would be asked.
- `configured_proxy()` is `SYSHTTP_PROXY` as a proxylib `Proxy` (a bare
  `host:port` is `http`). Its credential is `SYSHTTP_PROXY_AUTH`, a header value
  sent verbatim in `auth_header()` (`SYSHTTP_PROXY_AUTH_HEADER`, default
  `Proxy-Authorization`; a value with `:` or whitespace raises `ValueError`)
  in place of the userinfo, else the userinfo as Basic. A credential (this
  or `HTTP_PROXY_AUTH`) containing a CR, LF or NUL raises `ValueError` naming
  the variable, never the value. It goes to that proxy only: a `CONNECT`, or a plain-http request to it, never through the tunnel.
  `SYSHTTP_PROXY_TYPE=prefix[:/endpoint]` (`proxy_type()`) makes it a
  `prefix+http(s)` gateway: the request for `T` goes to
  `<proxy><endpoint>T`, the credential a header of that request. `syshttp.client`
  does not send an `https:` origin through a plain `prefix+http` gateway.
- `system_map()` is `proxylib.auto_proxy(environ={})` (the OS resolver --
  WinHTTP, CFNetwork, libproxy -- then the OS settings, PAC and WPAD
  included), built once per `SYSTEM_PROXY_MAX_AGE` seconds, each URL's
  answer cached as long. A configuration that cannot be read is `None`, and
  a lookup that fails is no opinion: DIRECT, logged at DEBUG, never a failed
  request.
- Proxies never print their secrets: a `Proxy`'s `repr()` hides the password
  and headers, `.url` has no credentials.
- How an answer is used is the client integration's: requests, httpx and
  aiohttp try the entries in order and move on when one does not connect
  (the last error is raised; a DIRECT entry reached is direct); a client
  that sends once, `syshttp.client` among them, takes the first reachable
  entry through `proxylib.Probed(proxy_map())`, which raises
  `NoReachableProxyError` (a
  `LookupError`) when none answers and the list holds no DIRECT.

## Client (`syshttp.client`)

A synchronous HTTP client on the standard library (`http.client`, `ssl`): no
third-party package, `requests` included. It routes by the proxy map
(`syshttp.proxy`), verifies with the system's TLS, and keeps the cookies and
tokens of each origin. `import syshttp.client` loads `http.client`, `ssl`,
proxylib and sslcontext; `import syshttp` does not.

```python
class HTTPClient:
    headers: dict
    timeout: float | tuple | None
    deadline: float | None
    user_agent: str
    def __init__(self, transport=None, *, headers=None, timeout=(10, 60), deadline=None, user_agent=None,
                 env: HTTPEnv | None = None, proxymap=None, ssl_context=None, proxy_ssl_context=None,
                 verify: bool | str | PathLike = True,
                 cookies: bool | str | CookieJar | None = False, tokens: bool | str | TokenJar | None = False,
                 auth_provider: AuthProvider | None = None, retries: int = 3, backoff: float = 1,
                 status_forcelist: Iterable[int] = TRANSIENT_STATUSES,
                 cookie_hosts: Iterable[Iterable[str]] | None = None,
                 negotiate: Negotiate | None = None)
    transport                                   # the transport in use
    def request(self, method, url, *, data=None, headers=None, stream=False, allow_redirects=None,
                timeout=..., deadline=..., auth=None) -> HTTPResponse
    def redirect(self, method, url, resp, *, headers=None, stream=False, timeout=..., deadline=...,
                 auth=None) -> HTTPResponse
    def close(self) -> None

def fetch(url, method="GET", *, headers=None, data=None, json=None, timeout=DEFAULT_TIMEOUT,
          client=None, transport=None, reauth=None, **client_options) -> HTTPResponse

DEFAULT_TIMEOUT = (10, 60)
MAX_REPLY_BYTES = 8388608
CA_BUNDLE = "CA_BUNDLE"; COOKIE_HOSTS = "SYSHTTP_COOKIE_HOSTS"
DEFAULT_TRANSPORT = "SYSHTTP_DEFAULT_TRANSPORT"      # setting names
```

- **`request(method, url, *, data=None, headers=None, stream=False,
  allow_redirects=None, timeout, deadline, auth=None)`** returns the final
  `HTTPResponse`. `data` is `bytes`, `str` (UTF-8), a binary file or an
  iterable of `bytes`; one that is not `bytes` cannot be sent twice, so it is
  not sent again after a redirect, a dropped connection or a retry. `auth` is a
  `(user, password)` pair sent as `Authorization: Basic`, or a `str` sent as
  the `Authorization` value (`"Bearer <token>"`), to the origin of `url`
  unless a header names an `Authorization`; it beats a token of the client. A
  `url` that carries credentials, a URL or header value with a control
  character (CR and LF included) and another scheme than `http:` or `https:`
  are `ValueError`, before anything is sent. A status of 400 or more is
  **not** an error: it is the reply (`raise_for_status()`). With
  `stream=False` the body has been read when `request()` returns, and one
  that decodes to more than `MAX_REPLY_BYTES` is `OSError(EFBIG)`; with
  `stream=True` the caller reads the body and closes the response.
- **Headers and time.** `headers` of the client and of the call are merged by
  name (case-blind, a value of `None` removes the name) over
  `User-Agent: <user_agent>` (default `syshttp/<version>`) and `Accept: */*`.
  Every request gets `timeout=(10, 60)` seconds (`connect`, `read`) unless
  the client or the call gives one; `timeout=None` waits without limit.
  `timeout` bounds each wait; `deadline` (seconds, `None` for none) bounds the
  whole request, redirects, retries and the reading of the body included, and
  `TimeoutError` is raised once it has passed. A call's value replaces the
  client's; a `deadline` that is not a number or `None` is `TypeError`, one
  that is not positive `ValueError`. `repr()` of a client shows no header.
- **Redirects.** `GET`, `HEAD` and `OPTIONS` follow up to 30 redirects (a
  `303` becomes a `GET`); `allow_redirects=False` returns the first answer. A
  redirect whose `Location` is missing or cannot be requested is
  `OSError(EIO)`. A redirect that changes the scheme, host or port drops
  `Authorization`, `Cookie` and `Proxy-Authorization` for that hop and every
  later one (the jar's cookies are chosen again for each hop), and nothing
  else: every other header goes to the new host as well, so keep a secret in
  one of those three. Every other method is sent without
  following: a 307 or 308 (for `PROPFIND` also a 301, 302 or 303) to the same
  scheme, host and port is sent once more with the same method, headers and
  body, and any other 3xx, a redirect to another origin or a second redirect
  is `OSError(EIO)` naming the status and the `Location` (userinfo, query and
  fragment removed). `redirect(method, url, resp, ...)` sends `method` to where
  `resp`, the answer to a request for `url` made with `allow_redirects=False`,
  redirects to, with the same rules; cookies apply to every hop, the token,
  hooks and retries belong to `request()`.
- **Routing.** Each request asks the proxy map (`proxymap`, any proxylib
  `ProxyMap` or value `ProxyMap()` builds one from; default
  `proxy.proxy_map(env=env)`) for the entries it may use and takes the first
  that accepts a TCP connection (`proxylib.Probed`; with no entry reachable and
  no `DIRECT`, `proxylib.NoReachableProxyError`). A direct entry connects to
  the origin; an `http:` or `https:` proxy gets an absolute-form request for
  an `http:` origin and a `CONNECT` for an `https:` one, an `https:` proxy
  over TLS and the origin's TLS inside it; a `prefix+http(s)` gateway gets
  `<gateway><path><URL>` with its credential as a header of that request, and
  the response keeps the URL asked for; a plain `prefix+http` gateway is not
  offered an `https:` origin, whose tokens and Secure cookies would cross it in
  clear text: the entry is skipped like a SOCKS one, and with nothing else left
  the request is `proxylib.UnsupportedProxyError`. A proxy's headers (its credential) go
  to the proxy only: in the `CONNECT`, or on the plain-http request to it,
  never through a tunnel. SOCKS entries are skipped; an answer with nothing
  else is `proxylib.UnsupportedProxyError`. A map with no opinion for a URL
  (`{}` for every URL) means a direct connection and the settings are not
  read. Every hop of a redirect is routed again; a connection to a proxy this
  thread already holds is reused without probing it. A `proxymap` of your own
  adds no `SYSHTTP_PROXY_AUTH` credential. A malformed proxy setting
  (`ConfigurationError`) is refused when the client is made.
- **TLS.** `https:` origins are verified against `ssl_context` when given,
  used as given and never changed (its `verify_mode`, trust store, client
  identity, ciphers and protocol versions decide; `verify` must stay `True`
  beside it, else `ValueError`; a non-`SSLContext` is `TypeError`); else
  against the CA bundle that `verify=<path>` or the `CA_BUNDLE` setting (read
  at each new connection, through the prefixes) names, a context trusting only
  that file (a file that cannot be read is `ConfigurationError` naming where
  the path came from); else against the system's context
  (`tls.os_ssl_context()`: the OS verifies, and a server that asks for a client
  certificate gets one from the OS store). `verify=False` turns verification
  off (a warning is logged under the `syshttp.client` logger when the client's
  transport is made). requests' own `REQUESTS_CA_BUNDLE` / `CURL_CA_BUNDLE` are
  not read. An `https:` proxy or gateway is spoken to with
  `proxy_ssl_context`, else the system's context; the gateway never gets the
  origin's `ssl_context` or client certificate. There is no per-request
  `verify` or client certificate: build another client or load the identity
  into the context.
- **Cookies.** A client keeps the cookies its responses set, per origin host
  and never per proxy or gateway, on every hop: parsed as RFC 6265 reads them
  (`cookies.set_cookie_specs`), sent as `cookies.cookie_applies` decides
  (longer paths first), expired and deleted ones dropped. A `Cookie` header the
  call or client names replaces the jar's for that request. They live in
  memory for the client's life; `cookies=True` also keeps them in a file jar
  under `jar.store_root(env=env)` by host, a string names one key for every
  host, a jar object is used as given. A host's rows are loaded from the jar
  the first time the host is asked for, and written back only when they differ
  from what was loaded or written last; a jar that fails to read or write is
  ignored. A by-host file gives its host (or group) only the rows whose domain
  covers it; a named key holds every row. A `Set-Cookie` with a control
  character (the tab apart) is ignored whole. A Secure cookie from plain http
  (the loopback hosts apart, as curl has it) is ignored, and plain http cannot
  set, replace or delete a stored Secure cookie of the same name whose domain
  (either containing the other) and path match (RFC 6265bis 5.7). `cookie_hosts` (default `SYSHTTP_COOKIE_HOSTS`, read when the client
  is made: groups split by `;`, hosts by `,`:
  `app.example.com,app.example.net;wiki,wiki.corp.example`; `[]` for none)
  declares groups of hosts that are one for cookies (`cookies.host_aliases`):
  - a host-only cookie a member sets, and one whose `Domain` names a member,
    belongs to the group's first host (stored there, kept in its jar file);
  - a request to any member carries what a request to any member would,
    `Secure` and the path still applying per request;
  - a member deletes such a cookie as the first host would;
  - a `Domain` outside the group is judged on the host that sent it, so a
    group never lets a host set a cookie for a domain that is not its own.

  Without groups the RFC 6265 rule stands: no host sets or deletes another
  host's cookie. Hosts are names or IP addresses, without a port; a host in
  two groups raises `ValueError`, a malformed variable `ConfigurationError`
  naming it, a group given as one string `TypeError`.
- **Tokens.** `tokens=True` reads `Authorization` values from file jars under
  `jar.store_root(env=env)` keyed by the origin's host (read at each request),
  a string names one key for every host, a jar object is used as given. A
  token is a per-request `Authorization`: `Bearer <token>`, or verbatim when it
  already names a scheme, never a client header, so it follows no redirect to
  another origin. An explicit `Authorization` header or `auth=` wins. A token
  containing a CR, LF or NUL is `ConfigurationError` naming the jar key, never
  the value.
- **Auth provider and hooks.** In `request()` (not `redirect()`),
  `auth_provider.ensure(client, url)` runs first and its errors are swallowed;
  then the `_PY` hooks (see "URL hooks") run on the caller's URL with the
  keyword arguments the call gave (`data`, `headers`, `stream`,
  `allow_redirects`, `timeout`, `deadline`, `auth`) as a mutable `kwargs`; one
  that sets another name is `TypeError`. A hook may return a response, which
  is used instead of sending. A request a provider or a hook makes through the
  client runs neither again; the guard is per thread, so another thread's
  requests still run them.
- **Negotiate and NTLM.** `negotiate=` (a `syshttp.negotiate.Negotiate`, see
  its section) configures the default transport as `proxymap` does: a transport
  of your own, or `SYSHTTP_DEFAULT_TRANSPORT`, beside it is refused. Without
  it the transport reads `SYSHTTP_NEGOTIATE` and its kin, which name no host by
  default.
- **Retries.** A status in `status_forcelist` (default `TRANSIENT_STATUSES`),
  or a failed connection (`ConnectionError`, not a timeout, not
  `NoReachableProxyError`), is sent again up to `retries` times (default 3) for
  `GET`, `HEAD`, `OPTIONS`, `PUT`, `DELETE`, `TRACE` and `PROPFIND` with a body
  that can be sent twice. None waits before the first retry, then `backoff`
  seconds doubled each time, never less than the reply's `Retry-After`, at most
  120 seconds; the `deadline` bounds the sum. A status that outlasts the
  retries is returned, not raised; a connection that never succeeds raises
  its last error. `retries=0` sends once.
- **Close.** `close()` (or leaving a `with` block) closes a transport the
  client made, never one it was given; a closed client makes a new one when
  used again.

```python
class HTTPResponse:
    status: int
    reason: str
    headers: Headers
    url: str
    def __init__(self, status, reason, headers, url, body=b"", *, decode=True): ...
    def read(self, size=-1): ...
    def iter_bytes(self, chunk_size=65536): ...
    def buffered(self): ...
    content: bytes                                   # property
    def text(self, encoding=None, errors="replace") -> str
    def json(self) -> Any
    def close(self): ...

class Headers:                                       # read-only Mapping, names case-blind
    def get_all(self, name): ...

class HTTPStatusError(Exception):
    response: HTTPResponse

def raise_for_status(resp): ...
def read_limited(resp, what, limit=None): ...
def json_body(resp, what, limit=None): ...
def drop_body(resp, limit=None): ...
def peer_text(text, limit=120): ...
def split_userinfo(url): ...
def is_redirect(resp): ...
```

- **`HTTPResponse`**: `status`, `reason`, `headers` (names compare without
  case, a name sent twice reads as `"a, b"` and `headers.get_all()` lists them;
  `repr()` shows names only), `url` (the URL requested, without fragment, an
  empty path `/`; through a gateway still the URL asked for), `read(size=-1)`,
  `iter_bytes(chunk_size)`, `buffered(limit=None)` (reads the rest of the body
  into memory, closes the connection and returns the response, which stays
  readable; more than `limit` decoded bytes, default `MAX_REPLY_BYTES`, is
  `OSError(EFBIG)`), `close()` and a context manager. A `gzip` or `deflate` body is
  decoded, in steps of at most 256 KiB, unless the request named an
  `Accept-Encoding` of its own (`identity` counts as none); `headers` stay as
  received, so `Content-Length` counts the encoded bytes. A body that ends
  before the length the server stated, a chunked body cut short and a coded
  body that is not valid are `OSError(EIO)`, never a shorter read.
  `content` is the rest of the decoded body, read on first use (at most
  `MAX_REPLY_BYTES`, else `OSError(EFBIG)` naming the URL as scheme, host,
  port and path) and kept, so `content`, `text()`
  and `json()` agree however often they are used; bytes already taken with
  `read()` are not in it. `text()` decodes with `encoding`, else the
  `charset` of `Content-Type`, else UTF-8, replacing what does not decode.
  `json()` parses it (`None` for an empty body); a body that is not JSON is
  `ResponseError` naming the status. A response built from `bytes` by a hook
  or a fake transport has all of this.
- `raise_for_status(resp)` raises `HTTPStatusError` (holding `response`) for a
  status of 400 or more. `read_limited(resp, what, limit=None)` is the whole
  decoded body, at most `limit` bytes (default `MAX_REPLY_BYTES`, 8 MiB after
  decoding; assign `syshttp.client.MAX_REPLY_BYTES` to allow more, it is read
  each time): more is `OSError(EFBIG)` naming `what`, and the connection is
  closed; `json_body()` is that, parsed (`ValueError` when it is not JSON).
  `drop_body(resp, limit=None)` gives up the body of a reply nobody looks at: it
  is read up to `limit` bytes so the connection can serve the next request,
  and `resp` is closed. `peer_text(text, limit=120)` is text from the other end
  (a reason phrase, a `Location`) as an error message may show it: control and
  bidirectional characters escaped, cut to `limit`. `split_userinfo(url)` is
  `(url_without_userinfo, (user, password) | None)`, the parts the octets their
  percent-escapes stand for; `is_redirect(resp)` says whether a reply is a
  301, 302, 303, 307 or 308 that names a `Location`.
- **`fetch(url, method="GET", *, headers=None, data=None, json=None,
  timeout=DEFAULT_TIMEOUT, client=None, transport=None, reauth=None,
  **client_options)`** sends one request and returns the `HTTPResponse` with
  its body read whole (`MAX_REPLY_BYTES` bounds it), whatever the status: take
  `.status`, `.headers`, `.content`, `.text()` or `.json()` from it. The return
  type never depends on an argument. `data` is bytes, text, a mapping
  (form-encoded, `Content-Type: application/x-www-form-urlencoded`) or a binary
  file; `json` is a value sent as JSON (`Content-Type: application/json`;
  `None` sends nothing); both is `ValueError`. It sends through `client` when
  given, left open, else through a new `HTTPClient(transport, **client_options)`
  closed after the call: `transport` is any object implementing the transport
  protocol (`None`: the `SYSHTTP_DEFAULT_TRANSPORT` setting's, else syshttp's
  own) and `client_options` are the other keywords of `HTTPClient`. A `client`
  beside `transport` or `client_options` is `ValueError`: a given client has
  them already. `timeout` is for this call, whatever the client's own is.
  `reauth` is called as `reauth(client, url)` (an object with
  `ensure(client, url)`, an `AuthProvider`, through that) once after a 401 or
  403, and the request is sent one more time; its errors are the caller's, and
  the body must be one that can be sent twice. `syshttp.fetch` is the same
  function: the root imports the client only when it is asked for.

### The transport protocol and the default transport (`syshttp.client`)

```python
class Transport(Protocol):
    def send(self, method, url, *, headers, body=None, timeout, stream=False) -> HTTPResponse: ...
    def close(self) -> None: ...

class PreparedRequest(NamedTuple):
    method: str; url: str; headers: dict[str, str]; body: Any
    timeout: tuple[float | None, float | None]; decode: bool

def prepare_request(method, url, *, headers, body=None, timeout) -> PreparedRequest

class HTTPTransport:
    def __init__(self, *, proxymap=None, env=None, ssl_context=None, proxy_ssl_context=None, verify=True,
                 negotiate: Negotiate | None = None)
    def send(self, method, url, *, headers, body=None, timeout, stream=False) -> HTTPResponse
    def close(self) -> None
```

`HTTPClient(transport=...)` takes any object with `send()` (a transport that
calls `requests`, `httpx`, a fake in a test); the client owns redirects,
credentials, cookies, tokens, hooks, retries and the deadline above it, so a
transport does none of them. Without one the client builds the transport the
`SYSHTTP_DEFAULT_TRANSPORT` setting names (read through the prefixes when the
client is made): an object reference `module:attr` or `<file>.py:attr` (a
dotted `attr` is allowed), resolved as a `_PY` hook is (`hooks.load_object`).
The object is the transport when it has `send()`; a class or factory (anything
else callable) is called with no arguments to make one, which the client then
closes. A value that cannot be imported, resolved or called, or whose result
has no `send()`, is `ConfigurationError` naming the variable, never a silent
fallback; `proxymap`, `ssl_context`, `proxy_ssl_context` and `verify` beside a
setting, or beside a `transport` of your own, are refused. Precedence: an
explicit `transport=`, then the setting, then `HTTPTransport`. The setting
names code to import: never let an untrusted party set the environment of a
process using syshttp.

- **The contract.** `send()` makes exactly one request: it follows no
  redirect, adds no credentials of the caller's and retries nothing but what is
  said below. `body` is `None`, `bytes`, a binary file or an iterable of
  `bytes` (never `str`: `TypeError`), sent under a `Content-Length` when its
  length is known without reading it (`bytes`, a list or tuple of `bytes`, a
  seekable file, a regular file), else `Transfer-Encoding: chunked`; a
  `Content-Length` in `headers` is trusted (a longer body is cut there, a count
  larger than a known length or not a number is `ValueError`, a body that runs
  out first is `OSError(EIO)`). `timeout` is seconds, a `(connect, read)` pair
  or `None`; the read half bounds each wait on the server. With `stream=False`
  the body has been read when `send()` returns (a body that decodes to more
  than `MAX_REPLY_BYTES` is `OSError(EFBIG)`); with `stream=True` it is read
  from the response, which the caller closes. A transport raises only
  `TimeoutError`, `ConnectionError`, `ssl.SSLError`, `ValueError` (before
  anything is sent: a header or URL with a control character, a URL with
  credentials, another scheme) or else `OSError(EIO)`; no third-party
  exception and no URL or header value in its text. A reply below 200 is never
  the one it returns. It builds the answer as `HTTPResponse(status, reason,
  headers, url, body, decode=...)` with `body` as `bytes` or an object with
  `read(amount)` and `close()`.
- **`prepare_request(method, url, *, headers, body=None, timeout)`** is the
  arguments of `send()` as the contract reads them, so a transport that starts
  with it refuses what `HTTPTransport` refuses and frames a body the same way:
  `method` upper-cased, the fragment dropped from `url`, `headers` a `dict` of
  text values with the `Content-Length` of a body whose length is known (`0`
  for a `PATCH`, `POST` or `PUT` without one) and `Accept-Encoding: gzip,
  deflate` unless the caller named an encoding, `body` an object that yields
  exactly `Content-Length` bytes or an iterable to send chunked, `timeout` the
  pair, `decode` what to pass as `HTTPResponse(..., decode=decode)`. It raises
  `ValueError` for a method or header name that is not a token, a value or
  URL with a control character, a URL with credentials or another scheme, a
  `Content-Length` that is not a count of bytes or exceeds the body, and a
  timeout that is not a positive finite number, `None` or a pair of them;
  `TypeError` for a `str` body. No message quotes the URL or a header value.
- **What `HTTPTransport` does that another transport must do itself** (the
  client does none of it): routing by the proxy map (`proxymap`, `env`: probing,
  failover, proxies, `CONNECT`, gateways, a proxy's credentials), TLS
  verification (`ssl_context`, `proxy_ssl_context`, `verify`, `CA_BUNDLE`, the
  system's context), connection reuse (one idle connection per route and
  thread, at most 8, closed when the thread ends or on `close()`; reused only
  if the server has not closed it or sent bytes on it; an idempotent request
  that fails before any byte of a reply on a reused connection is sent once
  more on a new one, any other request reuses a connection only if it carried
  a reply within the last second), skipping interim (1xx) replies (at most 8),
  decoding `gzip` and `deflate`. A transport written on another library
  therefore gets the library's own proxy and TLS behaviour, not syshttp's,
  unless it implements them; it can still be used by `fetch(transport=...)`.
  `HTTPTransport` adds to the contract's exceptions
  `proxylib.NoReachableProxyError`, `proxylib.UnsupportedProxyError` and
  `ConfigurationError`, and `NegotiationError` or `NegotiateUnavailableError`
  for a server or proxy the `negotiate` policy names.

## Negotiate and NTLM (`syshttp.negotiate`)

```python
class Negotiate:
    def __init__(self, hosts: str | Iterable[str] | None = None, proxies: str | Iterable[str] | None = None, *,
                 username: str | None = None, password: str | None = None, plain_http: bool | None = None,
                 max_legs: int | None = None, max_token: int | None = None, env: HTTPEnv | None = None) -> None
    def settings(self) -> NegotiateSettings
    def wants(self, host: str, *, proxy: bool = False) -> bool

@dataclass(frozen=True)
class NegotiateSettings: hosts: tuple[str, ...]; proxies: tuple[str, ...]; plain_http: bool; max_legs: int; max_token: int; explicit_credentials: bool

def has_negotiate() -> bool
DEFAULT_MAX_LEGS = 5; DEFAULT_MAX_TOKEN = 65536
NEGOTIATE = "SYSHTTP_NEGOTIATE"; PROXY_NEGOTIATE = "SYSHTTP_PROXY_NEGOTIATE"
NEGOTIATE_USER = "SYSHTTP_NEGOTIATE_USER"; NEGOTIATE_PASSWORD = "SYSHTTP_NEGOTIATE_PASSWORD"
NEGOTIATE_PLAIN_HTTP = "SYSHTTP_NEGOTIATE_PLAIN_HTTP"
NEGOTIATE_MAX_LEGS = "SYSHTTP_NEGOTIATE_MAX_LEGS"; NEGOTIATE_MAX_TOKEN = "SYSHTTP_NEGOTIATE_MAX_TOKEN"   # setting names
```

`pip install "syshttp[negotiate]"` (pyspnego) is the one dependency; `kerberos`
adds `gssapi` for the credential cache on Linux and macOS. `import syshttp`,
`syshttp.negotiate` and `syshttp.client` import neither; pyspnego is imported
at the first handshake.

- **Off by default.** `HTTPTransport(negotiate=...)` and
  `HTTPClient(negotiate=...)` take a `Negotiate`; with none given the transport
  uses `Negotiate(env=env)`. A `401` with `WWW-Authenticate: Negotiate` or `NTLM`
  and a `407` with `Proxy-Authenticate` are answered only for a host the policy
  names; any other is the reply, as for any client. `hosts` (else
  `SYSHTTP_NEGOTIATE`) names servers and `proxies` (else `SYSHTTP_PROXY_NEGOTIATE`)
  proxies, by the host of the proxy: a comma list or an iterable of host names,
  `*.suffix` for every host below a domain (not the domain), `*` for all; an
  empty list is none and beats the variable. A host name is compared without
  case, brackets or a trailing dot.
- **The exchange.** The transport sends the same request again with `Authorization:
  <Negotiate|NTLM> <base64 token>` (`Proxy-Authorization` for a proxy) on the
  connection the challenge came on, with `Connection: keep-alive`, until the reply
  is not the challenge again; `Negotiate` is preferred when a reply offers
  both. A `CONNECT` the proxy answers `407` is answered the same way, on the
  proxy connection, before the tunnel is made; a proxy's challenge is
  answered before a server's, each once. The body of a challenge is read (up to
  64 KiB) and dropped; the reply that follows is what `send()` returns, and
  the connection, now authenticated, goes back to the pool. The server's
  closing token is taken from that reply when the mechanism proves the server
  (Kerberos): a reply of 400 or more is returned unchecked; an incomplete
  exchange with no closing token, or one the token does not complete, is
  `NegotiationError`; NTLM has none.
- **Not answered** (the reply is returned): the request names an `Authorization`
  (a `Proxy-Authorization` for a proxy challenge), the proxy has a credential of
  its own (userinfo, headers), the body cannot be sent twice (a file, an
  iterable), the route is a prefix gateway, or the reply offers neither scheme. A
  plain-http server behind a proxy that also challenges is answered after the
  proxy, but the proxy's token is not repeated on the server's legs: a
  Kerberos proxy asks again and its `407` is returned. A transport of your own
  does its own authentication.
- **Identity.** `username` and `password` (else `SYSHTTP_NEGOTIATE_USER` and
  `SYSHTTP_NEGOTIATE_PASSWORD`, both or `ConfigurationError`) are one identity
  for every host the policy names, as `DOMAIN\user` or `user@REALM`; with none,
  the Windows logon session (SSPI) or the Kerberos credential cache. The
  password is a secret held by the object and in no `repr()`, message, log
  line or exception attribute; `repr(Negotiate)` says `credentials=explicit`
  or `logon`, `NegotiateSettings` holds `explicit_credentials`, never the
  identity. A caller's bad argument is `ValueError` or `TypeError` (a half
  identity, a line break in either part, `max_legs` below 1, a host that is not a
  name or pattern); a variable that cannot be used is `ConfigurationError`
  naming it, refused when the transport is made.
- **Plain http.** A handshake over `http:` (the server's scheme; for a proxy
  challenge the proxy URL's) to a host that is not `localhost`, `127.0.0.0/8` or
  `::1` is `NegotiationError` naming `SYSHTTP_NEGOTIATE_PLAIN_HTTP`, before any
  token is made. `plain_http=True` (else the variable, a boolean) allows it;
  each such server or proxy is then logged once per transport at WARNING, under
  `syshttp.client`, as `weakened`. An `https:` server through a proxy is judged
  by its own scheme.
- **Limits.** `max_legs` (default 5, `SYSHTTP_NEGOTIATE_MAX_LEGS`) is the most
  authenticated requests of one handshake: NTLM takes two, Kerberos one or two.
  `max_token` (default 65536, `SYSHTTP_NEGOTIATE_MAX_TOKEN`) is the most
  bytes of a token, sent or received. Past either: `NegotiationError`, and
  nothing more is sent.
- **Failures.** `NegotiationError` (message: the host and port, the
  mechanism, never a token or a credential): the credentials refused (the
  challenge again), a challenge answered with a token that is not valid
  base64, a server that closes the connection or sends more than 64 KiB between
  legs, a limit, the library's own failure (`__cause__`), a refusal over plain
  http. `NegotiateUnavailableError` (also `ImportError`): pyspnego is
  missing or does not import, naming `pip install "syshttp[negotiate]"`; raised
  only for a host the policy names. A handshake is never sent again by
  syshttp: `NegotiationError` is not a `ConnectionError`, so the client's retries
  do not repeat it.
- **Channel binding** (Extended Protection for Authentication) is not sent: a
  server that requires it refuses the exchange. `has_negotiate()` is whether
  pyspnego imports.

## Exceptions (`syshttp.exceptions`)

```python
class SysHTTPError(Exception)
class ConfigurationError(SysHTTPError, ValueError)
class HookError(SysHTTPError, RuntimeError)
class ResponseError(SysHTTPError, ValueError)
class NegotiationError(SysHTTPError)
class NegotiateUnavailableError(NegotiationError, ImportError)
```

- `SysHTTPError` is the base of what goes wrong at run time. proxylib's own
  errors (`NoReachableProxyError`, `UnsupportedProxyError`, `ProxyParseError`)
  pass through as they are.
- `ConfigurationError`: a setting or stored credential that cannot be used
  (a malformed `SYSHTTP_PROXY_TYPE`, a regular expression that does not compile,
  a hook that cannot be loaded, a token with a line break, a malformed
  `SYSHTTP_PREFIX`). The message names the variable or key, never a secret.
- `HookError`: a `_PY` hook failed; the hook's own exception is `__cause__`.
- `ResponseError`: a body that is not the JSON `HTTPResponse.json()` was asked for.
- `NegotiationError`: a Negotiate or NTLM handshake that did not authenticate
  (see "Negotiate and NTLM"); `NegotiateUnavailableError` is the one raised when
  pyspnego is missing or does not import, naming the `negotiate` extra. The
  message names the host, never a token or a credential.
- A caller's own mistake is a plain `ValueError` or `TypeError`, not one of
  these: a malformed `prefixes=` argument, `verify=False` beside `ssl_context`,
  a `client` beside `client_options` in `fetch()`, an unknown patch target.

## Jars (`syshttp.jar`)

```python
def store_root(*, env=None) -> Path
def default_root(*, env=None) -> Path
def safe_name(key: str) -> str
class FileCookieJar:  def __init__(self, root: Path | None = None, *, env=None)
class FileTokenJar:   def __init__(self, root: Path | None = None, *, env=None)
class MemoryCookieJar(dict)
class MemoryTokenJar(dict)
class CookieJar(Protocol); class TokenJar(Protocol)   # __getitem__, __setitem__, get
```

- `store_root()` returns `SYSHTTP_HOME` (a leading `~` expanded), else
  `default_root()`: a directory `syshttp` under `%LOCALAPPDATA%` (Windows),
  `~/Library/Application Support` (macOS) or `$XDG_STATE_HOME` /
  `~/.local/state` (elsewhere).
- Cookies live in `<root>/cookies/<host>.txt` (Netscape), tokens in
  `<root>/tokens/<host>.token`.
- Both are secrets and are written as such: mode `0600` (directories this
  library creates `0700`; an existing directory keeps its mode), replaced
  whole by a rename so a reader sees the old file or the new one, with LF line
  ends on every platform. `cookies.save_netscape` does the same. The
  constructors do nothing on disk: the directory is created at the first
  write.
- `get()` returns the default on any read error. Token values are never
  logged.
- A client saves a host's cookie file only when its cookies differ from
  those last loaded or saved. A token file is read at every request.

## Cookies (`syshttp.cookies`)

```python
@dataclass(frozen=True)
class CookieSpec: domain: str; path: str; secure: bool; expires: int | None; name: str; value: str; http_only: bool = False; subdomains: bool = False
def load_netscape(path: Path) -> list[CookieSpec]
def save_netscape(session_cookies: Iterable[CookieLike], path: Path) -> None
def cookie_applies(cookie: CookieSpec, url: str, now: float | None = None) -> bool
def set_cookie_specs(values: Iterable[str], default_domain: str, now: float | None = None, *,
                     request_path: str = "/",
                     aliases: Mapping[str, str] | None = None) -> list[tuple[CookieSpec, bool]]
def domain_covers(domain: str, host: str) -> bool
def host_aliases(groups: Iterable[Iterable[str]]) -> dict[str, str]
HTTP_ONLY_PREFIX = "#HttpOnly_"
MAX_COOKIE_AGE = 400 * 24 * 3600
```

- `load_netscape` returns `[]` for a missing file, reads `#HttpOnly_` rows,
  keeps a row whose value is empty and treats an unreadable expiry as a
  session cookie. Lines end at `\n` only (one trailing `\r` is taken off), so
  a character `str.splitlines()` ends a line at (`\x0b`, `\x0c`, `\x85`)
  cannot start a row inside a value; a row whose name or value holds a control
  character is skipped. `save_netscape` writes `#HttpOnly_` rows as curl does,
  and writes no row with a control character or a tab in a field.
- `cookie_applies` decides as curl does: the domain (a subdomain only with a
  leading dot or the include-subdomains flag, and an IP only matches
  itself), the RFC 6265 path match, `Secure` only over https or to loopback,
  not expired (`0` / `None` is a session cookie).
- `set_cookie_specs` returns `(cookie, gone)` per `Set-Cookie` value, parsed
  as RFC 6265 section 5.2 reads it: the name and value up to the first `;`
  (a value may hold spaces, `=` or JSON), attribute names in any case,
  unknown attributes (`Priority`, `Partitioned`) ignored, `Max-Age` beating
  `Expires` in either order, an HTTP date in any of its three forms read as
  UTC, and an expiry beyond 400 days cut to `MAX_COOKIE_AGE`. A header with
  no `name=value` is skipped. `gone` marks a cookie the server expired (an
  empty value, `Max-Age` of zero or less, a past date).
  - `default_domain` is the host asked. A `Domain` attribute is kept only
    when that host domain-matches it, on a set and on a deletion alike;
    otherwise the cookie is skipped. It then gives `subdomains=True`. With no
    `Domain`, or with one equal to an IP-literal host, the cookie is
    host-only. A `Domain` that is a public suffix is skipped unless it
    equals the host (`localhost`, `wiki`), which gives a host-only cookie.
  - A public suffix is recognised without the Public Suffix List: a name
    with no dot (a top level domain) or a registry under a two-letter country
    code (`co.uk`, `com.au`). A shared suffix such as `github.io` is not
    recognised, so a site there can set a `Domain` cookie for it.
  - A cookie with no `Path` gets the directory of `request_path` (the
    request's path; RFC 6265 section 5.1.4: `/app/login` is `/app`).
- `FileCookieJar` keeps `HttpOnly` and the include-subdomains flag. A
  by-host file holds every cookie that applies to its host, one a host set
  for a parent domain (`Domain=example.com` from `www.example.com`) included.
- `host_aliases(groups)` maps each host of each group (lower case, IPv6
  brackets and a trailing dot removed) to the group's first host; a group of
  one host is no alias. A host that is not a name or an IP address (a port,
  a path, a blank) or that is in two groups raises `ValueError`; a group
  given as one string, `TypeError`. `set_cookie_specs` takes the mapping as
  `aliases`, and `HTTPClient` applies its `cookie_hosts` rules with it.

## URL hooks (`syshttp.hooks`)

```
SYSHTTP_HOOKS_<KEY>=<regex>                re.search against the caller's URL
SYSHTTP_HOOKS_<KEY>_PY=<module:callable>   syshttp calls callable(client, method, url, kwargs)
SYSHTTP_HOOKS_<KEY>_CURL=<command>         a curl front end runs this in its place, its argv appended
```

```python
class Hook:  key, pattern, curl, py, variable; matches(url) -> bool
def hooks_from_env(*, env=None) -> list[Hook]
def matching(url: str, *, kind: str | None = None, env=None) -> list[Hook]
def skipped(*, env=None) -> set[str]
def call_py_hooks(client, method, url, kwargs, *, env=None) -> HTTPResponse | None
def load_callable(spec: str) -> PyHook
def load_object(spec: str, what: str = "an object") -> Any
def split_command(value: str) -> list[str]
def curl_command(hook: Hook, python: str | None = None) -> list[str]
def wrapper_environment(hook: Hook, url: str, entry: str, *, env=None) -> dict[str, str]
```

- Hooks run in KEY order. A `_PY` hook returning non-`None` is used as the
  response and ends the chain; the response is an `HTTPResponse`. `kwargs`
  holds the keyword arguments the `HTTPClient.request()` call gave and is
  mutable (a name `request()` does not take is `TypeError`). A hook declared without
  a `_PY` or `_CURL` target is ignored, and so is a target without a
  pattern, or a blank one.
- KEYs are compared without regard to case (`Hook.key` is upper-case, as
  Windows holds variable names): `HOOKS_mykey` and `HOOKS_MYKEY` are one
  hook, and `HOOK_SKIP=mykey` suppresses it.
- `SYSHTTP_HOOK_SKIP` (a comma list of KEYs) suppresses hooks.
- `load_callable` accepts `module:attr` or `<file>.py:attr` (`attr` may be
  dotted); `load_object` is the same lookup without the callable check, the
  loader `SYSHTTP_DEFAULT_TRANSPORT` shares. A file is loaded once per process, by its resolved path, as a
  `module` is imported once: its module-level state lives on between requests
  and a later edit is not picked up. Two files named alike are two modules.
- A failing `_PY` hook raises `RuntimeError` naming the variable, the target,
  the method and the URL as scheme, host, port and path (no userinfo, query
  or fragment); the hook's own exception is chained and not rewritten.
- `curl_command` splits a shell-quoted command line. Backslashes are
  literal, a bare existing path is one program, and a leading `.py` runs
  under `python`.
- `wrapper_environment` returns the `SYSHTTP_HOOK_URL`, `SYSHTTP_HOOK_KEY`,
  `SYSHTTP_HOOK_CURL` and `SYSHTTP_HOOK_SKIP` (this KEY added) variables a
  `_CURL` wrapper run needs, each under the first prefix.

## TLS and retry (`syshttp.tls`, `syshttp.retry`)

```python
def new_os_context(cafile: str | None = None, capath: str | None = None, *,
                   client_certificates: bool = True) -> ssl.SSLContext
def os_ssl_context() -> ssl.SSLContext
OS_CONTEXT_MAX_AGE = 60
TRANSIENT_STATUSES = (408, 429, 500, 502, 503, 504)
def retry_after(headers: Iterable[tuple[str, str]], now: float | None = None) -> float | None
```

- `new_os_context()` without `cafile`/`capath` is
  `sslcontext.system_context()`. On Python 3.10+ it is a
  `truststore.SSLContext`: the operating system verifies the chain
  (CryptoAPI on Windows, the Security framework on macOS, OpenSSL over the
  system store elsewhere), so OpenSSL's CRL flags have no effect on it. On
  3.9 OpenSSL verifies over the default store. A server that asks for a
  client certificate gets one from the OS store (the Windows Personal store
  and smart cards, the macOS keychains, the default PKCS#11 module), chosen
  as a browser chooses (the remembered choice, the Edge/Chrome
  `AutoSelectCertificateForUrls` policy, the only candidate), or none.
  `client_certificates=False` never offers one: pass it before loading a
  certificate of your own, which a store certificate would otherwise
  replace. With `cafile`/`capath` it is a plain `ssl` context trusting only
  them, offering no store certificate.
- `os_ssl_context()` is shared for `OS_CONTEXT_MAX_AGE` seconds, because
  the clients that pool connections by context object (urllib3) would never
  reuse one otherwise. It is what `syshttp.client` verifies with by default.
  Never load a client certificate into it; use
  `new_os_context(client_certificates=False)`.
- `retry_after` reads a number of seconds (the digits `0-9` only) or an HTTP
  date, a date without a zone being UTC. It returns `None` when the header
  is absent or unreadable.

## Import-time patching (`syshttp.autopatch`)

```python
SETTING = "SYSHTTP_IMPORTPATCH"
TARGETS = {"requests": "requests", "urllib": "urllib.request", "httpx": "httpx", "aiohttp": "aiohttp",
           "pip": "pip._vendor.requests"}
def setting_name(*, env=None) -> str
def enabled(*, env=None) -> frozenset[str]
def importpatch(name: str, module: ModuleType) -> None   # importpatch's entry point
def patch(targets: Iterable[str] | None = None) -> tuple[str, ...]
def unpatch() -> None
def patched() -> tuple[str, ...]
```

- `SYSHTTP_IMPORTPATCH` patches client libraries as they are imported, in
  any program run by an interpreter of the environment. It is read under the
  prefixes like every setting (`SYSHTTP_PREFIX=AGENTS_`:
  `AGENTS_SYSHTTP_IMPORTPATCH`; `setting_name()` is the variable found, else
  the name under the first prefix). Values:
  `1`/`true`/`yes`/`on` for every target, `0`/`false`/`no`/`off`, empty or
  unset for none, else target names separated by `:` (`requests:httpx`;
  `urllib.request` means `urllib`). An unknown name is
  logged at WARNING and skipped. Read when the library is imported.
- The mechanism is importpatch (a dependency): its `.pth` hooks imports at
  interpreter start, and syshttp's `importpatch` entry points name
  `syshttp.autopatch` for `requests`, `urllib.request`, `httpx` and
  `aiohttp`. `IMPORTPATCH_DISABLE=1` turns every importpatch hook off.
  `patch(targets=None)` applies the patches from code whatever the setting
  says (every installed target by default; a named one that is not installed
  raises its `ImportError`, an unknown name `ValueError`); `unpatch()` undoes
  them, though a client built while patched keeps what it was given.
- What a patched library does: routing is proxylib's integration for that
  client (`proxylib.patch(proxy.proxy_map(), targets=[name])`, the newest
  patch winning, as proxylib's own `PROXYLIB_IMPORTPATCH` would install it);
  TLS is syshttp's: with verification on and no TLS argument of the
  caller's, the system's context.
  - **requests**: new `Session`s mount proxylib's `ProxyMapAdapter`:
    entries tried in order. A proxy the caller gives (`proxies=` on the
    call, or `session.proxies`) is used as given, without syshttp's
    credential, and a session with `trust_env = False` is left to requests.
    Every `HTTPAdapter` with `verify=True` and no context of its own pool
    manager verifies with `tls.os_ssl_context()`.
  - **urllib**: proxylib's global opener (installed when the program has
    not installed its own) routes `urlopen`, through the first reachable
    entry (`Probed`; none reachable: `URLError` whose `reason` is
    `NoReachableProxyError`). A credential under another header than
    `Proxy-Authorization` cannot go to an https proxy:
    `proxylib.UnsupportedProxyError`. `ssl._create_default_https_context`
    returns a system context, so `http.client` and every caller that gives
    no context verify with it (one context of its own, shared 60 s:
    http.client sets ALPN on it).
  - **httpx**: `Client` / `AsyncClient` built without `transport`, `proxy`,
    `proxies` or `mounts` get proxylib's `ProxyTransport` /
    `AsyncProxyTransport`; `verify` left at `True` becomes the system
    context (a fresh one offering no store certificate when `cert=` is
    given).
  - **aiohttp**: `ClientSession` requests without `proxy=` are routed by
    proxylib, with failover. A URL-prefix gateway is not followed:
    `proxylib.UnsupportedProxyError`. `ssl` left at `True` with no
    `ssl_context` / `verify_ssl` / `fingerprint` becomes the system context.
  - **pip** (`pip._vendor.requests`): every adapter pip mounts routes
    through the map, as proxylib's `pip` target does; `pip --proxy` and
    `--no-proxy-env` keep pip's own choice. pip keeps its own TLS context
    (truststore).
- Not patched: urllib3 used directly, websocket libraries.
- proxylib's own `PROXYLIB_AUTOPROXY` names clients that use
  `proxylib.auto_proxy()`; a client syshttp patches uses syshttp's map
  instead (the newer patch wins).

## Environment variables

| Variable | Sets | Default |
| --- | --- | --- |
| `SYSHTTP_PREFIX` | the prefixes every variable below is read under, `:`-separated, in order; read as written | none (the names as written) |
| `SYSHTTP_PROXY` | the proxy URL (`http://`, `https://`, or a bare `host:port`) | the request's scheme's `*_PROXY` variable, else `ALL_PROXY` (lowercase first); with none set, the system's configuration for the URL |
| `SYSHTTP_SYSTEM_PROXY` | whether the system's proxy configuration is consulted (boolean) | on |
| `SYSHTTP_PROXY_AUTH` | **secret**: `SYSHTTP_PROXY`'s credential, a header value sent verbatim | the URL's userinfo as Basic |
| `HTTP_PROXY_AUTH` | **secret**: the machine's proxy's credential (a `*_PROXY` variable's or the system's), as `Proxy-Authorization` | the URL's userinfo as Basic |
| `SYSHTTP_PROXY_AUTH_HEADER` | the header name `SYSHTTP_PROXY_AUTH` rides in | `Proxy-Authorization` |
| `SYSHTTP_PROXY_TYPE` | `connect` or `prefix[:/endpoint]` | `connect` |
| `SYSHTTP_NEGOTIATE` | the servers whose Negotiate or NTLM challenge is answered: comma list of host names, `*.suffix`, `*` | none |
| `SYSHTTP_PROXY_NEGOTIATE` | the same for proxies, by the proxy's host | none |
| `SYSHTTP_NEGOTIATE_USER` | the explicit identity's name, `DOMAIN\user` or `user@REALM` (with `_PASSWORD`) | the logon session or credential cache |
| `SYSHTTP_NEGOTIATE_PASSWORD` | **secret**: the explicit identity's password | none |
| `SYSHTTP_NEGOTIATE_PLAIN_HTTP` | boolean: authenticate over plain http to a host that is not loopback (logged as a weakening) | off |
| `SYSHTTP_NEGOTIATE_MAX_LEGS` | most authenticated requests of one handshake | 5 |
| `SYSHTTP_NEGOTIATE_MAX_TOKEN` | most bytes of one token, sent or received | 65536 |
| `SYSHTTP_HOME` | the jar root | the per-user state directory |
| `SYSHTTP_COOKIE_HOSTS` | groups of hosts that share cookies: hosts split by `,`, groups by `;` (`HTTPClient`) | none |
| `SYSHTTP_DEFAULT_TRANSPORT` | the transport of an `HTTPClient` (and `fetch()`) given none: `module:attr` or `<file>.py:attr`, an object with `send()` or something that makes one. It names code to import | syshttp's `HTTPTransport` |
| `SYSHTTP_IMPORTPATCH` | which client libraries are patched on import (`1` for all, or `:`-separated names: `requests`, `urllib`, `httpx`, `aiohttp`, `pip`) | none |
| `SYSHTTP_HOOKS_<KEY>` (+ `_PY`, `_CURL`) | a URL hook | none |
| `SYSHTTP_HOOK_SKIP` | KEYs of hooks not to run, comma list | none |
| `HTTP_PROXY`, `HTTPS_PROXY`, `FTP_PROXY`, `WS_PROXY`, `WSS_PROXY`, `ALL_PROXY` (either case, lowercase first) | the machine's proxy, per scheme | none |
| `NO_PROXY` / `no_proxy` | hosts that go direct | none |
| `CA_BUNDLE` | the CA bundle a client's `verify=True` uses (`REQUESTS_CA_BUNDLE` / `CURL_CA_BUNDLE` are not read) | the OS verifier |

Each of these is read under every prefix of `SYSHTTP_PREFIX`. A `_CURL`
hook's wrapper runs with `SYSHTTP_HOOK_URL`, `SYSHTTP_HOOK_KEY`,
`SYSHTTP_HOOK_CURL` and `SYSHTTP_HOOK_SKIP` set under the first prefix
(`hooks.wrapper_environment`); a curl front end reads them back.

Read as written, never prefixed: `LOCALAPPDATA` (Windows) and
`XDG_STATE_HOME` (Linux and other POSIX) for the per-user state directory;
importpatch's `IMPORTPATCH_DISABLE` (`1` turns every import-time patch off);
proxylib's own `PROXYLIB_IMPORTPATCH` and `PROXYLIB_AUTOPROXY`.

## Gotchas

- With no proxy variable set, the system's configuration routes requests:
  on a machine with a corporate PAC script, traffic goes where the browser's
  would. `SYSHTTP_SYSTEM_PROXY=0` stops that.
- `SYSHTTP_PREFIX=MYTOOL_` reads `MYTOOL_<NAME>` only: `SYSHTTP_PROXY` and
  the machine's `HTTPS_PROXY` are then ignored. Add the empty entry
  (`MYTOOL_:`) to fall back to them.
- A malformed `SYSHTTP_PROXY_TYPE` is harmless until `SYSHTTP_PROXY` is set.
- Pass `root=` to keep jar files out of the user's state directory.
- A client certificate loaded into the context you pass is used for every
  https host the client talks to, redirects included. Give a client an
  identity only for hosts that should see it.
- `verify=False` logs a warning under the `syshttp.client` logger when the
  transport is made, and changes no process-wide warning filter.
- A `_PY` hook and `SYSHTTP_DEFAULT_TRANSPORT` name code to import. Never let
  an untrusted party set the environment of a process using syshttp.
- A client keeps the cookies its responses set for its whole life, as a
  session does: build one per identity, or pass `cookies=` a jar of its own.
- Negotiate and NTLM send nothing until `SYSHTTP_NEGOTIATE` or
  `SYSHTTP_PROXY_NEGOTIATE` (or a `Negotiate(hosts=...)`) names the host: the
  logon identity is released only to hosts you list, never to whatever
  challenges. Over plain http, to anything but loopback, it needs
  `SYSHTTP_NEGOTIATE_PLAIN_HTTP` as well.
- In a venv of the Windows ARM64 CPython 3.9 and 3.14 tested (cryptography
  50.0.2, pyspnego 0.12.4), `import spnego` fails with "DLL load failed" until
  the interpreter's `DLLs` directory is on the DLL search path
  (`os.add_dll_directory`), and then warns that OpenSSL's legacy provider did
  not load, which leaves pyspnego's own NTLM without RC4; SSPI, once the import
  works, does not need it. `has_negotiate()` is the probe, and a handshake that
  needs what is missing is `NegotiationError` or `NegotiateUnavailableError`.
