"""The `net` import module of the fused build as stubs that fail with ENOSYS (WASI's numbering): the WASI 0.2 experiment has no sockets yet."""

NAMES = (
    "SUCCESS 2BIG ACCES ADDRINUSE ADDRNOTAVAIL AFNOSUPPORT AGAIN ALREADY BADF BADMSG BUSY CANCELED CHILD CONNABORTED "
    "CONNREFUSED CONNRESET DEADLK DESTADDRREQ DOM DQUOT EXIST FAULT FBIG HOSTUNREACH IDRM ILSEQ INPROGRESS INTR INVAL "
    "IO ISCONN ISDIR LOOP MFILE MLINK MSGSIZE MULTIHOP NAMETOOLONG NETDOWN NETRESET NETUNREACH NFILE NOBUFS NODEV NOENT "
    "NOEXEC NOLCK NOLINK NOMEM NOMSG NOPROTOOPT NOSPC NOSYS"
).split()
ENOSYS = -NAMES.index("NOSYS")
PARAMS = {
    "socket": 3,
    "connect": 4,
    "send": 3,
    "recv": 4,
    "poll": 3,
    "close": 1,
    "shutdown": 2,
    "name": 4,
    "resolve": 3,
}

print("(module")
for name, n in PARAMS.items():
    print(f'  (func (export "{name}") {" ".join("(param i32)" for _ in range(n))} (result i32) (i32.const {ENOSYS}))')
print(")")
