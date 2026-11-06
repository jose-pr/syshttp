# Settings

Every setting is an environment variable with a full name: syshttp's own
carry `SYSHTTP_`, the conventional ones keep theirs. Each is read as
`<PREFIX><NAME>` for every prefix of `SYSHTTP_PREFIX` in turn (a
`:`-separated list, used literally), the first one set winning, each name on
its own. With `SYSHTTP_PREFIX` blank or unset there is one empty prefix: the
names as written below. A setting given as an argument wins over its
variable, and the variable wins over the built-in default. Variables are
read when they are needed, never at import.

| Variable | Sets | Default |
| --- | --- | --- |
| `SYSHTTP_PREFIX` | the prefixes every variable below is read under, in order; itself read as written | none |
| `SYSHTTP_PROXY` | the proxy URL | the request's scheme's `*_PROXY` variable, else `ALL_PROXY` (lowercase first); with none set, the system's configuration for the URL |
| `SYSHTTP_SYSTEM_PROXY` | whether the system's proxy configuration is consulted (`0`/`false`/`no`/`off` to stop) | on |
| `SYSHTTP_PROXY_AUTH` | `SYSHTTP_PROXY`'s credential, a header value sent verbatim to it only (a secret) | the URL's userinfo as Basic |
| `SYSHTTP_PROXY_AUTH_HEADER` | the header `SYSHTTP_PROXY_AUTH` rides in | `Proxy-Authorization` |
| `SYSHTTP_PROXY_TYPE` | `connect`, or `prefix[:/endpoint]` for a URL-prefix gateway | `connect` |
| `SYSHTTP_NEGOTIATE` | the servers whose `Negotiate` or `NTLM` challenge is answered: a comma list of host names, `*.suffix` for a domain, `*` for all; needs the `negotiate` extra | none |
| `SYSHTTP_PROXY_NEGOTIATE` | the same for proxies, by the proxy's host | none |
| `SYSHTTP_NEGOTIATE_USER`, `SYSHTTP_NEGOTIATE_PASSWORD` | an explicit identity (`DOMAIN\user` or `user@REALM`) for every allowed host; both or neither; the password is a secret | the logon session (SSPI) or the Kerberos credential cache |
| `SYSHTTP_NEGOTIATE_PLAIN_HTTP` | whether to authenticate over plain http to a host that is not loopback (boolean); each such host is logged as a weakening | off |
| `SYSHTTP_NEGOTIATE_MAX_LEGS` | most authenticated requests of one handshake | 5 |
| `SYSHTTP_NEGOTIATE_MAX_TOKEN` | most bytes of one token, sent or received | 65536 |
| `SYSHTTP_HOME` | the directory of the cookie and token jars | the per-user state directory |
| `SYSHTTP_COOKIE_HOSTS` | groups of hosts that share cookies: hosts split by `,`, groups by `;` | none |
| `SYSHTTP_IMPORTPATCH` | client libraries patched as they are imported to use the system proxy and TLS: `1` for all, or `:`-separated names from `requests`, `urllib`, `httpx`, `aiohttp`, `pip` | none |
| `SYSHTTP_HOOKS_<KEY>` | a URL hook's pattern; `_PY` and `_CURL` name its targets | none |
| `SYSHTTP_HOOK_SKIP` | KEYs of hooks not to run | none |
| `HTTP_PROXY`, `HTTPS_PROXY`, `FTP_PROXY`, `WS_PROXY`, `WSS_PROXY`, `ALL_PROXY` | the machine's proxy, per scheme (either case, lowercase first) | none |
| `HTTP_PROXY_AUTH` | the machine's proxy's credential (a `*_PROXY` variable's or the system's), sent as `Proxy-Authorization` (a secret) | the URL's userinfo as Basic |
| `NO_PROXY` / `no_proxy` | hosts that never go through the proxy | none |
| `SYSHTTP_DEFAULT_TRANSPORT` | the transport of an `HTTPClient` (and `fetch()`) given none: `module:attr` or `<file>.py:attr`; names code to import | syshttp's own |
| `CA_BUNDLE` | the CA bundle a client's `verify=True` uses; requests' `REQUESTS_CA_BUNDLE` / `CURL_CA_BUNDLE` are not read | the OS verifier |

A `_CURL` hook's wrapper runs with `SYSHTTP_HOOK_URL`, `SYSHTTP_HOOK_KEY`,
`SYSHTTP_HOOK_CURL` and `SYSHTTP_HOOK_SKIP` set under the first prefix; a
curl front end reads them back.

Read as written, never prefixed: `LOCALAPPDATA` (Windows) and
`XDG_STATE_HOME` (Linux and other POSIX) for the per-user state directory,
importpatch's `IMPORTPATCH_DISABLE`, and proxylib's own
`PROXYLIB_IMPORTPATCH` and `PROXYLIB_AUTOPROXY`.

## Prefixes

A tool that embeds syshttp opts out of the defaults with a prefix of its own:

```sh
SYSHTTP_PREFIX=MYTOOL_ MYTOOL_HTTPS_PROXY=http://proxy.internal:3128 mytool ...
```

reads `MYTOOL_HTTPS_PROXY`, `MYTOOL_SYSHTTP_HOME`, `MYTOOL_CA_BUNDLE` and so
on, and ignores the machine's `HTTPS_PROXY`. With the empty entry last,
`SYSHTTP_PREFIX=MYTOOL_:`, each variable falls back to its unprefixed name:
`MYTOOL_HTTPS_PROXY` over `HTTPS_PROXY`, while an unset `MYTOOL_NO_PROXY`
leaves the machine's `NO_PROXY` in force.

