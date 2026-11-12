"""Windows-only DIAGNOSTIC (BACKLOG D8): prints why a symlink made through __syscall_symlinkat fails on Windows.

It asserts nothing about symlink success: it collects one line per variant, prints them and appends them to
GITHUB_STEP_SUMMARY. Remove it when D8 is closed."""

from __future__ import annotations

import os
import platform
import sys
import tempfile
import warnings
from pathlib import Path

import pytest
from conftest import Guest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only diagnostic of BACKLOG D8")

# (name, target, link relative to the mount, target is a directory)
VARIANTS = [
    ("root-rel", "f", "l1", False),
    ("sub-rel", "f", "sub/l2", False),
    ("root-sub/f", "sub/f", "l3", False),
    ("sub-up", "../f", "sub/l4", False),
    ("abs-root", "/mnt/h/f", "l5", False),
    ("abs-sub", "/mnt/h/f", "sub/l6", False),
    ("dir-root-rel", "d", "ld1", True),
    ("dir-sub-rel", "d", "sub/ld2", True),
    ("dir-sub-up", "../d", "sub/ld3", True),
    ("dir-abs", "/mnt/h/d", "ld4", True),
]

GUEST = """
import os, errno
def e(f, *a):
    try:
        r = f(*a)
    except OSError as x:
        return "ERR " + errno.errorcode.get(x.errno, str(x.errno))
    return "ok" if r is None else repr(r)
for name, target, link in {variants!r}:
    print("V", name, "symlink=" + e(os.symlink, target, "/mnt/h/" + link),
          "readlink=" + e(os.readlink, "/mnt/h/" + link), "exists=" + e(os.path.exists, "/mnt/h/" + link))
"""


def host_side(base: Path) -> list[str]:
    out = []
    for kind in ("file", "dir"):
        for form in ("rel", "abs"):
            tgt = base / f"t_{kind}"
            tgt.mkdir(exist_ok=True) if kind == "dir" else tgt.write_bytes(b"x")
            link = base / f"hl_{kind}_{form}"
            try:
                os.symlink(tgt if form == "abs" else tgt.name, link, target_is_directory=kind == "dir")
                r = "ok " + os.readlink(link)
            except OSError as x:
                r = f"ERR errno={x.errno} winerror={getattr(x, 'winerror', None)} {x.strerror}"
            out.append(f"HOST os.symlink {kind} {form}: {r}")
    return out


def host_link(base: Path, link: str) -> str:
    p = base / link
    try:
        return (
            f"host islink={p.is_symlink()} raw={os.readlink(p)!r}"
            if p.is_symlink()
            else f"host islink=False exists={p.exists()}"
        )
    except OSError as x:
        return f"host ERR {x}"


def test_windows_symlink_diagnostic(guest: Guest) -> None:
    from importlib.metadata import version

    lines = [f"## symlink diag [{guest.flavor}] {platform.platform()} wasmtime {version('wasmtime')}"]
    with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
        lines += host_side(Path(t1))
        base = Path(t2)
        (base / "sub" / "d").mkdir(parents=True)
        (base / "d").mkdir()
        (base / "f").write_bytes(b"x")
        (base / "sub" / "f").write_bytes(b"x")
        p = guest.run(GUEST.replace("{variants!r}", repr([v[:3] for v in VARIANTS])), None, "--mount", f"/mnt/h={base}")
        lines.append(f"guest returncode={p.returncode}")
        lines += [
            ln + " " + host_link(base, v[2])
            for ln, v in zip([x for x in p.stdout.splitlines() if x.startswith("V ")], VARIANTS, strict=False)
        ]
        if p.returncode:
            lines.append("guest stderr: " + p.stderr[-800:].replace("\n", " | "))
    text = "\n".join(lines)
    warnings.warn("symlink diagnostic:\n" + text, stacklevel=1)  # xdist forwards warnings into the CI log, not stdout
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("```\n" + text + "\n```\n")
