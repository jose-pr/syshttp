"""syshttp -- HTTP plumbing that follows the system, and an HTTP client on the
standard library that uses it.

Public surface (the package's AGENTS.md documents each name):
  env.HTTPEnv                          — where settings come from: <PREFIX><NAME> for each
                                         prefix of SYSHTTP_PREFIX (default: none)
  proxy.proxy_map                      — the routing as a proxylib ProxyMap: SYSHTTP_PROXY with
                                         its credential, else the *_PROXY variables or the
                                         system's configuration, NO_PROXY first (-x / -U /
                                         --noproxy overrides included)
  proxy.configured_proxy / proxy_type  — SYSHTTP_PROXY as a proxylib Proxy; SYSHTTP_PROXY_TYPE
                                         (connect | prefix[:/endpoint])
  negotiate.Negotiate                  — Negotiate and NTLM for the servers and proxies SYSHTTP_NEGOTIATE /
                                         SYSHTTP_PROXY_NEGOTIATE name (the `negotiate` extra)
  client.HTTPClient / fetch            — the client: proxy map, system TLS, cookies, tokens,
                                         hooks, retries; replaceable transport. ``fetch`` is
                                         also ``syshttp.fetch``
  cookies.load_netscape / save_netscape / cookie_applies / set_cookie_specs
                                       — Netscape jars and curl's cookie rules
  tls.os_ssl_context / new_os_context  — the system's TLS client (sslcontext) as an SSLContext
  retry.TRANSIENT_STATUSES / retry_after — what counts as transient, Retry-After
  jar.FileCookieJar / FileTokenJar     — file-backed jars under SYSHTTP_HOME
  hooks                                — SYSHTTP_HOOKS_<KEY> URL hooks (a curl wrapper,
                                         a syshttp callable) matched on the caller's URL
  autopatch                            — SYSHTTP_IMPORTPATCH: requests, urllib, httpx, aiohttp,
                                         pip patched on import to route and verify the same way

Nothing here imports ``requests``: only ``autopatch`` patches it, in a program
that imports it. Importing ``syshttp`` itself loads neither proxylib nor the
client.
"""

from importlib.metadata import PackageNotFoundError, version
from typing import Any

from .env import HTTPEnv
from .exceptions import (
    ConfigurationError,
    HookError,
    NegotiateUnavailableError,
    NegotiationError,
    ResponseError,
    SysHTTPError,
)

__all__ = [
    "ConfigurationError",
    "HTTPEnv",
    "HookError",
    "NegotiateUnavailableError",
    "NegotiationError",
    "NoReachableProxyError",
    "ResponseError",
    "SysHTTPError",
    "configured_proxy",
    "fetch",
    "proxy_map",
    "proxy_type",
]

# Read from syshttp.proxy when first asked for: importing syshttp must not
# import proxylib, whose own import of urllib.request runs syshttp's
# import-time patch (syshttp.autopatch) while proxylib is half built.
_FROM_PROXY = ("NoReachableProxyError", "configured_proxy", "proxy_map", "proxy_type")


def __getattr__(name: str) -> Any:
    if name in _FROM_PROXY:
        from . import proxy

        return getattr(proxy, name)
    if name == "fetch":
        from .client import fetch

        return fetch
    raise AttributeError("module %r has no attribute %r" % (__name__, name))


try:
    __version__ = version("syshttp")
except PackageNotFoundError:  # a source tree on sys.path, not installed
    __version__ = "0+unknown"
