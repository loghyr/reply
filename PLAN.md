<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Plan: reply — XDR/RPC toolkit for Python

## What this is

A standalone Python package providing:
- `xdr_parser.py` — XDR parser and code generator (RFC 4506/5531)
- `rpc/` — ONC RPC client/server library (RFC 1831, RFC 2203)

Designed as a drop-in replacement for pynfs, with no GPL dependencies.
Licensed AGPL-3.0-or-later.

## Repo packaging TODO

### Files to create
- `LICENSE` — AGPL-3.0-or-later full text
- `README.md` — project overview, install, usage
- `pyproject.toml` — Python packaging (PEP 621)
- `CLAUDE.md` — Claude Code project instructions
- `.claude/roles.md` — planner/programmer/reviewer roles
- `.claude/standards.md` — Python coding standards
- `.claude/commands/review.md` — review slash command
- `.claude/agents/review.md` — review agent

### Git history
- Squash first two commits ("Frame the issue" + "Add xdr_parser.py")
- Keep co-author tags

### Python standards to enforce
- Python 3.6+ (xdrlib3 or xdrlib fallback)
- PEP 8 style (4-space indent, 79-col lines)
- Type hints where practical (not required for generated code)
- SPDX headers on all files
- No GPL dependencies

### Package structure
```
reply/
├── LICENSE
├── README.md
├── CLAUDE.md
├── pyproject.toml
├── .gitignore
├── .claude/
│   ├── roles.md
│   ├── standards.md
│   ├── commands/
│   │   └── review.md
│   └── agents/
│       └── review.md
├── xdr_parser.py
├── rpc/
│   ├── __init__.py
│   ├── rpc.py
│   ├── rpclib.py
│   ├── rpc_security.py
│   ├── rpc_const.py (generated)
│   ├── rpc_type.py (generated)
│   ├── rpc_pack.py (generated)
│   ├── gss_const.py (generated)
│   ├── gss_type.py (generated)
│   └── gss_pack.py (generated)
├── rpc.x
├── gss.x
├── tests/
│   ├── simplest.x ... edge_cases.x
│   └── (real-world .x files)
├── Makefile
├── test_xdr_parser.sh
└── test_matrix.sh
```
