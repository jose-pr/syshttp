# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.1] - 2026-11-07

### Added

- `syshttp.negotiate`: Negotiate (SPNEGO) and NTLM authentication for the
  default transport, so `HTTPClient`, `fetch()` and `HTTPTransport` answer a
  `401` with `WWW-Authenticate: Negotiate` or `NTLM` and a `407` with
  `Proxy-Authenticate` (a `CONNECT` the proxy challenges included), leg after
  leg on the connection the challenge came on, with `Connection: keep-alive`.
  It is off until `SYSHTTP_NEGOTIATE` (servers) or `SYSHTTP_PROXY_NEGOTIATE`
  (proxies) names a host (`*.suffix` and `*` allowed), or `Negotiate(hosts,
  proxies, *, username, password, plain_http, max_legs, max_token, env)` is
  passed as `negotiate=` to `HTTPClient` or `HTTPTransport`. The identity is the
  Windows logon session (SSPI) or the Kerberos credential cache, or
  `SYSHTTP_NEGOTIATE_USER` and `SYSHTTP_NEGOTIATE_PASSWORD`; a password is in no
  `repr()`, log line or message. A token is not sent over plain http to a host
  that is not loopback unless `SYSHTTP_NEGOTIATE_PLAIN_HTTP` allows it, which
  is logged as a weakening; `SYSHTTP_NEGOTIATE_MAX_LEGS` (default 5) and
  `SYSHTTP_NEGOTIATE_MAX_TOKEN` (default 65536) bound a handshake. A server's
  closing token is checked where the mechanism has mutual authentication. Skipped
  for a request that names its own `Authorization`, a proxy with a credential of
  its own, a body that cannot be sent twice and a gateway.
- The extras `negotiate` (pyspnego: SSPI on Windows, NTLM in Python) and
  `kerberos` (pyspnego with `gssapi`, for the credential cache on Linux and
  macOS). `import syshttp` and a default install load and need neither.
- `NegotiationError` (a handshake that failed: credentials refused, a token that
  is not valid or too large, a connection closed or more legs than allowed, a
  handshake that would cross plain http) and `NegotiateUnavailableError` (also an
  `ImportError`: the extra is missing or does not import), both under
  `SysHTTPError` and exported from the root; `has_negotiate()` says whether the
  library imports.

## [0.1.0] - 2026-10-20

### Added

