#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 Tom Haynes <loghyr@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# rpc.py - RPC client and server implementation
#
# Implements the ONC RPC protocol (RFC 1831) with TCP record marking
# (section 10), select-based I/O multiplexing, and threaded request
# handling. Supports AUTH_NONE, AUTH_SYS, and RPCSEC_GSS security.

from __future__ import with_statement
from __future__ import absolute_import

import socket
import select
import struct
import threading
import logging
import random
from collections import deque as Deque
from errno import EINPROGRESS, EWOULDBLOCK, EADDRINUSE

from . import rpc_pack
from .rpc_const import *
from .rpc_type import *

from . import rpc_security as security
from . import rpclib

log_p = logging.getLogger("rpc.poll")
log_t = logging.getLogger("rpc.thread")

LOOPBACK = "127.0.0.1"


def inc_u32(i):
    """Increment a 32 bit integer, with wrap-around."""
    return int((i + 1) & 0xffffffff)


class RPCError(Exception):
    pass


class RPCTimeout(RPCError):
    pass


class RPCAcceptError(RPCError):
    def __init__(self, a):
        self.verf = a.verf
        a = a.reply_data
        self.stat = a.stat
        if self.stat == PROG_MISMATCH:
            self.low = a.mismatch_info.low
            self.high = a.mismatch_info.high

    def __str__(self):
        if self.stat == PROG_MISMATCH:
            return "RPCError: MSG_ACCEPTED: PROG_MISMATCH [%i,%i]" % \
                   (self.low, self.high)
        else:
            return "RPCError: MSG_ACCEPTED: %s" % \
                   accept_stat.get(self.stat, self.stat)


class RPCDeniedError(RPCError):
    def __init__(self, r):
        self.stat = r.stat
        if self.stat == RPC_MISMATCH:
            self.low = r.mismatch_info.low
            self.high = r.mismatch_info.high
        elif self.stat == AUTH_ERROR:
            self.astat = r.astat

    def __str__(self):
        if self.stat == RPC_MISMATCH:
            return "RPCError: MSG_DENIED: RPC_MISMATCH [%i,%i]" % \
                   (self.low, self.high)
        else:
            return "RPCError: MSG_DENIED: AUTH_ERROR: %s" % \
                   auth_stat.get(self.astat, self.astat)


###################################################

class FancyRPCUnpacker(rpc_pack.RPCUnpacker):
    """RPC headers contain opaque credentials. Try to de-opaque them."""
    def _filter_opaque_auth(self, py_data):
        try:
            kls = security.klass(py_data.flavor)
        except Exception:
            return py_data
        try:
            body = kls.unpack_cred(py_data.body)
            out = opaque_auth(py_data.flavor, body)
            out.opaque = False
            return out
        except Exception:
            return py_data

    def filter_call_body(self, py_data):
        return call_body(py_data.rpcvers, py_data.prog, py_data.vers,
                         py_data.proc,
                         self._filter_opaque_auth(py_data.cred),
                         py_data.verf)


class FancyRPCPacker(rpc_pack.RPCPacker):
    """Re-opaque expanded credentials before sending."""
    def _filter_opaque_auth(self, py_data):
        if getattr(py_data, "opaque", True):
            return py_data
        kls = security.klass(py_data.flavor)
        return opaque_auth(py_data.flavor, kls.pack_cred(py_data.body))

    def filter_call_body(self, py_data):
        return call_body(py_data.rpcvers, py_data.prog, py_data.vers,
                         py_data.proc,
                         self._filter_opaque_auth(py_data.cred),
                         py_data.verf)


###################################################

class DeferredData(object):
    """Synchronization mechanism for async RPC replies.

    The calling thread creates an instance, then waits on it.
    The polling/worker thread fills it when the reply arrives.
    """
    def __init__(self, msg=None):
        self._filled = threading.Event()
        self.data = None
        self._exception = None
        self.msg = msg

    def wait(self, timeout=300):
        self._filled.wait(timeout)
        if not self._filled.is_set():
            raise RPCTimeout
        if self._exception is not None:
            raise self._exception

    def fill(self, data=None, exception=None):
        self._exception = exception
        self.data = data
        self._filled.set()


class Alarm(object):
    """Notifies the select loop that data is waiting via self-pipe trick."""
    def __init__(self, address):
        self._queue = Deque()
        self._s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._s.setblocking(0)
        try:
            self._s.connect(address)
        except socket.error as e:
            if e.args[0] in [EINPROGRESS, EWOULDBLOCK]:
                pass
            else:
                raise

    def buzz(self, command, info):
        self._queue.appendleft(info)
        while not self._s.send(command):
            pass

    def pop(self):
        return self._queue.pop()

    def __getattr__(self, attr):
        return getattr(self._s, attr)


