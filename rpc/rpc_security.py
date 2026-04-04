#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 Tom Haynes <loghyr@gmail.com>
# SPDX-License-Identifier: Apache-2.0
#
# rpc_security.py - RPC authentication and security
#
# Implements AUTH_NONE, AUTH_SYS (RFC 1831), and RPCSEC_GSS (RFC 2203)
# security flavors for RPC. The RPCSEC_GSS support requires the
# optional gssapi Python module for Kerberos.

from .rpc_const import AUTH_NONE, AUTH_SYS, RPCSEC_GSS, SUCCESS, CALL, \
    MSG_ACCEPTED
from .rpc_type import opaque_auth, authsys_parms
from .rpc_pack import RPCPacker, RPCUnpacker
from .gss_pack import GSSPacker, GSSUnpacker
from . import rpclib
from .gss_const import *
from . import gss_type
from .gss_type import rpc_gss_init_res
try:
    import gssapi
    from gssapi.raw.misc import GSSError
except ImportError:
    gssapi = None
import threading
import logging

try:
    from xdrlib3 import Packer, Unpacker
except Exception:
    from xdrlib import Packer, Unpacker

log_gss = logging.getLogger("rpc.sec.gss")
log_gss.setLevel(logging.INFO)

WINDOWSIZE = 8  # Sliding window size for GSS replay detection


class SecError(Exception):
    pass


class CredInfo(object):
    """Information needed to build a CALL credential."""
    def _get_principal(self):
        if self.flavor == AUTH_NONE:
            return b"nobody"
        elif self.flavor == AUTH_SYS:
            return b"%d@%s" % (self.context.uid, self.context.machinename)
        elif self.flavor == RPCSEC_GSS:
            c = self.sec._get_context(self.context)
            if c is None:
                return b"gss_nobody"
            else:
                return c.source_name.name
        else:
            raise SecError("Unknown flavor %s" % self.flavor)

    flavor = property(lambda s: s.sec.flavor)
    principal = property(_get_principal)

    def __init__(self, sec=None, context=None,
                 service=rpc_gss_svc_none, gss_proc=RPCSEC_GSS_DATA, qop=0):
        if sec is None:
            sec = AuthNone()
        self.sec = sec
        self.context = context
        self.service = service
        self.qop = qop
        self.gss_proc = gss_proc


class AuthNone(object):
    """AUTH_NONE: no security."""
    flavor = AUTH_NONE
    name = "AUTH_NONE"

    def get_info(self, header):
        return None

    def make_reply_verf(self, cred, stat):
        return rpclib.NULL_CRED

    def make_call_verf(self, xid, body):
        return rpclib.NULL_CRED

    def unsecure_data(self, cred, data):
        return data

    def secure_data(self, msg, data):
        return data

    @staticmethod
    def pack_cred(py_data):
        return py_data

    @staticmethod
    def unpack_cred(data):
        return data

    def init_cred(self):
        return CredInfo(self)

    def make_cred(self, credinfo):
        return rpclib.NULL_CRED

    def check_auth(self, msg, data):
        return CredInfo(self)

    def check_reply_verf(self, msg, call_cred, data):
        if msg.stat == MSG_ACCEPTED and not self.is_NULL(msg.body.verf):
            raise SecError("Bad reply verifier - expected NULL verifier")

    def is_NULL(self, cred):
        return cred.flavor == AUTH_NONE and cred.body == b''