- `syshttp.client`: an HTTP client on the standard library, so that no feature
  of syshttp needs `requests` (which only `syshttp.autopatch` patches, in a
  program that imports it). `HTTPClient(transport=None, *, headers, timeout,
  deadline, user_agent, env, proxymap, ssl_context, proxy_ssl_context, verify,
  cookies, tokens, auth_provider, retries, backoff, status_forcelist,
  cookie_hosts)` sends through a transport and follows redirects with one rule
  for credentials (`Authorization`, `Cookie` and `Proxy-Authorization` go to the
  origin they were given for and to no other scheme, host or port). The default `HTTPTransport` (on `http.client`,
  with a per-thread connection pool, framed bodies, `gzip` / `deflate`
  decoding and a bounded reply size) routes every request and redirect hop by
  `proxy.proxy_map(env=env)` (or `proxymap=`): the first entry that accepts a
  connection, an `http` or `https` proxy (`CONNECT`; an `https` proxy over TLS
  with the origin's TLS inside it), a URL-prefix gateway, a proxy's
  credential to the proxy alone; and verifies with the caller's `ssl_context`,
  else the `CA_BUNDLE` bundle or `verify=<path>`, else the system's context
  (`proxy_ssl_context` for an `https` proxy or gateway). Cookies (RFC 6265,
  per origin, on every hop, in a jar by host with `cookies=`), tokens, `_PY`
  hooks, `auth_provider` and retries (`Retry-After` honoured, a status that
  outlasts them returned) work as they did on the session. `HTTPResponse`
  reads its body whole as `content`, `text()` and `json()`.
- `syshttp.fetch()` (defined in `syshttp.client`, re-exported from the root
  without importing it): `fetch(url, method="GET", *, headers, data, json,
  timeout, client, transport, reauth, **client_options)` returns the
  `HTTPResponse` with its body read, whatever the status; a given `client` is
  left open and a new one is closed; `reauth` runs once after a 401 or 403.
- The transport protocol is public: `Transport` (`send()` and `close()`),
  `PreparedRequest` and `prepare_request()` give another transport (on
  `requests`, `httpx`, or a fake) the checks and body framing of syshttp's own.
  `SYSHTTP_DEFAULT_TRANSPORT` (`module:attr` or `<file>.py:attr`, read under the
  prefixes) names the transport of a client given none; a value that cannot be
  used is `ConfigurationError`. `hooks.load_object()` is the loader it shares
  with the `_PY` hooks.
- `syshttp.exceptions`: `SysHTTPError` (the base of what goes wrong at run
  time), `ConfigurationError` (a `ValueError`), `HookError` (a `RuntimeError`)
  and `ResponseError` (a `ValueError`), exported from the root. A malformed
  setting, a hook that cannot be loaded, a failing hook and a body that is not
  JSON raise them; every one is still the `ValueError` or `RuntimeError` it
  was, so existing handlers keep working. A caller's own mistake stays a plain
  `ValueError` / `TypeError`.
- Every public module declares `__all__` (`proxy` also lists its setting-name
  constants, `PROXY` and `DEFAULT_AUTH_HEADER` among them).
- `syshttp.env.HTTPEnv(prefixes=None, environ=None)`: every setting is a
  variable with a full name -- syshttp's own carry `SYSHTTP_`
  (`SYSHTTP_PROXY`, `SYSHTTP_HOME`, `SYSHTTP_HOOKS_<KEY>`,
  `SYSHTTP_IMPORTPATCH`), conventional ones keep theirs (`HTTPS_PROXY`,
  `NO_PROXY`, `HTTP_PROXY_AUTH`, `CA_BUNDLE`) -- read as `<PREFIX><NAME>` for
  each prefix of `SYSHTTP_PREFIX` in turn, a `:`-separated list used
  literally (default: one empty prefix, the names as written). The first
  prefix that sets a variable wins, each variable on its own:
  `SYSHTTP_PREFIX=MYTOOL_` reads only `MYTOOL_<NAME>`, `MYTOOL_:` falls back
  to the unprefixed names. `find()` returns the variable found with its
  value, for messages. Every function that reads a setting takes `env=`,
  `new_session()` and the `fetch` `*_auto` helpers included.
- `CA_BUNDLE` (under the prefixes) names the CA bundle a session's
  `verify=True` uses; sessions no longer read requests' own
  `REQUESTS_CA_BUNDLE` / `CURL_CA_BUNDLE`.
- The system's proxy configuration is the last proxy source, decided for the
  URL being requested: WinHTTP on Windows, CFNetwork on macOS, libproxy or the
  desktop's settings elsewhere, PAC scripts and WPAD included (through
  proxylib, a new dependency). It comes after `SYSHTTP_PROXY` and the
  `*_PROXY` variables, after the `NO_PROXY` check, and is always spoken to as
  `connect`. `SYSHTTP_SYSTEM_PROXY=0` turns it off. `proxy.plan()`,
  `proxy_url()`, `resolve()` and `proxy_authorization()` take the request URL
  (`url=` / `target=`). `proxy.configured_proxy_url()` gives the
  environment's answer alone. The `pac` extra adds a JavaScript engine for PAC
  scripts proxylib evaluates itself (Linux without libproxy).
- `syshttp.autopatch`: `SYSHTTP_IMPORTPATCH=1` (or `:`-separated names:
  `requests`, `urllib`, `httpx`, `aiohttp`; read under the prefixes like
  every setting) patches those libraries as they are imported,
  in any program of the environment, so requests without a proxy or TLS
  setting of the caller's route by syshttp and verify with the system's
  context. Through importpatch, a new dependency, and its entry points;
  `patch()` / `unpatch()` do it from code.
