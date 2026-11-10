// The adapter's `net` operations (adapter.c, "sockets") over WASI 0.2 sockets, for the component build (-DNET_P2):
// the same nine functions that the Python host answers in the other builds. Blocking, IPv4 and IPv6 streams (TCP);
// no UDP, no listen/accept, no MSG_PEEK (WASI 0.2 has none). Same rules as adapter.c: no data section (-fno-jump-tables),
// no stack of its own, state in one block from the main module's calloc kept in a wasm global.
//
// Imports are the canonical-ABI lowering of wasi:sockets / wasi:io / wasi:clocks @0.2.12; the signatures and the layouts of
// the return areas were read from wit-bindgen's C output for these interfaces (wit-bindgen c, v0.63.0).
// Errors are returned as -errno in WASI's numbering (= Emscripten's), as the host's operations do.
typedef signed int i32;
typedef unsigned int u32;
typedef unsigned char u8;
typedef unsigned short u16;
typedef long long i64;
extern void *calloc(unsigned long, unsigned long);
extern void free(void *);

#define IMP(m, n) __attribute__((import_module(m), import_name(n)))
#define TCP "wasi:sockets/tcp@0.2.12"
#define STREAMS "wasi:io/streams@0.2.12"
#define POLL "wasi:io/poll@0.2.12"
#define NETWORK "wasi:sockets/network@0.2.12"
#define LOOKUP "wasi:sockets/ip-name-lookup@0.2.12"

IMP("wasi:sockets/tcp-create-socket@0.2.12", "create-tcp-socket") void w_create(i32 family, u8 *ret);
IMP("wasi:sockets/instance-network@0.2.12", "instance-network") i32 w_instance_network(void);
IMP(NETWORK, "[resource-drop]network") void w_drop_network(i32);
IMP(TCP, "[method]tcp-socket.start-connect") void w_start_connect(i32 self, i32 net, i32 tag, i32 a0, i32 a1, i32 a2, i32 a3, i32 a4, i32 a5, i32 a6, i32 a7, i32 a8, i32 a9, i32 a10, u8 *ret);
IMP(TCP, "[method]tcp-socket.finish-connect") void w_finish_connect(i32 self, u8 *ret);
IMP(TCP, "[method]tcp-socket.subscribe") i32 w_tcp_subscribe(i32 self);
IMP(TCP, "[method]tcp-socket.shutdown") void w_shutdown(i32 self, i32 how, u8 *ret);
IMP(TCP, "[method]tcp-socket.local-address") void w_local(i32 self, u8 *ret);
IMP(TCP, "[method]tcp-socket.remote-address") void w_remote(i32 self, u8 *ret);
IMP(TCP, "[resource-drop]tcp-socket") void w_drop_tcp(i32);
IMP(STREAMS, "[method]input-stream.blocking-read") void w_blocking_read(i32 self, i64 len, u8 *ret);
IMP(STREAMS, "[method]input-stream.subscribe") i32 w_in_subscribe(i32 self);
IMP(STREAMS, "[method]output-stream.blocking-write-and-flush") void w_blocking_write(i32 self, const u8 *p, unsigned long n, u8 *ret);
IMP(STREAMS, "[method]output-stream.subscribe") i32 w_out_subscribe(i32 self);
IMP(STREAMS, "[resource-drop]input-stream") void w_drop_in(i32);
IMP(STREAMS, "[resource-drop]output-stream") void w_drop_out(i32);
IMP("wasi:io/error@0.2.12", "[resource-drop]error") void w_drop_error(i32);
IMP(POLL, "poll") void w_poll(const u32 *list, unsigned long n, u8 *ret);
IMP(POLL, "[method]pollable.block") void w_block(i32 self);
IMP(POLL, "[resource-drop]pollable") void w_drop_pollable(i32);
IMP("wasi:clocks/monotonic-clock@0.2.12", "subscribe-duration") i32 w_subscribe_duration(i64 ns);
IMP(LOOKUP, "resolve-addresses") void w_resolve(i32 net, const char *name, unsigned long n, u8 *ret);
IMP(LOOKUP, "[method]resolve-address-stream.resolve-next-address") void w_next_address(i32 self, u8 *ret);
IMP(LOOKUP, "[method]resolve-address-stream.subscribe") i32 w_stream_subscribe(i32 self);
IMP(LOOKUP, "[resource-drop]resolve-address-stream") void w_drop_stream(i32);