class AuthSys(AuthNone):
    """AUTH_SYS: standard UNIX-based security (RFC 1831 Appendix A)."""
    flavor = AUTH_SYS
    name = "AUTH_SYS"

    def get_info(self, py_header):
        return None

    @staticmethod
    def pack_cred(py_cred):
        p = RPCPacker()
        p.pack_authsys_parms(py_cred)
        return p.get_buffer()

    @staticmethod
    def unpack_cred(cred):
        p = RPCUnpacker(cred)
        py_cred = p.unpack_authsys_parms()
        p.done()
        return py_cred

    def init_cred(self, uid=None, gid=None, name=None, stamp=42, gids=None):
        if uid is None:
            uid = 0
        if gid is None:
            gid = 0
        if name is None:
            name = b"default machinename"
        if gids is None:
            gids = [3, 17, 100]
        return CredInfo(self, authsys_parms(stamp, name, uid, gid, gids))

    def make_cred(self, credinfo):
        if credinfo is None:
            who = self.init_cred()
        else:
            who = credinfo.context
        out = opaque_auth(AUTH_SYS, who)
        out.opaque = False
        return out

    def check_auth(self, msg, data):
        return CredInfo(self, msg.cred.body)


class GSSContext(object):
    """Wrapper around a gssapi SecurityContext with replay detection."""
    def __init__(self, context_ptr):
        self.lock = threading.Lock()
        self.ptr = context_ptr
        self.seqid = 0
        self.highest = 0
        self.seen = 0

    def __getattr__(self, attr):
        return self.ptr.__getattribute__(attr)

    def expired(self):
        return False

    def get_seqid(self):
        with self.lock:
            out = self.seqid
            self.seqid += 1
        return out

    def check_seqid(self, seqid):
        """RFC 2203 Sect 5.3.3.1 sliding window replay detection."""
        with self.lock:
            diff = seqid - self.highest
            if diff <= -WINDOWSIZE:
                raise rpclib.RPCDrop
            elif diff > 0:
                self.highest += diff
                self.seen >>= diff
                self.seen |= (1 << (WINDOWSIZE - 1))
            else:
                if (1 << (-diff)) & self.seen:
                    raise rpclib.RPCDrop