- The system's answer is a list (`PROXY a; PROXY b; DIRECT`): the first proxy
  that accepts a connection is used (proxylib's `first_working_proxy`), and a
  DIRECT reached first is direct. No reachable proxy and no DIRECT raises
  `proxy.NoReachableProxyError` (a `ConnectionError`, exported from the
  root); a session raises `requests.exceptions.ProxyError` for it.
- `new_session(ssl_context=..., proxy_ssl_context=...)` (and the same on the
  `fetch` `*_auto` helpers): a caller's `ssl.SSLContext` is used as given for
  every https origin, or for an `https://` proxy. That covers mutual TLS,
  ciphers and protocol versions. It cannot be combined with a `verify` other
  than `True`.
- `hooks.wrapper_environment()`: the `SYSHTTP_HOOK_*` variables a `_CURL`
  wrapper run receives.
- `jar.default_root()`: the per-user state directory used when
  `SYSHTTP_HOME` is unset.
- `syshttp.__version__`.
- Hosts that share cookies: `SYSHTTP_COOKIE_HOSTS` (hosts split by `,`,
  groups by `;`) or `new_session(cookie_hosts=...)` declares names that reach
  one service. In a group, a cookie a member sets for itself or another
  member belongs to the first host, every member's requests carry the
  group's cookies, and any member can delete them; a `Domain` outside the
  group is still judged on the host that sent it. `cookies.host_aliases()`
  builds the mapping, which `set_cookie_specs`, `merge_set_cookie_headers`
  and `host_only_policy` take as `aliases=`.
- The shipped header and the settings page list every variable syshttp
  reads under its own name (the proxy family, `REQUEST_METHOD`, the CA bundle
  variables, the state-directory variables, importpatch's and proxylib's).

### Changed

- `syshttp.fetch` is a function, not a module: `fetch()` replaces the helpers
  below. `_PY` hooks are called as `hook(client, method, url, kwargs)` with the
  keyword arguments of `HTTPClient.request()`, and may return an
  `HTTPResponse`; `auth.AuthProvider.ensure(client, url)` takes the client.
  `CA_BUNDLE` is the bundle a client's `verify=True` uses. `cookies.py` keeps
  the Netscape rows, `set_cookie_specs`, `cookie_applies` and `host_aliases`
  only; the client keeps its cookies as those rows.
- Routing is proxylib 2's (`proxylib>=2.0.2,<3`; 2.0.1 breaks pip's cached
  requests). `proxy.proxy_map(proxy,
  noproxy, proxy_user, *, env)` is the settings as one proxylib proxy map,
  read at each lookup; `proxy.configured_proxy()` is `SYSHTTP_PROXY` as a
  proxylib `Proxy`; `proxy.system_map()` is the system's configuration
  (`proxylib.auto_proxy`). The `*_PROXY` variables are read per scheme
  (lowercase first, httpoxy-safe), `NO_PROXY` takes CIDR entries, and curl's
  `-x ""` is direct. `SYSHTTP_PROXY_AUTH` goes to `SYSHTTP_PROXY` only and
  `HTTP_PROXY_AUTH` to the machine's proxies only.