class Pipe(object):
    """Socket wrapper with TCP record marking (RFC 1831 section 10).

    Records are split into packets with a 4-byte header (MSB = last-packet
    flag, lower 31 bits = packet length).
    """
    def __init__(self, sock, write_alarm):
        self._s = sock
        self._write_queue = Deque()
        self._alarm = write_alarm
        self._write_buf = b''
        self._read_buf = b''
        self._packet_buf = []

    def __getattr__(self, attr):
        return getattr(self._s, attr)

    def __str__(self):
        return "pipe-%i" % self._s.fileno()

    def recv_records(self, count):
        """Pull up to count bytes from pipe, converting into records."""
        data = self._s.recv(count)
        if not data:
            return None
        out = []
        self._read_buf += data
        while self._read_buf:
            buf = self._read_buf
            if len(buf) < 4:
                break
            packetlen = struct.unpack('>L', buf[0:4])[0]
            last = 0x80000000 & packetlen
            packetlen &= 0x7fffffff
            packetlen += 4
            if len(buf) < packetlen:
                break
            self._packet_buf.append(buf[4:packetlen])
            self._read_buf = buf[packetlen:]
            if last:
                record = b''.join(self._packet_buf)
                self._packet_buf = []
                out.append(record)
        return out

    def push_record(self, record):
        """Queue a record for sending (thread-safe)."""
        self._write_queue.appendleft(record)
        self._alarm.buzz(b'\x00', self)

    def pop_record(self, count):
        """Pull record off stack, add record marks, place in write buffer."""
        def add_record_marks(record, count):
            dlen = len(record)
            i = last = 0
            out = b''
            while not last:
                chunk = record[i:i + count]
                i += count
                if i >= dlen:
                    last = 0x80000000
                mark = struct.pack('>L', last | len(chunk))
                out += mark + chunk
            return out

        record = self._write_queue.pop()
        self._write_buf += add_record_marks(record, count)

    def flush_pipe(self):
        """Try to flush the write buffer. Returns True if fully flushed."""
        if not self._write_buf:
            raise RuntimeError
        try:
            count = self._s.send(self._write_buf)
        except socket.error as e:
            log_p.error("flush_pipe got exception %s" % str(e))
            return True
        self._write_buf = self._write_buf[count:]
        return not self._write_buf


class RpcPipe(Pipe):
    """Pipe with RPC XID management for matching calls to replies."""
    rpcversion = 2

    def __init__(self, *args, **kwargs):
        Pipe.__init__(self, *args, **kwargs)
        self._pending = {}
        self._lock = threading.Lock()
        self._xid = random.randint(0, 0x7fffffff)
        self.set_active()

    def _get_xid(self):
        with self._lock:
            out = self._xid
            self._xid = inc_u32(out)
        return out

    def set_active(self):
        self._active = True

    def clear_active(self):
        self._active = False

    def is_active(self):
        return self._active

    def listen(self, xid, timeout=None):
        """Wait for a reply to a CALL."""
        self._pending[xid].wait(timeout)
        reply = self._pending[xid].data
        del self._pending[xid]
        return reply

    def rpc_send(self, rpc_msg, data=b''):
        p = FancyRPCPacker()
        p.pack_rpc_msg(rpc_msg)
        header = p.get_buffer()
        self.push_record(header + data)

    def send_reply(self, xid, body, proc_response=""):
        log_t.debug("send_reply\nbody = %r\ndata=%r" % (body, proc_response))
        msg = rpc_msg(xid, rpc_msg_body(REPLY, rbody=body))
        self.rpc_send(msg, proc_response)

    def send_call(self, program, version, procedure, data, credinfo):
        """Send a CALL and store info needed to match and verify reply."""
        sec = credinfo.sec
        cred = sec.make_cred(credinfo)
        body = call_body(self.rpcversion, program, version, procedure,
                         cred, None)
        xid = self._get_xid()
        body.verf = sec.make_call_verf(xid, body)
        msg = rpc_msg(xid, rpc_msg_body(CALL, body))
        data = sec.secure_data(cred, data)
        self._pending[xid] = DeferredData((cred, sec))
        self.rpc_send(msg, data)
        return xid

    def rcv_reply(self, msg, msg_data):
        """Handle an incoming reply: verify, then fill the deferred."""
        try:
            deferred = self._pending[msg.xid]
        except KeyError:
            log_t.warning("Reply with unexpected xid=%i" % msg.xid)
            raise
        exc = None
        cred, sec = deferred.msg
        try:
            sec.check_reply_verf(msg, cred, msg_data)
        except Exception:
            log_t.warning("Reply did not pass verifier checks", exc_info=True)
            raise
        if msg.stat == MSG_DENIED:
            exc = RPCDeniedError(msg.rreply)
        elif msg.reply_data.stat != SUCCESS:
            exc = RPCAcceptError(msg.areply)
        else:
            try:
                msg_data = sec.unsecure_data(cred, msg_data)
            except Exception:
                exc = RPCError("Failed to unsecure data in reply")
        log_t.debug("Filling deferral %i" % msg.xid)
        reply = (msg, msg_data)
        deferred.fill(reply, exc)