class AuthGss(AuthNone):
    """RPCSEC_GSS: Kerberos-based security (RFC 2203)."""
    flavor = RPCSEC_GSS
    name = "RPCSEC_GSS"

    def __init__(self):
        self.contexts = {}

    def _add_context(self, context, handle=None):
        if handle is None:
            handle = repr(context.handle)
        self.contexts[handle] = GSSContext(context)
        return handle

    def _get_context(self, handle):
        return self.contexts.get(handle, None)

    def init_given_context(self, context, handle=None,
                           service=rpc_gss_svc_none):
        self._add_context(context, handle)
        return CredInfo(self, context=handle, service=service)

    def init_cred(self, call, target="nfs@jupiter", source=None, oid=None):
        good_major = [GSS_S_COMPLETE, GSS_S_CONTINUE_NEEDED]
        p = Packer()
        up = GSSUnpacker('')
        target = gssapi.Name(target, gssapi.NameType.hostbased_service)
        if source is not None:
            source = gssapi.Name(source, gssapi.NT_USER_NAME)
            gss_cred = gssapi.Credential(gssapi.INITIATE, source.ptr)
        else:
            gss_cred = None
        flags = gssapi.IntEnumFlagSet(
            gssapi.RequirementFlag,
            [gssapi.RequirementFlag.mutual_authentication])
        context = gssapi.SecurityContext(
            name=target, creds=gss_cred, flags=flags)
        input_token = None
        handle = b''
        proc = RPCSEC_GSS_INIT
        while not context.complete:
            output_token = context.step(input_token)
            if context.complete:
                self._add_context(context, handle)
                break
            credinfo = CredInfo(self, context=handle, gss_proc=proc)
            proc = RPCSEC_GSS_CONTINUE_INIT
            p.reset()
            p.pack_opaque(output_token)
            header, reply = call(p.get_buffer(), credinfo)
            up.reset(reply)
            res = up.unpack_rpc_gss_init_res()
            up.done()
            if res.gss_major not in good_major:
                raise GSSError(res.gss_major, res.gss_minor)
            handle = res.handle
            input_token = res.gss_token
        return CredInfo(self, context=handle)

    @staticmethod
    def pack_cred(py_cred):
        p = GSSPacker()
        p.pack_rpc_gss_cred_t(py_cred)
        return p.get_buffer()

    @staticmethod
    def unpack_cred(cred):
        p = GSSUnpacker(cred)
        py_cred = p.unpack_rpc_gss_cred_t()
        p.done()
        return py_cred

    def make_cred(self, credinfo):
        log_gss.debug("Calling make_cred %r" % credinfo)
        if credinfo.gss_proc in (RPCSEC_GSS_INIT, RPCSEC_GSS_CONTINUE_INIT):
            context = None
            seqid = 0
        else:
            context = self._get_context(credinfo.context)
            seqid = context.get_seqid()
        data = gss_type.rpc_gss_cred_vers_1_t(
            credinfo.gss_proc, seqid, credinfo.service, credinfo.context)
        cred = gss_type.rpc_gss_cred_t(RPCSEC_GSS_VERS_1, data)
        out = opaque_auth(RPCSEC_GSS, cred)
        out.opaque = False
        out.context = context
        out.body.qop = credinfo.qop
        log_gss.debug("make_cred = %r" % out)
        return out

    def unsecure_data(self, cred, data):
        def pull_seqnum(blob):
            p.reset(blob)
            try:
                seq_num = p.unpack_uint()
            except Exception:
                log_gss.exception("unsecure_data - unpacking seq_num")
                raise rpclib.RPCUnsuccessfulReply(GARBAGE_ARGS)
            if seq_num != cred.seq_num:
                raise rpclib.RPCUnsuccessfulReply(GARBAGE_ARGS)
            return p.get_buffer()[p.get_position():]

        def check_gssapi(qop):
            if qop != cred.qop:
                log_gss.warning("unsecure_data: mismatched qop %i != %i" %
                                (qop, cred.qop))
                raise rpclib.RPCUnsuccessfulReply(GARBAGE_ARGS)

        cred = cred.body
        if cred.service == rpc_gss_svc_none or \
           cred.gss_proc in (RPCSEC_GSS_INIT, RPCSEC_GSS_CONTINUE_INIT):
            return data
        p = GSSUnpacker(data)
        context = self._get_context(cred.handle)
        try:
            if cred.service == rpc_gss_svc_integrity:
                try:
                    data = p.unpack_opaque()
                    checksum = p.unpack_opaque()
                    p.done()
                except Exception:
                    log_gss.exception("unsecure_data - initial unpacking")
                    raise rpclib.RPCUnsuccessfulReply(GARBAGE_ARGS)
                qop = context.verify_signature(data, checksum)
                check_gssapi(qop)
                data = pull_seqnum(data)
            elif cred.service == rpc_gss_svc_privacy:
                try:
                    data = p.unpack_opaque()
                    p.done()
                except Exception:
                    log_gss.exception("unsecure_data - initial unpacking")
                    raise rpclib.RPCUnsuccessfulReply(GARBAGE_ARGS)
                data, encrypted, qop = context.unwrap(data)
                check_gssapi(qop)
                data = pull_seqnum(data)
            else:
                log_gss.error("Unknown service %i for RPCSEC_GSS" %
                              cred.service)
        except GSSError as e:
            log_gss.warning("unsecure_data: gssapi call returned %s" % str(e))
            raise rpclib.RPCUnsuccessfulReply(GARBAGE_ARGS)
        return data

    def secure_data(self, cred, data):
        log_gss.debug("secure_data(%r)" % cred)
        cred = cred.body
        if cred.service == rpc_gss_svc_none or \
           cred.gss_proc in (RPCSEC_GSS_INIT, RPCSEC_GSS_CONTINUE_INIT):
            return data
        p = Packer()
        context = self._get_context(cred.handle)
        try:
            if cred.service == rpc_gss_svc_integrity:
                p.pack_uint(cred.seq_num)
                data = p.get_buffer() + data
                token = context.get_signature(data)
                p.reset()
                p.pack_opaque(data)
                p.pack_opaque(token)
                data = p.get_buffer()
            elif cred.service == rpc_gss_svc_privacy:
                p.pack_uint(cred.seq_num)
                data = p.get_buffer() + data
                wrap_res = context.wrap(data, encrypt=True)
                p.reset()
                p.pack_opaque(wrap_res.message)
                data = p.get_buffer()
            else:
                log_gss.error("Unknown service %i for RPCSEC_GSS" %
                              cred.service)
        except GSSError as e:
            log_gss.warning("secure_data: gssapi call returned %s" % str(e))
            raise
        return data

    def partially_packed_header(self, xid, body):
        p = RPCPacker()
        p.pack_uint(xid)
        p.pack_enum(CALL)
        p.pack_uint(body.rpcvers)
        p.pack_uint(body.prog)
        p.pack_uint(body.vers)
        p.pack_uint(body.proc)
        cred = opaque_auth(RPCSEC_GSS, self.pack_cred(body.cred.body))
        p.pack_opaque_auth(cred)
        return p.get_buffer()

    def make_call_verf(self, xid, body):
        if body.cred.body.gss_proc in (RPCSEC_GSS_INIT,
                                        RPCSEC_GSS_CONTINUE_INIT):
            return rpclib.NULL_CRED
        else:
            data = self.partially_packed_header(xid, body)
            token = self._get_context(
                body.cred.body.handle).get_signature(data)
            return opaque_auth(RPCSEC_GSS, token)

    def check_call_verf(self, xid, body):
        if body.cred.body.gss_proc in (RPCSEC_GSS_INIT,
                                        RPCSEC_GSS_CONTINUE_INIT):
            return self.is_NULL(body.verf)
        else:
            if body.verf.flavor != RPCSEC_GSS:
                return False
            data = self.partially_packed_header(xid, body)
            try:
                qop = self._get_context(
                    body.cred.body.handle).verify_signature(
                        data, body.verf.body)
            except GSSError as e:
                log_gss.warning(
                    "Verifier checksum failed verification with %s" % str(e))
                return False
            body.cred.body.qop = qop
            log_gss.debug("verifier checks out (qop=%i)" % qop)
            return True

    def check_auth(self, msg, data):
        def auth_error(code):
            raise rpclib.RPCDeniedReply(AUTH_ERROR, code)

        log_gss.debug("check_auth called with %r" % msg)
        if getattr(msg.cred, "opaque", True):
            log_gss.warning("XDR problem unpacking cred")
            log_gss.info("DENYing msg with AUTH_BADCRED")
            auth_error(AUTH_BADCRED)
        cred = msg.cred.body
        if cred.vers != RPCSEC_GSS_VERS_1:
            auth_error(AUTH_BADCRED)
        if cred.gss_proc != RPCSEC_GSS_DATA:
            if msg.proc != 0:
                auth_error(AUTH_BADCRED)
            getattr(self, "handle_gss_proc_%i" % cred.gss_proc)(
                msg.cred, data)
        context = self._get_context(cred.handle)
        if context is None:
            auth_error(RPCSEC_GSS_CREDPROBLEM)
        if context.expired():
            auth_error(RPCSEC_GSS_CTXPROBLEM)
        if not self.check_call_verf(msg.xid, msg.cbody):
            auth_error(RPCSEC_GSS_CREDPROBLEM)
        if cred.seq_num >= MAXSEQ:
            auth_error(RPCSEC_GSS_CTXPROBLEM)
        context.check_seqid(cred.seq_num)
        return CredInfo(self, cred.handle, service=cred.service,
                        gss_proc=cred.gss_proc, qop=0)

    def handle_gss_proc_1(self, cred, data):
        log_gss.info("Handling RPCSEC_GSS_INIT")
        self.handle_gss_init(cred, data, first=True)

    def handle_gss_proc_2(self, cred, data):
        log_gss.info("Handling RPCSEC_GSS_CONTINUE_INIT")
        self.handle_gss_init(cred, data, first=False)

    def handle_gss_init(self, cred, data, first):
        p = GSSUnpacker(data)
        token = p.unpack_opaque()
        p.done()
        log_gss.debug("***ACCEPTSECCONTEXT***")
        if first:
            context = gssapi.Context()
        else:
            context = self._get_context(cred.body.handle)
        try:
            token = context.accept(token)
        except GSSError as e:
            log_gss.debug("RPCSEC_GSS_INIT failed (%s, %i)!" %
                          (str(e), e.min_code))
            res = rpc_gss_init_res('', e.maj_code, e.min_code, 0, '')
        else:
            log_gss.debug("RPCSEC_GSS_*INIT succeeded!")
            if first:
                handle = self._add_context(context)
                cred.body.rpc_gss_cred_vers_1_t.handle = handle
            else:
                handle = cred.body.handle
            if context.open:
                major = GSS_S_COMPLETE
            else:
                major = GSS_S_CONTINUE_NEEDED
            res = rpc_gss_init_res(handle, major, 0, WINDOWSIZE, token)
        p = GSSPacker()
        p.pack_rpc_gss_init_res(res)
        verf = self.make_reply_verf(cred, major)
        raise rpclib.RPCSuccessfulReply(verf, p.get_buffer())

    def make_reply_verf(self, cred, stat):
        log_gss.debug("CALL:make_reply_verf(%r, %i)" % (cred, stat))
        cred = cred.body
        if stat:
            return rpclib.NULL_CRED
        elif cred.gss_proc in (RPCSEC_GSS_INIT, RPCSEC_GSS_CONTINUE_INIT):
            i = WINDOWSIZE
        else:
            i = cred.seq_num
        p = Packer()
        p.pack_uint(i)
        token = self._get_context(cred.handle).get_signature(p.get_buffer())
        return opaque_auth(RPCSEC_GSS, token)

    def check_reply_verf(self, msg, call_cred, data):
        if msg.stat != MSG_ACCEPTED:
            return
        verf = msg.rbody.areply.verf
        if msg.rbody.areply.reply_data.stat != SUCCESS:
            if not self.is_NULL(verf):
                raise SecError("Bad reply verifier - expected NULL verifier")
        elif call_cred.body.gss_proc in (RPCSEC_GSS_INIT,
                                          RPCSEC_GSS_CONTINUE_INIT):
            p = GSSUnpacker(data)
            try:
                res = p.unpack_rpc_gss_init_res()
                p.done()
            except Exception:
                log_gss.warning("Failure unpacking gss_init_res")
                raise SecError("Failure unpacking gss_init_res")
            if self.is_NULL(verf):
                if res.gss_major == GSS_S_COMPLETE:
                    raise SecError("Expected seq_window, got NULL")
            else:
                if res.gss_major != GSS_S_COMPLETE:
                    raise SecError("Expected NULL")
        else:
            p = Packer()
            p.pack_uint(call_cred.body.seq_num)
            qop = call_cred.context.verify_signature(
                p.get_buffer(), verf.body)
            if qop != call_cred.body.qop:
                raise SecError("Mismatched qop")


##############################################

supported = {
    AUTH_NONE: AuthNone,
    AUTH_SYS: AuthSys,
}

if gssapi is not None:
    supported[RPCSEC_GSS] = AuthGss


def klass(flavor):
    """Return the Auth class for the given flavor."""
    return supported[flavor]


def instances():
    """Return dict of {flavor: Auth instance} for all supported flavors."""
    return {flavor: auth() for flavor, auth in supported.items()}


def instance(flavor, *args, **kwargs):
    """Create and return an Auth instance for the given flavor."""
    return klass(flavor)(*args, **kwargs)
