<!--
SPDX-FileCopyrightText: 2025 Tom Haynes <loghyr@gmail.com>
SPDX-License-Identifier: Apache-2.0
-->

# reply — Claude Code Project Instructions

Coding standards and Python conventions:

@.claude/standards.md

Role definitions (planner, programmer, reviewer):

@.claude/roles.md

Use the `review` subagent after making code changes to enforce style and
check for standards violations before committing.

## Architecture

- `xdr_parser.py` — Standalone XDR parser and code generator (RFC 4506/5531)
- `rpc/` — ONC RPC client/server package (RFC 1831, RFC 2203)
  - `rpc.py` — Client, Server, ConnectionHandler, Pipe, record marking
  - `rpclib.py` — NULL_CRED, flow-control exceptions
  - `rpc_security.py` — AUTH_NONE, AUTH_SYS, RPCSEC_GSS
  - `rpc_const.py`, `rpc_type.py`, `rpc_pack.py` — generated from `rpc.x`
  - `gss_const.py`, `gss_type.py`, `gss_pack.py` — generated from `gss.x`
- `rpc.x`, `gss.x` — XDR definitions (RFC-derived, BSD-3-Clause)
- `*.x` test files — synthetic and real-world XDR for parser testing

## Generated code

The `rpc/*_const.py`, `rpc/*_type.py`, `rpc/*_pack.py` files are generated
by `xdr_parser.py` from `rpc.x` and `gss.x`. Regenerate with:

```bash
./xdr_parser.py --lang python --output-dir rpc rpc.x
./xdr_parser.py --lang python --output-dir rpc gss.x
```

## License rules

- All original code: Apache-2.0
- RFC-derived `.x` files: BSD-3-Clause (preserved from source)
- SPDX headers required on all files
- Never add `Co-Authored-By:` lines in the reffs project — but they
  ARE used in this repo

## Git conventions

- Always sign off: `git commit -s`
- Co-Authored-By lines are permitted in this repo
- One concern per commit
- Run `/review` before committing

## Testing

```bash
make test          # Parse all .x files
make test-python   # Generate Python code
make test-c        # Generate C code
```