// WASI errno numbers (= Emscripten's) of the codes used below
enum { E_ACCES = 2, E_ADDRINUSE = 3, E_ADDRNOTAVAIL = 4, E_AFNOSUPPORT = 5, E_AGAIN = 6, E_ALREADY = 7, E_CONNABORTED = 13,
       E_CONNREFUSED = 14, E_CONNRESET = 15, E_HOSTUNREACH = 23, E_INVAL = 28, E_IO = 29, E_MFILE = 33, E_MSGSIZE = 35,
       E_NOENT = 44, E_NOMEM = 48, E_NOTSUP = 58, E_PIPE = 64, E_PROTONOSUPPORT = 66, E_TIMEDOUT = 73 };

// wasi:sockets/network error-code -> -errno
static i32 err_of(u8 code) {
    switch (code) {
        case 1: return -E_ACCES;
        case 2: return -E_NOTSUP;
        case 3: return -E_INVAL;
        case 4: return -E_NOMEM;
        case 5: return -E_TIMEDOUT;
        case 6: return -E_ALREADY;
        case 7: return -E_INVAL;
        case 8: return -E_AGAIN;
        case 9: return -E_INVAL;
        case 10: return -E_MFILE;
        case 11: return -E_ADDRNOTAVAIL;
        case 12: return -E_ADDRINUSE;
        case 13: return -E_HOSTUNREACH;
        case 14: return -E_CONNREFUSED;
        case 15: return -E_CONNRESET;
        case 16: return -E_CONNABORTED;
        case 17: return -E_MSGSIZE;
        case 18: return -E_NOENT;       // name-unresolvable
        case 19: return -E_AGAIN;       // temporary-resolver-failure
        case 20: return -E_NOENT;       // permanent-resolver-failure
        default: return -E_IO;
    }
}

// a stream-error at ret[4] (0: last-operation-failed(error handle at ret[8]), 1: closed)
static i32 stream_err(const u8 *r, i32 closed_is) {
    if (r[4] == 1) return closed_is;
    w_drop_error(*(const i32 *)(r + 8));
    return -E_IO;
}

#define MAXS 64
typedef struct { i32 used, tcp, in, out; } Sock;
__asm__(".globaltype p2net_state, i32\np2net_state:\n");
static Sock *table(void) {
    Sock *r;
    __asm__ volatile("global.get p2net_state\n\tlocal.set %0" : "=r"(r));
    if (!r) {
        r = (Sock *)calloc(MAXS, sizeof(Sock));
        __asm__ volatile("local.get %0\n\tglobal.set p2net_state" : : "r"(r));
    }
    return r;
}
static Sock *sock(i32 h) { return h >= 0 && h < MAXS && table()[h].used ? &table()[h] : 0; }

i32 net_socket(i32 domain, i32 type, i32 proto) {
    (void)proto;
    if (type != 1) return -E_PROTONOSUPPORT;  // SOCK_STREAM only
    if (domain != 2 && domain != 10) return -E_AFNOSUPPORT;
    Sock *t = table();
    i32 h = -1;
    for (i32 k = 0; k < MAXS; k++)
        if (!t[k].used) { h = k; break; }
    if (h < 0) return -E_MFILE;
    u8 r[8] __attribute__((aligned(4)));
    w_create(domain == 10 ? 1 : 0, r);
    if (r[0]) return err_of(r[4]);
    t[h].used = 1;
    t[h].tcp = *(i32 *)(r + 4);
    t[h].in = t[h].out = 0;
    return h;
}

i32 net_connect(i32 h, i32 family, i32 port, const u8 *addr) {
    Sock *s = sock(h);
    if (!s) return -E_INVAL;
    i32 a[11] = {0};
    i32 tag;
    a[0] = port;
    if (family == 10) {
        tag = 1;  // ipv6: port, flow-info, 8 x u16, scope-id
        for (i32 k = 0; k < 8; k++) a[2 + k] = (addr[2 * k] << 8) | addr[2 * k + 1];
    } else {
        tag = 0;  // ipv4: port, 4 x u8
        for (i32 k = 0; k < 4; k++) a[1 + k] = addr[k];
    }
    i32 net = w_instance_network();
    u8 r[12] __attribute__((aligned(4)));
    w_start_connect(s->tcp, net, tag, a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7], a[8], a[9], a[10], r);
    w_drop_network(net);
    if (r[0]) return err_of(r[1]);
    for (;;) {
        w_finish_connect(s->tcp, r);
        if (!r[0]) {
            s->in = *(i32 *)(r + 4);
            s->out = *(i32 *)(r + 8);
            return 0;
        }
        if (r[4] != 8) return err_of(r[4]);  // anything but would-block
        i32 p = w_tcp_subscribe(s->tcp);
        w_block(p);
        w_drop_pollable(p);
    }
}

