# syshttp

[![Version](https://img.shields.io/pypi/v/syshttp.svg)](https://pypi.org/project/syshttp/)
[![Python versions](https://img.shields.io/pypi/pyversions/syshttp.svg)](https://pypi.org/project/syshttp/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/jose-pr/syshttp/blob/main/LICENSE)
[![Docs](https://img.shields.io/badge/docs-latest-blue.svg)](https://jose-pr.github.io/syshttp/)
[![CI](https://img.shields.io/github/actions/workflow/status/jose-pr/syshttp/test.yml)](https://github.com/jose-pr/syshttp/actions/workflows/test.yml)

**HTTP plumbing that behaves the same in every client you build on it**:
which proxy to use, with which credential, for which hosts; how a prefix
gateway is spoken to; which cookies and tokens go with which origin; and TLS
through the operating system's own certificate verifier. By default it
routes the way the system does: the system's proxy configuration, PAC scripts
and WPAD included, unless a proxy variable says otherwise. An HTTP client on the
standard library puts all of them together; `requests` is needed by none of
it. Documentation: <https://jose-pr.github.io/syshttp/>.

## Features

- **Routing is [proxylib](https://pypi.org/project/proxylib/)'s** —
  `proxy.proxy_map()` turns the settings below into one proxylib proxy map,
  and proxylib's client integrations send through it.
- **The system's proxy, by default** — with no proxy variable set, the
  system's configuration decides per URL: WinHTTP on Windows, CFNetwork on
  macOS, libproxy or the desktop's settings elsewhere, PAC and WPAD included.
  A list (`PROXY a; PROXY b; DIRECT`) is tried in order, the next entry when
  one does not connect; with no proxy connecting and no DIRECT the request
  fails rather than going direct.
- **Proxies with credentials** — a proxy URL from `SYSHTTP_PROXY`, else the
  usual `HTTPS_PROXY` / `HTTP_PROXY` / `ALL_PROXY` for the request's scheme.
  The credential is a header value sent verbatim to that proxy only, so any
  scheme works (`Basic`, `Bearer`, `Negotiate`). `NO_PROXY` is honoured
  (CIDR included), and every redirect hop is decided again.
- **Prefix gateways** — `SYSHTTP_PROXY_TYPE=prefix:/fetch/` sends
  `GET https://api.example.com/x` to `<proxy>/fetch/https://api.example.com/x`
  (the client, requests, httpx and urllib; the client sends an `https:` origin
  through an `https` gateway only). Responses, redirects and cookies still use
  the caller's URL.
- **Prefixes of a tool's own** — `SYSHTTP_PREFIX=MYTOOL_` makes the package
  read `MYTOOL_HTTPS_PROXY`, `MYTOOL_SYSHTTP_HOME` and so on instead of the
  defaults; `MYTOOL_:` falls back to them, variable by variable. An
  `HTTPEnv("MYTOOL_")` object keeps one configuration apart from another in
  the same process.
- **Cookie and token jars** — Netscape cookie files with curl's matching
  rules, plus per-host token files. Both are chosen by the origin's host,
  never by the proxy's or the gateway's.
- **URL hooks** — `SYSHTTP_HOOKS_<KEY>=<regex>` plus `_PY=module:callable`
  runs your code before matching requests: a login, a signature, a canned
  response.
- **The system's TLS client, or your own TLS context** — by default
  [sslcontext](https://pypi.org/project/sslcontext/)'s system context: the
  operating system verifies certificates (CryptoAPI, the Security framework),
  with no `certifi` bundle involved, and a server that asks for a client
  certificate gets one from the OS store (smart cards included), chosen as a
  browser chooses. Or `HTTPClient(ssl_context=...)` for a given identity, a
  cipher list or a pinned protocol version.
- **An HTTP client on the standard library** — `HTTPClient` and `fetch()`:
  retry with backoff, redirects that keep a credential with its origin, and
  all of the above, on `http.client` and `ssl` alone. Its transport is
  replaceable: any object with `send()` (a `requests` or `httpx` one, a fake
  in a test), chosen per client or by `SYSHTTP_DEFAULT_TRANSPORT`.
- **Negotiate and NTLM, for the servers and proxies you name** — a `401` with
  `WWW-Authenticate: Negotiate` or `NTLM`, and a `407` with `Proxy-Authenticate`
  (a `CONNECT` included), is answered leg after leg on the connection it came
  on: SSPI with the current Windows logon, Kerberos from the credential cache
  where `gssapi` is installed, NTLM with a credential you give. Off until
  `SYSHTTP_NEGOTIATE` or `SYSHTTP_PROXY_NEGOTIATE` names a host, and never over
  plain http to a host that is not loopback unless a setting says so
  (`pip install "syshttp[negotiate]"`).
- **Other programs' clients, patched on import** — `SYSHTTP_IMPORTPATCH=1`
  (or `requests:urllib:httpx:aiohttp:pip`) makes those libraries route and
  verify the same way in any program of the environment, through
  [importpatch](https://pypi.org/project/importpatch/); what a caller sets
  itself still wins.

## Installation

```bash
pip install syshttp
```

| Extra | Adds | Needed for |
| --- | --- | --- |
| `pac` | a JavaScript engine for proxylib | PAC scripts proxylib evaluates itself (Linux without libproxy) |
| `negotiate` | pyspnego | Negotiate and NTLM for a server or proxy that challenges: SSPI on Windows, NTLM in Python elsewhere |
| `kerberos` | pyspnego with `gssapi` | Kerberos from the credential cache on Linux and macOS (builds against the system's Kerberos headers when no wheel exists) |

syshttp depends on proxylib (the system proxy), sslcontext (the system's
TLS client: the OS verifier through truststore on Python 3.10+, OpenSSL over
the default store on 3.9) and importpatch (its `.pth` hooks imports at
interpreter start; nothing is patched unless `SYSHTTP_IMPORTPATCH` says so).

## Quick start

Ask where a request would go, the way every client here does:

```python
import proxylib
from syshttp import proxy

for entry in proxylib.lookup(proxy.proxy_map(), "https://api.example.com/"):
    print("DIRECT" if entry is None else entry.url)   # tried in this order
```

One request, routed and verified the way the system does (no extra to install):

```python
from syshttp import fetch

response = fetch("https://api.example.com/thing")
print(response.status, response.json())
```

A client with file-backed cookies and tokens, kept across requests:

```python
from syshttp.client import HTTPClient

with HTTPClient(cookies=True, tokens=True) as client:
    response = client.request("GET", "https://api.example.com/thing")
```

A server or proxy behind Windows-integrated authentication, answered with the
logon session (nothing is sent unless the host is named; needs
`pip install "syshttp[negotiate]"`):

```python
from syshttp.client import HTTPClient
from syshttp.negotiate import Negotiate

with HTTPClient(negotiate=Negotiate("wiki.corp.example", proxies="proxy.corp.example")) as client:
    response = client.request("GET", "https://wiki.corp.example/api/page")
```

The same from the environment, with no code change:
`SYSHTTP_NEGOTIATE=wiki.corp.example SYSHTTP_PROXY_NEGOTIATE=proxy.corp.example`.

A separate configuration, isolated from the process environment:

```python
from syshttp import HTTPEnv, fetch

env = HTTPEnv("MYTOOL_", environ={"MYTOOL_SYSHTTP_PROXY": "http://proxy.internal:3128"})
response = fetch("https://api.example.com/thing", env=env)
```

## API overview

| Module | Purpose |
| --- | --- |
| `syshttp.env` | `HTTPEnv`: the prefixes and mapping every setting is read from |
| `syshttp.proxy` | `proxy_map()`: the settings as one proxylib proxy map |
| `syshttp.client` | `HTTPClient` and `fetch()`: the HTTP client, its transport protocol and response |
| `syshttp.negotiate` | `Negotiate`: which servers and proxies get Negotiate and NTLM, and with whose credentials |
| `syshttp.jar` | file and memory cookie/token jars |
| `syshttp.cookies` | Netscape cookie files and curl's cookie rules |
| `syshttp.hooks` | URL hooks declared in the environment |
| `syshttp.tls` | the OS verifier as an `SSLContext` |
| `syshttp.autopatch` | requests, urllib, httpx, aiohttp and pip patched on import |
| `syshttp.retry` | the transient statuses, `Retry-After` |

## Settings

Every setting is read as `<PREFIX><NAME>` for each prefix of
`SYSHTTP_PREFIX` (`:`-separated; default none, the names as written). The
full list is on the docs site:
<https://jose-pr.github.io/syshttp/settings/>.

| Variable | Sets |
| --- | --- |
| `SYSHTTP_PREFIX` | the prefixes every other setting is read under |
| `SYSHTTP_PROXY` | the proxy URL; else `HTTPS_PROXY`, `HTTP_PROXY`, `ALL_PROXY`, else the system's |
| `SYSHTTP_SYSTEM_PROXY` | `0` to stop consulting the system's proxy configuration |
| `SYSHTTP_PROXY_AUTH` | the proxy credential, sent verbatim; else `HTTP_PROXY_AUTH` |
| `SYSHTTP_PROXY_AUTH_HEADER` | the header it is sent in (default `Proxy-Authorization`) |
| `SYSHTTP_PROXY_TYPE` | `connect` (default) or `prefix[:/endpoint]` |
| `SYSHTTP_NEGOTIATE` | the servers whose Negotiate or NTLM challenge is answered: host names, `*.suffix`, `*` (default: none) |
| `SYSHTTP_PROXY_NEGOTIATE` | the same for proxies, by the proxy's host |
| `SYSHTTP_NEGOTIATE_USER`, `SYSHTTP_NEGOTIATE_PASSWORD` | an explicit identity (a secret) instead of the logon session or credential cache |
| `SYSHTTP_NEGOTIATE_PLAIN_HTTP` | also authenticate over plain http to a host that is not loopback (off; logged as a weakening) |
| `SYSHTTP_NEGOTIATE_MAX_LEGS`, `SYSHTTP_NEGOTIATE_MAX_TOKEN` | the limits of one handshake (5 requests, 65536 bytes a token) |
| `SYSHTTP_HOME` | the jar directory (default: the per-user state directory) |
| `SYSHTTP_IMPORTPATCH` | `1`, or `:`-separated names: the client libraries patched on import |
| `SYSHTTP_HOOKS_<KEY>` | a URL hook's pattern, with `_PY` / `_CURL` targets |
| `SYSHTTP_DEFAULT_TRANSPORT` | `module:attr` or `<file>.py:attr`: the transport of a client given none (it names code to import) |
| `CA_BUNDLE` | the CA bundle a client verifies with (default: the OS verifier) |

## Development

```bash
dotagents pyvenv            # or any Python 3.9+ virtual environment
.pyvenv/<tag>/Scripts/python -m pip install -e ".[dev]"
.pyvenv/<tag>/Scripts/python -m pytest -q
```

### Releasing

This project follows [Semantic Versioning](https://semver.org/) and keeps a
[`CHANGELOG.md`](https://github.com/jose-pr/syshttp/blob/main/CHANGELOG.md).
Pushing a tag matching `v*` triggers the release workflow: test gate → build
(checking the tag names the version built) → a strict docs build as a gate →
GitHub release → publish. The release workflow never deploys the docs site
itself: for a final release its last job dispatches the docs workflow at the
tag, which owns every Pages deploy.

## License

MIT — see [LICENSE](https://github.com/jose-pr/syshttp/blob/main/LICENSE).
