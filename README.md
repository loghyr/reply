<!-- SPDX-License-Identifier: Apache-2.0 -->
# reply — XDR/RPC toolkit for Python

A Python XDR parser, code generator, and ONC RPC client/server library.

Implements RFC 4506 (XDR), RFC 5531 (RPC), and RFC 2203 (RPCSEC_GSS).
Designed as a clean-room replacement for pynfs with no GPL dependencies.

## Components

### xdr_parser.py — XDR Parser and Code Generator

Hand-written recursive descent parser that reads `.x` (XDR) files and
generates Python or C code.

```bash
# Generate Python modules from an XDR definition
./xdr_parser.py --lang python --output-dir out/ protocol.x
# Produces: out/protocol_const.py, out/protocol_type.py, out/protocol_pack.py

# Generate C modules
./xdr_parser.py --lang c --output-dir out/ protocol.x
# Produces: out/protocol_xdr.h, out/protocol_xdr.c
```

### rpc/ — ONC RPC Client/Server

Python package implementing the ONC RPC protocol:

- **rpc.rpc** — Client and Server classes with TCP record marking,
  select-based I/O, and threaded request handling
- **rpc.rpclib** — Flow control exceptions and NULL_CRED constant
- **rpc.rpc_security** — AUTH_NONE, AUTH_SYS, and RPCSEC_GSS (Kerberos)
  security flavors

```python
from rpc.rpc import Client
from rpc.rpc_security import CredInfo, AuthSys

client = Client(program=100003, version=3)
pipe = client.connect(('server', 2049))
xid = client.send_call(pipe, 0)  # NULL procedure
header, data = pipe.listen(xid)
```

## Requirements

- Python 3.6+
- [xdrlib3](https://pypi.org/project/xdrlib3/) (or stdlib xdrlib on Python < 3.12)
- Optional: [gssapi](https://pypi.org/project/gssapi/) for RPCSEC_GSS/Kerberos

## Install

```bash
pip install reply-xdr
```

Or from source:
```bash
pip install .
```

## Testing

```bash
make test          # Parse all test XDR files
make test-python   # Generate Python from all tests
make test-c        # Generate C from all tests
```

## License

Apache-2.0. See [LICENSE](LICENSE) for the full text.

The `.x` files derived from IETF RFCs retain their original BSD-3-Clause
license as noted in their headers.
