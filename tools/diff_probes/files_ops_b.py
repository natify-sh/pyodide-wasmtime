# type: ignore
# ruff: noqa
# fmt: off
for n, p in SAFE.items():
    op('rename src=%s' % n, lambda: os.rename(P(p), B + '/renamed'), True)
    op('rename dst=%s (from f)' % n, lambda: os.rename(B + '/f', P(p)), True)
    op('rename dst=%s (from d)' % n, lambda: os.rename(B + '/d', P(p)), True)
    op('rename dst=%s (from emptyd)' % n, lambda: os.rename(B + '/emptyd', P(p)), True)
    op('rename dst=%s (from ln)' % n, lambda: os.rename(B + '/ln', P(p)), True)
    op('replace src=%s' % n, lambda: os.replace(P(p), B + '/f'), True)
    op('rename to-self %s' % n, lambda: os.rename(P(p), P(p)), True)
    op('rename to-sub %s' % n, lambda: os.rename(P(p), P(p) + '/sub'), True)

# rename specials
op('rename f -> existing ro', lambda: os.rename(B + '/f', B + '/ro'), True)
op('rename d -> existing emptyd', lambda: os.rename(B + '/d', B + '/emptyd'), True)
op('rename emptyd -> d (nonempty)', lambda: os.rename(B + '/emptyd', B + '/d'), True)
op('rename d -> d/sub', lambda: os.rename(B + '/d', B + '/d/sub'), True)
op('rename d -> d/x/y', lambda: os.rename(B + '/d', B + '/d/x/y'), True)
op('rename f -> f/x', lambda: os.rename(B + '/f', B + '/f/x'), True)
op('rename f -> hardlink of f', lambda: (os.link(B + '/f', B + '/f2'), os.rename(B + '/f', B + '/f2'))[1], True)
op('rename ln -> f (symlink over file)', lambda: os.rename(B + '/ln', B + '/f'), True)
op('rename f -> ln (file over symlink)', lambda: (os.rename(B + '/f', B + '/ln'), os.path.islink(B + '/ln'))[1], True)
op('rename d/ -> new/', lambda: os.rename(B + '/d/', B + '/new/'), True)
op('rename f/ -> new', lambda: os.rename(B + '/f/', B + '/new'), True)
op('rename f -> new/', lambda: os.rename(B + '/f', B + '/new/'), True)
op('rename keeps content', lambda: (os.rename(B + '/f', B + '/g'), open(B + '/g').read())[1])
op('rename keeps inode', lambda: (lambda i: (os.rename(B + '/f', B + '/g'), os.stat(B + '/g').st_ino == i)[1])(os.stat(B + '/f').st_ino))
op('rename dir keeps children', lambda: (os.rename(B + '/d', B + '/d2'), os.listdir(B + '/d2'))[1])
op('rename in dro', lambda: os.rename(B + '/dro', B + '/dro2'), True)
op('rename into dro', lambda: os.rename(B + '/f', B + '/dro/f'), True)
op('rename out of dro', lambda: (os.chmod(B + '/dro', 0o755), w(B + '/dro/x'), os.chmod(B + '/dro', 0o555), os.rename(B + '/dro/x', B + '/x'))[3], True)
op('unlink in dro', lambda: (os.chmod(B + '/dro', 0o755), w(B + '/dro/x'), os.chmod(B + '/dro', 0o555), os.unlink(B + '/dro/x'))[3], True)
op('unlink ro file', lambda: os.unlink(B + '/ro'), True)
