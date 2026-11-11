# type: ignore
# ruff: noqa
# fmt: off
for n, p in SAFE.items():
    op('unlink %s' % n, lambda: os.unlink(P(p)), True)
    op('rmdir %s' % n, lambda: os.rmdir(P(p)), True)
    op('mkdir %s' % n, lambda: os.mkdir(P(p), 0o750), True)
    op('mkdir mode %s' % n, lambda: (os.mkdir(P(p), 0o750), oct(stat.S_IMODE(os.stat(P(p)).st_mode)))[1])
    op('makedirs exist_ok %s' % n, lambda: os.makedirs(P(p), exist_ok=True))
    op('symlink to %s' % n, lambda: (os.symlink(P(p) if False else 'tgt', P(p)), os.readlink(P(p)))[1], True)
    op('symlink target=%s' % n, lambda: (os.symlink(p, B + '/newlink'), os.readlink(B + '/newlink').replace(B, 'B'))[1], True)
    op('link src=%s' % n, lambda: (os.link(P(p), B + '/newhard'), os.stat(B + '/newhard').st_nlink)[1], True)
    op('link follow src=%s' % n, lambda: (os.link(P(p), B + '/newhard', follow_symlinks=True), ty(os.lstat(B + '/newhard').st_mode))[1], True)
    op('link dst=%s' % n, lambda: os.link(B + '/f', P(p)), True)