#################################################

class ConnectionHandler(object):
    """Common code for RPC server and client.

    Sets up select-based polling and event dispatching, deals with RPC
    headers, XIDs, and record marking.
    """
    def __init__(self):
        self._stopped = False
        self.readlist = set()
        self.writelist = set()
        self.errlist = set()
        self.sockets = {}
        self.listeners = set()

        # Internal server for alarm system
        self.s = self.expose((LOOPBACK, 0), socket.AF_INET, False)

        # Alarm system for cross-thread notification
        self._alarm = Alarm(self.s.getsockname())
        self._alarm_poll = self._event_connect_incoming(self.s.fileno(),
                                                        internal=True)

        self.rsize = 4096
        self.wsize = 4098
        self.rpcversions = (2,)
        self.sec_flavors = security.instances()

    def _buzz_write_ready(self, pipe):
        pipe.pop_record(self.wsize)
        self.writelist.add(pipe.fileno())

    def _buzz_new_socket(self, data):
        pipe, defer = data
        fd = pipe.fileno()
        log_p.info("Adding %i generated by another thread" % fd)
        self.sockets[fd] = pipe
        self.readlist.add(fd)
        self.errlist.add(fd)
        defer.fill()

    def _buzz_stop(self, data):
        self._stopped = True

    def start(self):
        """Main event loop using select.select()."""
        switch = {
            0: self._buzz_write_ready,
            1: self._buzz_new_socket,
            2: self._buzz_stop,
        }
        while not self._stopped:
            log_p.debug("Calling select")
            r, w, e = select.select(self.readlist, self.writelist,
                                    self.errlist)
            for fd in e:
                log_p.warning("polling error from %i" % fd)
            for fd in w:
                try:
                    self._event_write(fd)
                except socket.error:
                    self._event_close(fd)
            for fd in r:
                if fd in self.listeners:
                    try:
                        self._event_connect_incoming(fd)
                    except socket.error:
                        self._event_close(fd)
                elif fd == self._alarm_poll.fileno():
                    commands = self._alarm_poll.recv(self.rsize)
                    for c in commands:
                        data = self._alarm.pop()
                        try:
                            switch[c](data)
                        except socket.error:
                            self._event_close(fd)
                else:
                    try:
                        data = self.sockets[fd].recv_records(self.rsize)
                    except socket.error:
                        data = None
                    if data is not None:
                        self._event_read(data, fd)
                    else:
                        self._event_close(fd)
        for s in self.sockets.values():
            s.close()

    def stop(self):
        self._alarm.buzz(b'\x02', None)

    def _event_connect_incoming(self, fd, internal=False):
        s = self.sockets[fd]
        try:
            if internal:
                s.setblocking(1)
                csock, caddr = s.accept()
                s.setblocking(0)
            else:
                csock, caddr = s.accept()
        except socket.error as e:
            log_p.error("accept() got error %s" % str(e))
            return
        csock.setblocking(0)
        fd = csock.fileno()
        pipe = self.sockets[fd] = RpcPipe(csock, self._alarm)
        log_p.info("got connection from %s, assigned to fd=%i" %
                   (csock.getpeername(), fd))
        self.readlist.add(fd)
        self.errlist.add(fd)
        return pipe

    def _event_close(self, fd):
        log_p.info("Closing %i" % fd)
        temp = set([fd])
        self.writelist -= temp
        self.readlist -= temp
        self.errlist -= temp
        self.sockets[fd].clear_active()
        self.sockets[fd].close()
        del self.sockets[fd]

    def _event_write(self, fd):
        if self.sockets[fd].flush_pipe():
            self.writelist.remove(fd)
            log_p.log(5, "Finished writing to %i" % fd)

    def _event_read(self, records, fd):
        s = self.sockets[fd]
        for r in records:
            log_p.log(5, "Received record from %i" % fd)
            t = threading.Thread(target=self._event_rpc_record, args=(r, s))
            t.setDaemon(True)
            t.start()

    def _event_rpc_record(self, record, pipe):
        log_t.log(5, "_event_rpc_record thread receives %r" % record)
        try:
            p = FancyRPCUnpacker(record)
            msg = p.unpack_rpc_msg()
            msg_data = record[p.get_position():]
            msg.length = p.get_position()
        except (rpc_pack.XDRError, EOFError) as e:
            log_t.warning("XDRError: %s, dropping packet" % e)
            log_t.debug("unpacking raised the following error", exc_info=True)
            self._notify_drop()
            return
        log_t.debug("MSG = %s" % str(msg))
        if msg.mtype == REPLY:
            self._event_rpc_reply(msg, msg_data, pipe)
        elif msg.mtype == CALL:
            self._event_rpc_call(msg, msg_data, pipe)
        else:
            log_t.error("Received rpc_record with msg.type=%i" % msg.type)
            self._notify_drop()

    def _event_rpc_reply(self, msg, msg_data, pipe):
        try:
            pipe.rcv_reply(msg, msg_data)
        except Exception:
            self._notify_drop()

    def _event_rpc_call(self, msg, msg_data, pipe):
        class CallInfo:
            pass
        call_info = CallInfo()
        call_info.header_size = msg.length
        call_info.payload_size = len(msg_data)
        call_info.connection = pipe
        call_info.raw_cred = msg.body.cred
        notify = None
        try:
            try:
                self._check_rpcvers(msg)
                call_info.credinfo = self._check_auth(msg, msg_data)
            except rpclib.RPCFlowContol:
                raise
            except Exception:
                log_t.warning(
                    "Problem with incoming call, returning AUTH_FAILED",
                    exc_info=True)
                raise rpclib.RPCDeniedReply(AUTH_ERROR, AUTH_FAILED)
            sec = call_info.credinfo.sec
            msg_data = sec.unsecure_data(msg.body.cred, msg_data)
            if not self._check_program(msg.prog):
                log_t.warning("PROG_UNAVAIL, do not support prog=%i" %
                              msg.prog)
                raise rpclib.RPCUnsuccessfulReply(PROG_UNAVAIL)
            low, hi = self._version_range(msg.prog)
            if not self._check_version(low, hi, msg.vers):
                log_t.warning("PROG_MISMATCH, do not support vers=%i" %
                              msg.vers)
                raise rpclib.RPCUnsuccessfulReply(PROG_MISMATCH, (low, hi))
            method = self._find_method(msg)
            if method is None:
                log_t.warning("PROC_UNAVAIL for vers=%i, proc=%i" %
                              (msg.vers, msg.proc))
                raise rpclib.RPCUnsuccessfulReply(PROC_UNAVAIL)
            result_tuple = method(msg_data, call_info)
            if len(result_tuple) == 2:
                status, result = result_tuple
            else:
                status, result, notify = result_tuple
            if result is None:
                result = b''
            if isinstance(result, str):
                result = bytes(result, encoding='UTF-8')
            if not isinstance(result, bytes):
                raise TypeError("Expected bytes, got %s" % type(result))
        except rpclib.RPCDrop:
            self._notify_drop()
            return
        except rpclib.RPCFlowContol as e:
            body, data = e.body()
        except Exception:
            log_t.warning("Unexpected exception", exc_info=True)
            body, data = rpclib.RPCUnsuccessfulReply(SYSTEM_ERR).body()
        else:
            try:
                data = sec.secure_data(msg.body.cred, result)
                verf = sec.make_reply_verf(msg.body.cred, status)
                areply = accepted_reply(verf, rpc_reply_data(status, b''))
                body = reply_body(MSG_ACCEPTED, areply=areply)
            except Exception:
                body, data = rpclib.RPCUnsuccessfulReply(SYSTEM_ERR).body()
        pipe.send_reply(msg.xid, body, data)
        if notify is not None:
            notify()

    def _notify_drop(self):
        log_t.warning("Dropped request")

    def _find_method(self, msg):
        raise NotImplementedError

    def _version_range(self, prog):
        raise NotImplementedError

    def _check_program(self, prog):
        raise NotImplementedError

    def _check_rpcvers(self, msg):
        if msg.rpcvers not in self.rpcversions:
            log_t.warning("RPC_MISMATCH, do not support vers=%i" %
                          msg.rpcvers)
            raise rpclib.RPCDeniedReply(RPC_MISMATCH,
                                        (min(self.rpcversions),
                                         max(self.rpcversions)))

    def _check_auth(self, msg, data):
        try:
            sec = self.sec_flavors[msg.cred.flavor]
        except KeyError:
            log_t.warning("AUTH_ERROR: Unsupported flavor %i" %
                          msg.cred.flavor)
            if msg.proc == 0 and msg.cred.flavor == AUTH_NONE:
                log_t.warning("Allowing NULL proc through anyway")
                sec = security.klass(AUTH_NONE)()
            else:
                raise rpclib.RPCDeniedReply(AUTH_ERROR, AUTH_FAILED)
        return sec.check_auth(msg, data)

    def connect(self, address, secure=False):
        """Connect to address, returning new RpcPipe."""
        log_t.info("Called connect(%r)" % (address,))
        host, port = address
        s = None
        for res in socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM):
            af, socktype, proto, cannonname, sa = res
            try:
                s = socket.socket(af, socktype, proto)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if secure:
                    self.bindsocket(s)
                s.connect(sa)
                break
            except Exception:
                if s is not None:
                    s.close()
                    s = None
        if s is None:
            raise socket.error(
                "Could not connect to any address for %s:%s" % (host, port))
        s.setblocking(0)
        pipe = RpcPipe(s, self._alarm)
        defer = DeferredData()
        self._alarm.buzz(b'\x01', (pipe, defer))
        defer.wait()
        return pipe

    def bindsocket(self, s, port=1):
        """Scan up through ports, looking for one we can bind to."""
        using = port
        while True:
            try:
                s.bind(('', using))
                return
            except OSError as why:
                if why.errno == EADDRINUSE:
                    using += 1
                    if port < 1024 <= using:
                        raise
                else:
                    raise

    def expose(self, address, af, safe=True):
        """Start listening for incoming connections on the given address."""
        s = socket.socket(af, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(address)
        s.setblocking(0)
        s.listen(5)
        self.listeners.add(s.fileno())
        if safe:
            defer = DeferredData()
            self._alarm.buzz(b'\x01', (s, defer))
            defer.wait()
        else:
            self.readlist.add(s.fileno())
            self.errlist.add(s.fileno())
            self.sockets[s.fileno()] = s
        return s

    def make_call_function(self, pipe, procedure, prog, vers):
        def call(data, credinfo, proc=None, timeout=300):
            if proc is None:
                proc = procedure
            xid = self.send_call(pipe, proc, data, credinfo, prog, vers)
            header, data = pipe.listen(xid, timeout)
            return header, data
        return call

    def listen(self, pipe, xid):
        header, data = pipe.listen(xid)
        print("HEADER", header)
        print("DATA", repr(data))


#################################################

class Server(ConnectionHandler):
    def __init__(self, prog, versions, port, interface=''):
        ConnectionHandler.__init__(self)
        self.prog = prog
        self.versions = versions
        self.default_cred = security.CredInfo()
        try:
            self.expose((interface, port), socket.AF_INET6, False)
        except Exception:
            self.expose((interface, port), socket.AF_INET, False)

    def _check_program(self, prog):
        return self.prog == prog

    def _check_version(self, low, hi, vers):
        return low <= vers <= hi

    def _version_range(self, prog):
        return (min(self.versions), max(self.versions))

    def _find_method(self, msg):
        method = getattr(self, 'handle_%i' % msg.proc, None)
        if method is not None:
            return method
        method = getattr(self, 'handle_%i_v%i' % (msg.proc, msg.vers), None)
        return method


class Client(ConnectionHandler):
    def __init__(self, program=None, version=None, secureport=False):
        ConnectionHandler.__init__(self)
        self.default_prog = program
        self.default_vers = version
        self.default_cred = security.CredInfo()
        self.secureport = secureport

        # Start polling thread
        t = threading.Thread(target=self.start, name="PollingThread")
        t.setDaemon(True)
        t.start()

    def send_call(self, pipe, procedure, data=b'', credinfo=None,
                  program=None, version=None):
        if program is None:
            program = self.default_prog
        if version is None:
            version = self.default_vers
        if program is None or version is None:
            raise Exception("Badness")
        if credinfo is None:
            credinfo = self.default_cred
        return pipe.send_call(program, version, procedure, data, credinfo)