Inside one process, separate configurations use separate `HTTPEnv` objects:

```python
from syshttp import HTTPEnv, proxy

corp = HTTPEnv("CORP_")                      # CORP_SYSHTTP_PROXY, CORP_HTTPS_PROXY, ...
lab = HTTPEnv("LAB_", environ={"LAB_SYSHTTP_PROXY": "http://lab:8080"})
proxy.proxy_map(env=corp), proxy.proxy_map(env=lab)
```

A CGI program receives every request header as an `HTTP_*` variable, so a
client could set `HTTP_PROXY` or `HTTP_PROXY_AUTH`: under CGI, set a prefix
list without the empty entry.

## Hosts that share cookies

A response may set or delete cookies only for its own host and that host's
parent domains (RFC 6265). When two names reach one service, declare them a
group:

```sh
SYSHTTP_COOKIE_HOSTS="app.example.com,app.example.net;localhost,127.0.0.1"
```

or `HTTPClient(cookie_hosts=[["app.example.com", "app.example.net"]])`.
In a group, a cookie a member sets for itself or for another member belongs
to the first host, every member's requests carry the group's cookies, and
any member can delete them. A `Domain` outside the group is still judged on
the host that sent it.

## Prefix gateways

```sh
SYSHTTP_PROXY=https://gw.example SYSHTTP_PROXY_TYPE=prefix:/fetch/
```

With these set, `GET https://api.example.com/x` is sent to
`https://gw.example/fetch/https://api.example.com/x`, with the credential as a
header of that request. Redirects, cookies and `response.url` still use the
caller's URL. `syshttp.client`, requests, httpx and urllib follow a gateway;
aiohttp is not offered one (proxylib's `UnsupportedProxyError`). `syshttp.client`
does not send an `https:` origin through a plain `prefix+http` gateway, whose
hop would carry that origin's tokens and Secure cookies in clear text: use an
`https` gateway.

## Negotiate and NTLM

A server that answers `401` with `WWW-Authenticate: Negotiate` or `NTLM`, and a
proxy that answers `407` with `Proxy-Authenticate` (to a `CONNECT` as well), is
answered by `syshttp.client` only for the hosts the settings name, and only
with the `negotiate` extra installed:

```sh
pip install "syshttp[negotiate]"
SYSHTTP_NEGOTIATE="wiki.corp.example,*.apps.corp.example"
SYSHTTP_PROXY_NEGOTIATE="proxy.corp.example"
```

A pattern is a host name, `*.suffix` for every host below a domain (not the
domain itself), or `*`. With neither variable set the library never sends a
token and a `401` or `407` is the reply, as for any other client.

- **Whose identity.** With no `SYSHTTP_NEGOTIATE_USER` and
  `SYSHTTP_NEGOTIATE_PASSWORD`, the logon session on Windows (SSPI) and the
  Kerberos credential cache on Linux and macOS (the `kerberos` extra adds
  `gssapi`; without it pyspnego's own NTLM needs the explicit identity). With
  them, that one identity for every host the lists name. A password is a secret:
  it appears in no `repr()`, log line or message, and belongs in the
  environment or a secret store, never on a command line.
- **The exchange.** Each leg is the same request again with a token, on the
  connection the challenge came on and with `Connection: keep-alive`, since
  NTLM binds the identity to the connection. The request is not answered when
  it names an `Authorization` (a `Proxy-Authorization` for a proxy), when the
  proxy has a credential of its own, when its body cannot be sent twice, and for
  a prefix gateway. The server's closing token is checked where the mechanism
  has one (Kerberos); NTLM has none.
- **Plain http.** A token crossing plain http is not tried for a host that is
  not loopback, and the request fails with `NegotiationError` naming
  `SYSHTTP_NEGOTIATE_PLAIN_HTTP`. Setting it to `1` allows it, and each such
  host is logged once as `weakened` under the `syshttp.client` logger. An
  `https:` server is judged by its own scheme; a proxy by the proxy URL's.
- **Limits and failures.** `SYSHTTP_NEGOTIATE_MAX_LEGS` bounds the
  authenticated requests of one handshake (NTLM takes two) and
  `SYSHTTP_NEGOTIATE_MAX_TOKEN` a token in either direction. Refused
  credentials, a token that is not valid, a closed connection, a limit and a
  failure of the library raise `NegotiationError`, once: nothing is sent again.
  The extra missing raises `NegotiateUnavailableError`, which is also an
  `ImportError`, only for a host the settings name.

In code, `HTTPClient(negotiate=Negotiate(...))` (or `HTTPTransport(negotiate=...)`)
takes the same settings as arguments, which win over the variables; the
[`syshttp.negotiate` reference](api/negotiate.md) lists them.

## The default transport

An `HTTPClient` (and so `fetch()`) built without a `transport=` sends through
syshttp's own, on `http.client`. `SYSHTTP_DEFAULT_TRANSPORT` names another:

```sh
SYSHTTP_DEFAULT_TRANSPORT=mypackage.transport:HttpxTransport
SYSHTTP_DEFAULT_TRANSPORT=/opt/tools/transport.py:make_transport
```

The value is an object reference, `module:attr` or `<file>.py:attr` (a dotted
`attr` is allowed), resolved as a `_PY` hook is. The object is the transport
when it has `send()`; a class or a factory is called with no arguments to make
one, which the client then closes. A value that cannot be imported, called or
used raises `ConfigurationError` naming the variable; nothing falls back
silently. An explicit `transport=` beats the setting, and the setting beats
syshttp's own. It is read when the client is made, under the prefixes like every
setting. The transport protocol is in the [client reference](api/client.md).

It names code to import: never let an untrusted party set the environment of a
process using syshttp.
