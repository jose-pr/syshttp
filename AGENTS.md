# syshttp — contributor orientation

| Shipped header | Covers |
| --- | --- |
| [`src/syshttp/AGENTS.md`](src/syshttp/AGENTS.md) | the whole public API, its settings and gotchas |

## Layout

- `src/syshttp/` — the package. `negotiate.py` is the Negotiate and NTLM policy and the
  only module that imports pyspnego (inside a function, so a bare install loads it
  never). `env.py` is the only module that knows how a
  setting's name is built; every other module asks an `HTTPEnv`.
- `src/syshttp/client/` — the HTTP client on the standard library: `_client`
  (`HTTPClient`), `_transport` (the default transport and the `Transport`
  protocol), `_route` / `_context` / `_tlstunnel` (proxy map, TLS choice, TLS
  inside an https proxy), `_state` (cookies, tokens), `_default` (the
  `SYSHTTP_DEFAULT_TRANSPORT` setting), `_fetch`, `_handshake` (the legs of a Negotiate or
  NTLM exchange; `_transport` sends them on the challenged connection); the rest (`_follow`, `_pool`,
  `_headers`, `_body`, `_response`, `_status`, `_deadline`, `_prepare`) follows
  the design of `pathapi.http`.
- `tests/` — pytest. `conftest.py` clears every `SYSHTTP_*` variable per test.
  `client_wire.py` (byte-level loopback servers, a proxy, and `Handshake`: the server half
  of a Negotiate or NTLM exchange on pyspnego's acceptor, for `test_negotiate_auth.py`) and
  `client_fakes.py` (a fake transport) serve the client and transport tests;
  `test_proxy_auth.py` and `test_jars_proxy.py` hold fake proxies, gateways
  and origins on 127.0.0.1 that other test modules import.
- `docs/` + `mkdocs.yml` — the docs site (MkDocs Material, mkdocstrings).

## Environment

Python 3.9 or later. One venv per interpreter, under
`.pyvenv/<version>-<os>-<arch>/` (`dotagents pyvenv`, `dotagents pyvenv 3.9`).
The 3.9 venv needs `pip install --upgrade pip` before an editable install
(pip 21.2 lacks PEP 660).

```bash
.pyvenv/<tag>/Scripts/python -m pip install -e ".[dev,docs]"
```

## Checks

```bash
.pyvenv/<tag>/Scripts/python -m pytest -q        # warnings are errors
.pyvenv/<tag>/Scripts/python -m black --check src tests
.pyvenv/<tag>/Scripts/mkdocs build --strict
```

`tests/test_switches.py` runs mypy over `src/syshttp` when mypy is installed.

## Conventions

- A setting is read through `HTTPEnv` at call time, never at import.
  Messages name the variable found (`env.find(...)`), else `env.name(...)`.
- Only `autopatch` names `requests` or `urllib3`; the client, hooks and jars
  never import them (`test_switches.py` enforces it, and runs `fetch()` with
  both blocked from import).
- Black, line length 120, target py39.

## Releasing

See `README.md` → Releasing. Bump `version` in `pyproject.toml` in the same
commit as the `CHANGELOG.md` entry.
