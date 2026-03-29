<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# xdr_parser.py — XDR Parser and Code Generator

## Overview

`xdr_parser.py` is a hand-written recursive descent parser for XDR
(External Data Representation, RFC 4506) with RPC extensions (RFC 5531).
It reads `.x` files and generates Python or C source code.

## Command Line

```
xdr_parser.py [options] input.x

Options:
  --lang {python,c}   Target language (default: python)
  --output-dir DIR     Output directory (default: current directory)
  --prefix PREFIX      Prefix for output filenames (default: input basename)
  --help               Show help message
```

## Python Output

For each input `protocol.x`, generates three files:

### protocol_const.py

Constants and enumeration reverse-maps:

```python
MAX_SIZE = 1024
AUTH_NONE = 0
AUTH_SYS = 1
auth_flavor = {
    0 : 'AUTH_NONE',
    1 : 'AUTH_SYS',
}
```

Program, version, and procedure numbers from RPC `program` blocks are
also emitted as constants.

### protocol_type.py

Python classes for each struct and union:

```python
class opaque_auth:
    def __init__(self, flavor=None, body=None):
        self.flavor = flavor
        self.body = body
    def __repr__(self):
        ...
```

Unions get a `switch` property that returns the active arm based on
the discriminant value, plus `__getattr__` delegation:

```python
class reply_body:
    switch = property(lambda s: {const.MSG_ACCEPTED:s.areply,...}[s.stat])
    def __getattr__(self, attr):
        return getattr(self.switch, attr)
```

Structs with exactly one struct/union member get `__getattr__`
passthrough for convenience.

Simple typedefs produce aliases: `mountlist = mountbody`.

### protocol_pack.py

Packer and Unpacker classes extending `xdrlib.Packer` / `xdrlib.Unpacker`:

```python
class PROTOCOLPacker(xdrlib.Packer):
    def __init__(self, check_enum=True, check_array=True):
        ...
    def pack_opaque_auth(self, data):
        ...

class PROTOCOLUnpacker(xdrlib.Unpacker):
    def __init__(self, data, check_enum=True, check_array=True):
        ...
    def unpack_opaque_auth(self):
        ...
```

The packer/unpacker use `xdrlib3` if available, falling back to the
stdlib `xdrlib` module.

Filter hooks (`filter_TypeName`) allow subclasses to intercept
pack/unpack operations (used by FancyRPCPacker for credential expansion).

## C Output

For each input `protocol.x`, generates two files:

### protocol_xdr.h

```c
#ifndef PROTOCOL_XDR_H
#define PROTOCOL_XDR_H

#include <rpc/xdr.h>

#define MAX_SIZE 1024
enum auth_flavor { AUTH_NONE = 0, AUTH_SYS = 1 };
struct opaque_auth { ... };
extern bool_t xdr_opaque_auth(XDR *, struct opaque_auth *);

#endif
```

### protocol_xdr.c

```c
#include "protocol_xdr.h"

bool_t xdr_opaque_auth(XDR *xdrs, struct opaque_auth *objp) {
    if (!xdr_auth_flavor(xdrs, &objp->flavor))
        return FALSE;
    ...
    return TRUE;
}
```

## XDR Language Features

Supports the full XDR grammar (RFC 4506 Section 6.3) plus RPC
extensions (RFC 5531 Section 11):

| Feature | Example |
|---------|---------|
| Constants | `const MAX = 1024;` |
| Enumerations | `enum status { OK = 0, ERR = 1 };` |
| Structures | `struct point { int x; int y; };` |
| Discriminated unions | `union result switch (status s) { case OK: int val; default: void; };` |
| Typedefs | `typedef string filename<255>;` |
| Fixed arrays | `int data[10];` |
| Variable arrays | `int data<100>;` |
| Opaque data | `opaque key[16];` / `opaque data<>;` |
| Strings | `string name<255>;` |
| Pointers | `node *next;` |
| RPC programs | `program FOO { version V1 { ... } = 1; } = 100000;` |
| Basic types | `int`, `unsigned int`, `hyper`, `unsigned hyper`, `float`, `double`, `quadruple`, `bool`, `void` |

Additional features beyond the strict RFC grammar:
- `long` / `unsigned long` aliases (common in legacy `.x` files)
- `struct` keyword as type prefix: `struct foo bar;`
- `#ifdef` / `#endif` preprocessor directives (skipped)
- `%` passthrough lines (preserved in C output)
- Fall-through union cases
- Python keyword escaping (`from` -> `from_` in generated Python)

## Examples

### Generate Python from an NFS protocol definition

```bash
./xdr_parser.py --lang python --output-dir out/ nfs_prot.x
```

### Use generated code

```python
from out.nfs_prot_const import *
from out.nfs_prot_type import *
from out.nfs_prot_pack import NFS_PROTPacker, NFS_PROTUnpacker

# Pack
p = NFS_PROTPacker()
p.pack_some_type(some_type(field1=42, field2=b'hello'))
wire_data = p.get_buffer()

# Unpack
u = NFS_PROTUnpacker(wire_data)
result = u.unpack_some_type()
```

### Generate C

```bash
./xdr_parser.py --lang c --output-dir out/ nfs_prot.x
gcc -c out/nfs_prot_xdr.c -I out/
```
