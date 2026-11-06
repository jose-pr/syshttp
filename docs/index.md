# syshttp

**HTTP plumbing that behaves the same in every client you build on it.**
`syshttp` decides which proxy to use, with which credential and for which
hosts. It speaks to URL-prefix gateways, files cookies and tokens under the
origin's host, and has the operating system verify certificates. With no
proxy variable set it routes the way the system does (its proxy settings, PAC,
WPAD). Its own HTTP client, on the standard library alone, applies all of them;
`requests` is needed by no feature, and only `syshttp.autopatch` patches it.

```python
from syshttp import fetch

response = fetch("https://example.com/", cookies=True, tokens=True)
print(response.status, response.headers["Content-Type"])
```

- [Settings](settings.md): the variables, their prefix, `HTTPEnv`, and Negotiate and NTLM.
- API reference: one page per module, in the navigation.
- [Changelog](changelog.md).

Source: <https://github.com/jose-pr/syshttp>.