- A list from the system (`PROXY a; PROXY b; DIRECT`) is tried in order by the
  session, httpx and aiohttp (proxylib's failover), replacing the probe of
  the entry above; urllib takes the first reachable entry. No proxy
  connecting and no DIRECT is the client's own connection error;
  `NoReachableProxyError` is proxylib's.
- The session's `ProxyAdapter` is proxylib's `ProxyMapAdapter` with the
  system's TLS; `adapter.route(url)` returns the entries it will try.
  `proxies=` given to `new_session` are requests' own, with no syshttp
  credential added.
- `syshttp.autopatch` routes through `proxylib.patch()` and patches TLS only;
  requests' TLS is a pool hook on every `HTTPAdapter`. A caller's own
  proxies and `trust_env = False` still win over syshttp (proxylib 2.0.2's
  rule). aiohttp is not offered
  URL-prefix gateways. New target `pip` (`pip._vendor.requests`, proxylib
  2.0.1's `pip` target): pip's adapters route through the map unless pip is
  given `--proxy` or `--no-proxy-env`; pip keeps its own TLS context.

- The jar constructors (`FileCookieJar`, `FileTokenJar`) no longer create
  their directory; it is created at the first write.

- A session returns the last response when a status in `status_forcelist`
  outlasts its retries, as plain requests does; it used to raise
  `requests.exceptions.RetryError`, which the fetch helpers (`-> (status,
  text)`) passed on. The `*_auto` helpers take `new_session`'s options as
  `**session_options` (every keyword they had still works) and their
  `timeout` may be a `(connect, read)` pair.
- Every dependency's floor is its newest release that supports Python 3.9:
  the `session` extra requires `requests>=2.32.5` and `urllib3>=2.6.3` (was
  `requests>=2.25`), and `sslcontext>=2.1.0`. Below requests 2.32.3 a caller's
  `ssl_context` was silently ignored, urllib3 1.26 raises a bare `ValueError`
  for an https IP-literal host, and urllib3 up to 2.2 leaks the socket of a
  failed TLS handshake through an https proxy. On Python 3.9, botocore pins `urllib3<1.27`, so `syshttp[session]`
  cannot share an environment with it there.


- The header says that jars, tokens, `_PY` hooks and `auth_provider` apply to
  `session.request` and not to a bare `session.send()`, which gets the proxy
  decision and TLS only.

- `new_session()` no longer calls `urllib3.disable_warnings`, which silenced
  `InsecureRequestWarning` for the whole process; with `verify=False` urllib3
  warns as it does for any requests session. The undocumented
  `syshttp.warnings` module is gone.

### Removed

- `syshttp.session` (`new_session()` and its `requests` adapter), the
  `session` extra (and its `requests` and `urllib3` floors; `requests` stays a
  development dependency for the tests of `syshttp.autopatch`), and the helpers
  of the old `syshttp.fetch` module: `request_text`, `request_json`,
  `request_with_reauth`, `request_text_auto` and `request_json_auto`. Their
  replacements are `HTTPClient` and `fetch()`. A per-request `verify=` and
  `cert=` are gone with them: build a client with `verify=` or an
  `ssl_context` that holds the identity. `cookies.apply_to_session`,
  `merge_set_cookie_headers` and `host_only_policy`, which only a `requests`
  session used, are gone too.
- `proxy.proxy_url`, `configured_proxy_url`, `system_proxy`,
  `system_proxy_map`, `first_reachable`, `PROBE_MAX_AGE`, `PROBE_TIMEOUT`,
  `resolve`, `proxy_authorization`, `configured_authorization`, `userinfo`,
  `basic_authorization`, `strip_auth`, `redact`, `prefix_url`,
  `should_bypass`, `bypassed_by`, `no_proxy_from_env`, `proxies_from_env`,
  `plan` and `ProxyPlan`: `proxy_map()` and proxylib's `Proxy` replace them.

### Changed (earlier)

- The package stands alone as `syshttp`. It was previously the `httplib`
  library of the dotagents `net` overlay, which shipped with a curl-compatible
  command (`httplib.cli`, `python -m httplib`) that is now the `curlike`
  package. Imports move from `httplib` to `syshttp`, and settings from the
  dotagents names to the prefixed ones: `AGENTS_PROXY` → `SYSHTTP_PROXY`,
  `AGENTS_PROXY_AUTH` → `SYSHTTP_PROXY_AUTH`, `AGENTS_PROXY_AUTH_HEADER` →
  `SYSHTTP_PROXY_AUTH_HEADER`, `AGENTS_PROXY_TYPE` → `SYSHTTP_PROXY_TYPE`,
  `AGENTS_HOME` → `SYSHTTP_HOME`, `NET_HOOKS_<KEY>` → `SYSHTTP_HOOKS_<KEY>`,
  `NET_HOOK_*` → `SYSHTTP_HOOK_*`. A tool's own namespace is a prefix:
  `SYSHTTP_PREFIX=AGENTS_` reads `AGENTS_SYSHTTP_PROXY`,
  `AGENTS_SYSHTTP_HOOKS_<KEY>` and so on.
- The system's TLS client by default: `tls.new_os_context()` (and so
  `os_ssl_context()` and every session with `verify=True`) returns
  `sslcontext.system_context()` (sslcontext 2 is a new dependency).
  Certificates are verified by the operating system on Python 3.10+
  (CryptoAPI on Windows, the Security framework on macOS, OpenSSL over the
  system store elsewhere), by OpenSSL over the default store on 3.9, and a
  server that asks for a client certificate gets one from the OS store,
  chosen as a browser chooses. `new_os_context(client_certificates=False)`
  offers none, for a caller loading its own. A `cafile` / `capath` still
  replaces the store with a plain `ssl` context.
- A session without caller `proxies` decides the proxy for every request and
  every redirect hop, from the environment as it is then and the system's
  answer for that URL. A direct decision is final: requests' `trust_env` cannot
  re-add a proxy. `adapter.route(url)` shows the decision.
- Without `SYSHTTP_HOME`, the jars live in the per-user state directory
  instead of the dotagents store directory.
- `proxy.resolve()` and `proxy.proxy_authorization()`: the keyword `env: bool`
  is now `configured: bool`.
- `hooks.hooks_from_env()`, `matching()`, `skipped()` and `call_py_hooks()`
  take `env: HTTPEnv` (keyword-only) instead of a mapping `environ`.
  `hooks.PREFIX`, `SKIP_ENV`, `URL_ENV`, `KEY_ENV` and `CURL_ENV` are
  replaced by the setting names `HOOKS`, `HOOK_SKIP`, `HOOK_URL`, `HOOK_KEY`
  and `HOOK_CURL`.
- `proxy.AUTH_VARS`, `AUTH_HEADER_VAR` and `TYPE_VAR` are replaced by the
  setting names `PROXY_AUTH`, `PROXY_AUTH_HEADER` and `PROXY_TYPE`.

### Fixed

- A by-host cookie file keeps a cookie its host set for a parent domain
  (`Domain=example.com` from `www.example.com`); it was never saved.
- The proxy credential reaches a proxy whose host is configured in upper
  case. requests lower-cases the proxy URL it hands to `proxy_headers`, so the
  credential used to be dropped and the proxy answered 407.
- `Set-Cookie` is read as RFC 6265 section 5.2 reads it, not through
  `http.cookies.SimpleCookie`: a value with a space or JSON is kept, an
  unknown attribute (`Priority`, `Partitioned`) is no longer a cookie of its
  own, `Max-Age` beats `Expires`, and a header with no `name=value` is
  skipped. A `Domain` without a leading dot covers subdomains. A cookie with
  no `Path` gets the directory of the request path
  (`set_cookie_specs(..., request_path=)`).
- A session holds one copy of each cookie. `merge_set_cookie_headers` no
  longer re-sets what requests already stored (it used to add a second copy
  with path `/` and a dotless domain); it applies only the deletions requests
  misses, for redirect hops too.
- A cookie set without `Domain` stays on its host: rows loaded from a jar and
  cookies a server sets are no longer sent to subdomains
  (`new_session` uses `cookies.host_only_policy()`).
- A cookie for a single-label host (`localhost`, `wiki`) is loaded from its
  jar file, and is saved under its own name instead of `localhost.local`.
- `FileCookieJar` keeps `HttpOnly` and the include-subdomains flag.
- `load_netscape` keeps a row whose value is empty, and an expiry written
  with a non-ASCII digit is a session cookie instead of a `ValueError`.
  `retry_after` returns `None` for such a value, and reads an HTTP date
  written without a zone (`asctime`) as UTC.
- A cookie expiry beyond 400 days is cut to 400 days.
- A hook whose `_PY` / `_CURL` target is blank is ignored instead of failing
  every request, and `HTTPEnv.family` strips values as `get` does.
- Hook KEYs are compared without regard to case: `HOOK_SKIP=mykey` did not
  suppress `MYKEY`, the form Windows holds. `Hook.key` and `skipped()` are
  upper-case.
- A `<file>.py:callable` hook's module is loaded once per process, not on
  every request (its module-level state was reset each time), and two files
  with one name no longer share a module name.
- `request_text_auto` and `request_json_auto` retry a 408 by default, as
  `new_session` does (their own list had dropped it), and close the session
  they built instead of leaking its connection pool. The five fetch helpers
  have docstrings.
- `new_session(user_agent=...)` sets the User-Agent; the default
  `python-requests/x` was sent whatever was given.
- The guards that keep a hook or `auth_provider.ensure` from running again for
  its own requests are per thread: while one thread was inside a hook, the
  other threads' requests skipped hooks and `ensure`.
- A request-level `verify=` (`False`, or a bundle) beside `ssl_context`, which
  was silently ignored, raises `ValueError` as the same value does at session
  level. `CA_BUNDLE` is not a request-level value, and a session with an
  `ssl_context` does not consult it.
- The import patch replaces requests 2.32.3's own default context (a certifi
  bundle) in a pool, as it does for the later versions that leave it out.