i32 net_send(i32 h, const u8 *p, i32 n) {
    Sock *s = sock(h);
    if (!s || !s->out) return -E_INVAL;
    if (n > 4096) n = 4096;  // blocking-write-and-flush takes at most 4096 bytes
    if (n <= 0) return 0;
    u8 r[12] __attribute__((aligned(4)));
    w_blocking_write(s->out, p, (unsigned long)n, r);
    if (r[0]) return stream_err(r, -E_PIPE);
    return n;
}

i32 net_recv(i32 h, u8 *p, i32 n, i32 peek) {
    Sock *s = sock(h);
    if (!s || !s->in) return -E_INVAL;
    if (peek) return -E_NOTSUP;  // WASI 0.2 has no MSG_PEEK
    if (n <= 0) return 0;
    u8 r[12] __attribute__((aligned(4)));
    w_blocking_read(s->in, (i64)n, r);
    if (r[0]) return stream_err(r, 0);  // closed: end of stream
    u8 *data = *(u8 **)(r + 4);
    i32 len = *(i32 *)(r + 8);
    for (i32 k = 0; k < len; k++) p[k] = data[k];
    free(data);  // the list was allocated by the module's cabi_realloc (malloc)
    return len;
}

i32 net_poll(i32 h, i32 events, i32 timeout_ms) {
    Sock *s = sock(h);
    if (!s) return 0;
    u32 ph[3];
    i32 kind[3];
    i32 n = 0;
    if ((events & 1) && s->in) { ph[n] = (u32)w_in_subscribe(s->in); kind[n++] = 1; }
    if ((events & 4) && s->out) { ph[n] = (u32)w_out_subscribe(s->out); kind[n++] = 4; }
    i32 nio = n;
    if (timeout_ms >= 0) { ph[n] = (u32)w_subscribe_duration((i64)timeout_ms * 1000000); kind[n++] = 0; }
    if (!n) return 0;
    u8 r[8] __attribute__((aligned(4)));
    w_poll(ph, (unsigned long)n, r);
    u32 *ready = *(u32 **)r;
    i32 cnt = *(i32 *)(r + 4);
    i32 rev = 0;
    for (i32 k = 0; k < cnt; k++)
        if (ready[k] < (u32)nio) rev |= kind[ready[k]];
    free(ready);
    for (i32 k = 0; k < n; k++) w_drop_pollable((i32)ph[k]);
    return rev;
}

i32 net_close(i32 h) {
    Sock *s = sock(h);
    if (!s) return 0;
    if (s->in) w_drop_in(s->in);
    if (s->out) w_drop_out(s->out);
    w_drop_tcp(s->tcp);
    s->used = 0;
    return 0;
}

i32 net_shutdown(i32 h, i32 how) {
    Sock *s = sock(h);
    if (!s) return -E_INVAL;
    u8 r[2] __attribute__((aligned(1)));
    w_shutdown(s->tcp, how, r);  // SHUT_RD, SHUT_WR, SHUT_RDWR = receive, send, both
    return r[0] ? err_of(r[1]) : 0;
}

i32 net_name(i32 h, i32 peer, u8 *addr4, i32 *port) {
    Sock *s = sock(h);
    if (!s) return -E_INVAL;
    u8 r[36] __attribute__((aligned(4)));
    if (peer) w_remote(s->tcp, r); else w_local(s->tcp, r);
    if (r[0]) return err_of(r[4]);
    *port = *(u16 *)(r + 8);
    for (i32 k = 0; k < 4; k++) addr4[k] = r[4] == 0 ? r[10 + k] : 0;  // IPv4 only, as the host's operation
    return 0;
}

i32 net_resolve(const char *name, i32 n, u8 *addr4) {
    i32 net = w_instance_network();
    u8 r[8] __attribute__((aligned(4)));
    w_resolve(net, name, (unsigned long)n, r);
    w_drop_network(net);
    if (r[0]) return err_of(r[4]);
    i32 st = *(i32 *)(r + 4);
    i32 res = -E_NOENT;
    for (;;) {
        u8 a[22] __attribute__((aligned(2)));
        w_next_address(st, a);
        if (a[0]) {
            if (a[2] != 8) { res = err_of(a[2]); break; }  // anything but would-block
            i32 p = w_stream_subscribe(st);
            w_block(p);
            w_drop_pollable(p);
            continue;
        }
        if (!a[2]) break;  // no more addresses
        if (a[4] == 0) {   // an IPv4 one (the host's operation gives IPv4 only)
            for (i32 k = 0; k < 4; k++) addr4[k] = a[6 + k];
            res = 0;
            break;
        }
    }
    w_drop_stream(st);
    return res;
}
