<!--
SPDX-FileCopyrightText: 2025 Tom Haynes <loghyr@gmail.com>
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Python Coding Standards

## Style

- PEP 8 with 4-space indentation
- Line length: 79 characters (code), 72 (docstrings/comments)
- Use single quotes for strings unless the string contains a single quote
- No trailing whitespace
- Files end with a single newline

## SPDX headers

Every source file must begin with:

```python
# SPDX-FileCopyrightText: YEAR Tom Haynes <loghyr@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later
```

For `.x` files use `/* */` comment style. For `.md` files use `<!-- -->`.

## Imports

- Standard library first, then third-party, then local
- One import per line for `from` imports with multiple names
- Use relative imports within the `rpc` package (`from . import rpclib`)

## Error handling

- Use specific exception types, not bare `except:`
- `except Exception:` is acceptable as a catch-all when logging
- Never silently swallow exceptions — at minimum log them

## Type hints

- Encouraged but not required
- Not used in generated code
- Use when it clarifies function signatures

## Naming

- `snake_case` for functions, methods, variables, modules
- `PascalCase` for classes
- `UPPER_CASE` for module-level constants
- Prefix private methods/attributes with `_`

## Logging

- Use `logging` module, not `print()`
- Logger names: `rpc.poll`, `rpc.thread`, `rpc.sec.gss`, `rpc.lib`
- DEBUG for detailed tracing
- INFO for normal operational events
- WARNING for recoverable issues
- ERROR for failures that affect functionality

## Testing

- All `.x` test files must parse without errors
- Generated Python must be syntactically valid (`ast.parse()`)
- Generated Python must import successfully
- Pack/unpack round-trips must produce identical data

## Generated code

Generated code (`*_const.py`, `*_type.py`, `*_pack.py`) follows a
fixed format for compatibility with existing consumers. Do not
reformat or apply style rules to generated output.

## Dependencies

- Python 3.6+ minimum
- `xdrlib3` for XDR serialization (fallback to stdlib `xdrlib`)
- `gssapi` optional for RPCSEC_GSS/Kerberos
- No GPL-2.0-only dependencies permitted