- Token and cookie files are replaced whole by a rename, so a reader never sees
  an empty or half-written file and concurrent savers no longer truncate each
  other's file.
- `SYSHTTP_HOME=~/jars` is expanded instead of creating a directory named `~`.
- Jar files are written with LF on Windows too, as curl writes them.
- A session whose cookie jar cannot be read (an error while iterating
  `session.cookies`) no longer saves an empty list over the host's cookies, and
  writes a host's file only when its cookies changed instead of after every
  response.

### Security

- The client closes six gaps found in review. A `Set-Cookie` with a control
  character in it is ignored whole (RFC 6265bis 5.6), `load_netscape` ends a
  line at a newline only (it ended one at `\x0b`, `\x0c`, `\x1c`-`\x1e` and
  `\x85` too, so a value could become a whole row for another domain),
  `save_netscape` writes no row with a control character or a tab in a field,
  and a by-host jar file gives the client only the rows that cover its host or
  group. A plain-http response can no longer set a Secure cookie, or set,
  replace or delete one that is stored (RFC 6265bis 5.7; the loopback hosts
  count as secure, as in curl). A redirect to another scheme, host or port
  drops a caller's `Cookie` and `Proxy-Authorization` header with
  `Authorization`. `HTTPTransport.send(stream=False)` and
  `HTTPResponse.buffered()` hold a decoded reply to `MAX_REPLY_BYTES` (a
  kilobyte of gzip decoded to tens of megabytes), and the too-large error names
  the URL as scheme, host, port and path, without its query. An `https:` origin
  is no longer sent through a plain `prefix+http` gateway, which would carry its
  tokens and Secure cookies in clear text: the entry is skipped, and with
  nothing else left the request raises `proxylib.UnsupportedProxyError`.
