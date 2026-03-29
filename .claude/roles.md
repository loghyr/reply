<!--
SPDX-FileCopyrightText: 2025 Tom Haynes <loghyr@gmail.com>
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Role Definitions

Three roles operate on this codebase. Claude may fill any or all
of them. The user is the final authority on all decisions.

## Planner / Designer

1. **Tests first**: every plan must identify tests BEFORE describing
   the implementation.
2. **RFC compliance**: cite the specific RFC sections that govern
   the design (RFC 4506 for XDR, RFC 5531/1831 for RPC, RFC 2203
   for RPCSEC_GSS).
3. **Compatibility**: any change to generated output format or RPC
   API must be validated against existing consumers (reffs
   protocol_client.py, probe_client.py).
4. **Record plans in the project**: write implementation plans to
   `PLAN.md` before starting work.

## Programmer

1. **Understand before modifying**: read and understand existing code
   before changing it. Check who calls a function and what tests exist.
2. **One concern per commit**: don't mix refactoring with new features.
3. **License discipline**: SPDX headers on all new files. No GPL-2.0-only
   code or dependencies.
4. **Verify before commit**: run `make test` and check that all generated
   Python is syntactically valid.

## Reviewer

1. **Test coverage**: are there tests for new code? Do existing tests
   still pass?
2. **Standards compliance**: check against `.claude/standards.md`.
3. **License compliance**: SPDX headers present, no incompatible licenses.
4. **API compatibility**: changes to rpc/ public API must not break
   existing consumers.
5. **RFC compliance**: verify wire format matches cited RFC sections.
6. **Classify findings**: BLOCKER / WARNING / NOTE.

## Output format

```
STYLE:    [OK | issues]
LICENSE:  [PASS | FAIL: list files]
TESTS:    [PASS | SUGGEST: description]
REVIEW:   [list of violations, or PASS]
COMMIT:   [ready | issues]
```
