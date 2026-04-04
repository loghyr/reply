<!-- SPDX-License-Identifier: Apache-2.0 -->
# rpc/ — ONC RPC Client/Server Library

## Overview

The `rpc/` package implements ONC RPC (RFC 1831) with RPCSEC_GSS
(RFC 2203) support. It provides client and server classes with TCP
record marking, select-based I/O multiplexing, and threaded request
handling.

## Package Structure

| Module | Purpose |
|--------|---------|
| `rpc.rpc` | Client, Server, ConnectionHandler, Pipe, record marking |
| `rpc.rpclib` | NULL_CRED constant, flow-control exceptions |
| `rpc.rpc_security` | AUTH_NONE, AUTH_SYS, RPCSEC_GSS security flavors |
| `rpc.rpc_const` | Generated constants from `rpc.x` |
| `rpc.rpc_type` | Generated type classes from `rpc.x` |
| `rpc.rpc_pack` | Generated Packer/Unpacker from `rpc.x` |
| `rpc.gss_const` | Generated constants from `gss.x` |
| `rpc.gss_type` | Generated type classes from `gss.x` |
| `rpc.gss_pack` | Generated Packer/Unpacker from `gss.x` |

## Quick Start: RPC Client

```python
from rpc.rpc import Client

# Connect to an RPC service
client = Client(program=100003, version=3)  # NFS v3
pipe = client.connect(('server.example.com', 2049))

# Send a NULL procedure call (procedure 0)
xid = client.send_call(pipe, 0)
header, data = pipe.listen(xid, timeout=10)
print("NULL call succeeded")
```

## Building a Protocol Client

For a real protocol, subclass `Client` or use the generated packer/unpacker
to encode procedure arguments:

```python
from rpc.rpc import Client
from rpc.rpc_security import AuthSys

# Create client with AUTH_SYS credentials
client = Client(program=100003, version=3)
pipe = client.connect(('server', 2049))

# Set up AUTH_SYS credentials
auth = AuthSys()
cred = auth.init_cred(uid=1000, gid=1000, name=b'myhost')

# Send a call with credentials
from my_protocol_pack import MY_PROTOCOLPacker
p = MY_PROTOCOLPacker()
p.pack_my_args(my_args(path=b'/test'))
xid = client.send_call(pipe, 1, p.get_buffer(), cred)

# Receive and decode response
header, data = pipe.listen(xid, timeout=10)
from my_protocol_pack import MY_PROTOCOLUnpacker
u = MY_PROTOCOLUnpacker(data)
result = u.unpack_my_result()
```

## Building a Protocol Server

```python
from rpc.rpc import Server

class MyServer(Server):
    def handle_0(self, data, call_info):
        """NULL procedure"""
        return 0, b''

    def handle_1(self, data, call_info):
        """Custom procedure"""
        # Decode request
        u = MY_PROTOCOLUnpacker(data)
        args = u.unpack_my_args()

        # Process and encode response
        p = MY_PROTOCOLPacker()
        p.pack_my_result(my_result(status=0))
        return 0, p.get_buffer()

server = MyServer(prog=100003, versions=[3], port=2049)
server.start()  # Blocks, runs event loop
```

## Security Flavors

### AUTH_NONE (no authentication)

```python
from rpc.rpc_security import AuthNone
cred = AuthNone().init_cred()
```

### AUTH_SYS (UNIX credentials)

```python
from rpc.rpc_security import AuthSys
cred = AuthSys().init_cred(uid=1000, gid=1000, name=b'myhost',
                            gids=[100, 200])
```

### RPCSEC_GSS (Kerberos)

Requires the `gssapi` Python package:

```python
from rpc.rpc_security import AuthGss

auth = AuthGss()
# The call function is provided by make_call_function()
call = client.make_call_function(pipe, 0, program, version)
cred = auth.init_cred(call, target="nfs@server.example.com")
```

## Key Classes

### Client

```python
class Client(ConnectionHandler):
    def __init__(self, program=None, version=None, secureport=False)
    def connect(self, address, secure=False) -> RpcPipe
    def send_call(self, pipe, procedure, data=b'', credinfo=None,
                  program=None, version=None) -> xid
```

- Spawns a daemon polling thread on creation
- `connect()` establishes a TCP connection and returns an `RpcPipe`
- `send_call()` is non-blocking; use `pipe.listen(xid)` to wait

### RpcPipe

```python
class RpcPipe(Pipe):
    def listen(self, xid, timeout=None) -> (header, data)
    def is_active(self) -> bool
```

- `listen()` blocks until the reply matching `xid` arrives
- `is_active()` returns False if the connection has been closed

### CredInfo

```python
class CredInfo:
    flavor    # AUTH_NONE, AUTH_SYS, or RPCSEC_GSS
    principal # b"nobody", b"uid@host", or GSS name
    sec       # Auth* instance
    context   # authsys_parms or GSS handle
    service   # rpc_gss_svc_none/integrity/privacy
```

## Flow Control Exceptions (Server-Side)

The server uses exceptions for message flow control:

| Exception | Effect |
|-----------|--------|
| `RPCDrop` | Silently drop the request |
| `RPCDeniedReply(stat, data)` | Send MSG_DENIED reply |
| `RPCUnsuccessfulReply(stat, data)` | Send MSG_ACCEPTED with error status |
| `RPCSuccessfulReply(verf, data)` | Send MSG_ACCEPTED with SUCCESS |

These are raised by security checks or procedure handlers and caught
by the ConnectionHandler event loop.

## Regenerating XDR Modules

The `rpc_const.py`, `rpc_type.py`, `rpc_pack.py`, `gss_const.py`,
`gss_type.py`, and `gss_pack.py` files are generated from `rpc.x`
and `gss.x`:

```bash
make generate-rpc
```

Or manually:

```bash
./xdr_parser.py --lang python --output-dir rpc rpc.x
./xdr_parser.py --lang python --output-dir rpc gss.x
```