- A `Set-Cookie` can no longer name a domain its host does not own. Any
  host could set or delete another host's cookie (`Domain=bank.example` from
  `evil.example`) or one for a top level domain; such a header is now skipped
  on a set and on a deletion, in the session, in `FileCookieJar` and in
  `set_cookie_specs` (which curlike's `-c` uses). A public suffix is
  recognised without the Public Suffix List (a name with no dot, or a
  `co.uk`-style registry).
- Token and cookie files are created `0600`, and the directories this library
  creates `0700`, instead of world-readable under a usual umask.
- A client certificate passed as `cert=` is no longer loaded into the shared OS
  context (or into the caller's `ssl_context`), where every later session, and
  every other user of that context, presented it too. It gets a context of the
  session's own; `cert=` beside `ssl_context` raises `ValueError`.
- A URL-prefix gateway is spoken to with `proxy_ssl_context` (or the system's
  verifier), no longer with the `ssl_context` and client certificate meant for
  the origin.
- A token, or a proxy credential, containing CR, LF or NUL raises a
  `ValueError` that names the jar key or variable instead of requests'
  `InvalidHeader` carrying the whole secret.
- No setting can be chosen by a CGI client unless the program reads the
  unprefixed names: syshttp's own all start `SYSHTTP_`, which a request
  header never becomes, and a CGI program sets a prefix list without the
  empty entry so that `HTTP_PROXY` and `HTTP_PROXY_AUTH` are not read.
- A failing hook's message names its URL as scheme, host, port and path, no
  longer with the userinfo, query and fragment (`user:pass@`,
  `?access_token=`).

[Unreleased]: https://github.com/jose-pr/syshttp/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/jose-pr/syshttp/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/jose-pr/syshttp/releases/tag/v0.1.0
