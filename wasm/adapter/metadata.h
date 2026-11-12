// Session metadata: permission bits, owners, umask, symlink targets. Included only by adapter.c.
#ifndef ADAPTER_METADATA_H
#define ADAPTER_METADATA_H

#include "common.h"
#include "cwd.h"

// ---- what WASI has no place for: permission bits, owners, the umask and the original target of a symlink are
// session metadata kept here (like Pyodide's in-memory file system keeps them in its nodes), keyed by the file's
// (st_dev, st_ino): a hash table in one malloc'd block, its address in a wasm global. They live for the interpreter's
// lifetime and are not written to the host's file. A file with no record (it was there before the guest) gets the
// defaults of Pyodide (regular 0644, directory 0755, symlink 0777, the guest's root 0777).
// nrestrict counts the records whose mode forbids something (a file without read or write, a directory without read,
// write or search): while it is 0 no permission check is needed and the calls do not look at the modes at all.
typedef struct {
    u64 dev, ino;
    u32 mode, uid, gid;
    u8 used;    // 0 free, 1 live, 2 deleted
    u8 orphan;  // the file was unlinked while a descriptor of it is open: the record stays until the last close
    u8 isdir, restr;
    char *target;  // a symlink made with an absolute target: what the program stored (the link holds a relative one)
} Meta;
typedef struct {
    u32 cap, fill, live, umask, ntarget, nrestrict, norphan;
    u32 hasroot;
    u64 rdev, rino;  // the guest's root directory
    Meta *e;
} MetaT;
__asm__(".globaltype meta_state, i32\nmeta_state:\n");
static MetaT *mt(void) {
    MetaT *r;
    __asm__ volatile("global.get meta_state\n\tlocal.set %0" : "=r"(r));
    if (!r) {
        r = (MetaT *)calloc(1, sizeof(MetaT));
        r->umask = 022;
        u64 fs[8];
        if (!w_fd_filestat_get(PREOPEN, fs)) r->hasroot = 1, r->rdev = fs[0], r->rino = fs[1];
        __asm__ volatile("local.get %0\n\tglobal.set meta_state" : : "r"(r));
    }
    return r;
}
static u32 mhash(u64 dev, u64 ino) {
    u64 h = (dev * 0x9E3779B97F4A7C15ull) ^ (ino * 0xC2B2AE3D27D4EB4Full);
    h ^= h >> 29;
    return (u32)h;
}
static Meta *meta_find(u64 dev, u64 ino) {
    MetaT *t = mt();
    if (!t->cap) return 0;
    u32 m = t->cap - 1;
    for (u32 i = mhash(dev, ino) & m;; i = (i + 1) & m) {
        Meta *e = &t->e[i];
        if (e->used == 0) return 0;
        if (e->used == 1 && e->dev == dev && e->ino == ino) return e;
    }
}
static i32 meta_grow(MetaT *t) {  // rebuild without the deleted ones, at a size that keeps the load under a half; 0, or ENOMEM
    u32 nc = t->cap ? t->cap : 256;
    while (t->live * 2 >= nc) nc *= 2;
    Meta *ne = (Meta *)calloc(nc, sizeof(Meta));
    if (!ne) return ENOMEM;
    for (u32 j = 0; j < t->cap; j++) {
        Meta *o = &t->e[j];
        if (o->used != 1) continue;
        u32 i = mhash(o->dev, o->ino) & (nc - 1);
        while (ne[i].used) i = (i + 1) & (nc - 1);
        ne[i].dev = o->dev, ne[i].ino = o->ino, ne[i].mode = o->mode, ne[i].uid = o->uid, ne[i].gid = o->gid;
        ne[i].used = 1, ne[i].orphan = o->orphan, ne[i].isdir = o->isdir, ne[i].restr = o->restr, ne[i].target = o->target;
    }
    if (t->e) free(t->e);
    t->e = ne;
    t->cap = nc;
    t->fill = t->live;
    return 0;
}
static void meta_notarget(MetaT *t, Meta *e) {
    if (e->target) {
        free(e->target);
        e->target = 0;
        t->ntarget--;
    }
}
static void meta_setmode(MetaT *t, Meta *e, u32 mode) {
    e->mode = mode;
    u8 r = e->isdir ? (!(mode & 0444) || !(mode & 0222) || !(mode & 0111)) : (!(mode & 0444) || !(mode & 0222));
    t->nrestrict += (u32)r - (u32)e->restr;
    e->restr = r;
}
// a new or replaced record (no symlink target); 0 when out of memory
static Meta *meta_put(u64 dev, u64 ino, u32 mode, u32 uid, u32 gid, u8 ft) {
    MetaT *t = mt();
    Meta *e = meta_find(dev, ino);
    if (!e) {
        if ((t->fill + 1) * 2 > t->cap && meta_grow(t)) return 0;
        u32 m = t->cap - 1, i = mhash(dev, ino) & m;
        while (t->e[i].used == 1) i = (i + 1) & m;
        e = &t->e[i];
        if (e->used == 0) t->fill++;
        t->live++;
        e->used = 1;
        e->dev = dev;
        e->ino = ino;
        e->target = 0;
        e->restr = 0;
        e->orphan = 0;
    }
    if (e->orphan) e->orphan = 0, t->norphan--;
    meta_notarget(t, e);
    e->isdir = ft == 3;
    e->uid = uid, e->gid = gid;
    meta_setmode(t, e, mode);
    return e;
}
static void meta_del(u64 dev, u64 ino) {
    MetaT *t = mt();
    Meta *e = meta_find(dev, ino);
    if (!e) return;
    meta_notarget(t, e);
    if (e->orphan) t->norphan--;
    t->nrestrict -= e->restr;
    e->used = 2;
    t->live--;
}
static u32 def_mode(u8 ft) { return ft == 3 ? 0755 : ft == 7 || ft == 5 || ft == 6 ? 0777 : ft == 2 || ft == 1 ? 0666 : 0644; }
static u32 def_for(const u8 *fs) {  // the mode of a file with no record: Pyodide's defaults (its root directory is 0777)
    if (*(const u64 *)fs == VDEV) return *(const u32 *)(fs + 20);  // a virtual node (dev.h) carries its mode in the padding
    MetaT *t = mt();
    if (fs[16] == 3 && t->hasroot && *(const u64 *)fs == t->rdev && *(const u64 *)(fs + 8) == t->rino) return 0777;
    return def_mode(fs[16]);
}
static u32 type_bits(u8 ft) {  // S_IF* of a WASI filetype
    return ft == 3 ? 0040000 : ft == 7 ? 0120000 : ft == 2 ? 0020000 : ft == 1 ? 0060000 : ft == 5 || ft == 6 ? 0140000 : 0100000;
}
static Meta *meta_for(const u8 *fs) {  // the record of the file whose WASI filestat is fs, made from the defaults; 0: no memory
    u64 dev = *(const u64 *)fs, ino = *(const u64 *)(fs + 8);
    Meta *e = meta_find(dev, ino);
    return e ? e : meta_put(dev, ino, def_for(fs), 0, 0, fs[16]);
}
// a file made now: its record is the mode asked, without the umask (if there is no memory for it the file has the defaults)
static void meta_created(const u8 *fs, u32 mode, u32 keep) {
    meta_put(*(const u64 *)fs, *(const u64 *)(fs + 8), mode & ~mt()->umask & keep, 0, 0, fs[16]);
}
// an object that is about to disappear (the last name of a file, or a directory)? -> its (dev, ino) in key
static i32 meta_doomed(i32 fd, const char *p, i32 n, u64 *key) {
    u64 fs[8];
    if (!mt()->live || w_path_filestat_get(fd, 0, p, n, fs)) return 0;
    key[0] = fs[0], key[1] = fs[1];
    return *((u8 *)fs + 16) == 3 || fs[3] <= 1;
}
// May the name be made or removed in the directory that holds it? The directory's recorded mode needs write and search
// (Pyodide's mayCreate / mayDelete, whoever asks). kind 1: a name to make (if it exists the call says EEXIST), 0: a name to
// remove (if it is not there the call says ENOENT), 2: either (the destination of a rename). -> EACCES or 0
static i32 dir_denies(i32 fd, const char *p, i32 n, i32 kind) {
    if (!mt()->nrestrict) return 0;
    u64 fs[8];
    i32 missing = w_path_filestat_get(fd, 0, p, n, fs) != 0;
    if (kind != 2 && missing != kind) return 0;
    i32 e = n;
    while (e > 1 && p[e - 1] == '/') e--;
    i32 st = e;
    while (st > 0 && p[st - 1] != '/') st--;  // the last name starts here
    char dot[2];
    dot[0] = '.', dot[1] = 0;
    char *par = st ? dupn(p, (u32)st) : 0;
    if (st && !par) return ENOMEM;
    i32 err = w_path_filestat_get(fd, 1, par ? par : dot, st ? st : 1, fs);
    if (par) free(par);
    Meta *r = err ? 0 : meta_find(fs[0], fs[1]);
    return r && (!(r->mode & 0222) || !(r->mode & 0111)) ? FE_ACCES : 0;
}

#endif
