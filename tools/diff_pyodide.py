# ruff: noqa: E501, UP031
"""Differential audit: run one probe on the real Pyodide (Node) and on ours (fused, dynamic); print a diff per flavor.

Usage (from the repository root, with the data built):
    uv run python tools/diff_pyodide.py [--tz TZ] [--site DIR] [--flavors fused,dynamic] [--ours-arg=ARG ...]
        [--isolate] [--jobs N] [--keep DIR] PROBE.py [PROBE.py ...]
    PYODIDE_DIST=<folder with pyodide.mjs> (default: pyo-build/dl/dist of this repository, made by tools/fetch.sh), $KEEP=1 keeps the outputs.
    The folder PYODIDE_DIST is visible in both guests as /dist (NODEFS on Pyodide, --mount on ours): wheels are read from there.

Each probe set has its own prelude (tools/diff_probes/), put in front of the probe, chosen by the probe's file name prefix or by a
first-line marker `# prelude: NAME` (_prelude_NAME.py): `files_*` -> files (case, w, tree(): only for a file with no `def case(` and no
`# standalone`), `io_*`/`loader_*`/`mmap_*` -> io (the fresh directory B, case(id, fn), and the side modules of _sides.py written to
B/so/), `runtime_*` -> none. `--isolate`, or a line `# isolate` at the top of an io probe, runs every case of it in a fresh interpreter
(3 targets x N cases, 60 s each, --jobs at a time; a case that dies is `id | CRASH`): for cases that leave state in the loader or kill
the guest. --keep DIR keeps the raw outputs in DIR. --ours-arg=ARG passes ARG to pyodide_nojs (e.g. --ours-arg=--dev).

A probe is a Python file that prints one line per case: `case-id | result` (`ERR errno-name` for an OSError).
A file may hold several programs, each run in a fresh interpreter: a line `# --- name` starts a program
(needed for exit/abort probes). A case that kills the guest is reported as `case-id | DEAD` and the program restarts after it (c() in the probes).
Every run ends with a line `EXIT-STATUS n`: ours is the process return code; for
Pyodide it is read from what Node's runPython throws (ExitStatus n -> n, SystemExit: n -> n, any other Python
exception -> 1 (both sides' tracebacks are cut to `TRACEBACK last-line`), a wasm trap a wasm trap (WebAssembly.RuntimeError) -> 134, no exception -> 0). Stdout and stderr are merged, stderr is
not separated. TZ (the process environment) is the same for all runs.
--site DIR: a folder with packages, copied into site-packages for ours and mounted (NODEFS) on /site on sys.path
for Pyodide.

Normalised before the diff: a trap (both sides' reports, also a failed host function of ours) -> TRAP, a refused proc_exit -> HOSTFAIL <reason>, the probe's temp directory (/tmp/dp_<digits> -> <B>), `<string>:12:`/`<exec>:12:` of a warning, a traceback to `TRACEBACK last-line`, hex addresses (0x + 5 or more
hex digits -> 0xADDR), trailing spaces, the CR of a CRLF. Exit code of this script: 0 if there is no difference.
"""

import concurrent.futures
import difflib
import os
import re
import signal
import subprocess
import sys
import tempfile

# the folder tools/fetch.sh makes (WORKDIR/dl/dist: Pyodide's release with pyodide.mjs); node and the npm package are build tools
DIST = os.environ.get("PYODIDE_DIST") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pyo-build", "dl", "dist"
)

MJS = """
import { loadPyodide } from "%(dist)s/pyodide.mjs";
import fs from "node:fs";
const out = (s) => console.log(s);
const py = await loadPyodide({ indexURL: "%(dist)s", stdout: out, stderr: out });
if (process.env.PYO_SITE) {
  py.FS.mkdir("/site");
  py.FS.mount(py.FS.filesystems.NODEFS, { root: process.env.PYO_SITE }, "/site");
  py.runPython("import sys; sys.path.append('/site')");
}
py.FS.mkdir("/dist");
py.FS.mount(py.FS.filesystems.NODEFS, { root: "%(dist)s" }, "/dist");
let st = 0;
try { py.runPython(fs.readFileSync(process.argv[2], "utf8")); }
catch (e) {
  if (e && e.name === "Exit") st = e.status & 255;
  else if (e && e.name === "PythonError") {
    // what `python file.py` would do with an uncaught exception: SystemExit(int) -> status, SystemExit(other) -> its text on stderr, 1
    const last = String(e.message).trim().split("\\n").pop();
    const m = /^SystemExit(?:: (.*))?$/.exec(last);
    if (!m) { st = 1; out("Traceback (most recent call last):\\n  File x\\n" + last); }
    else if (m[1] === undefined || m[1] === "None") st = 0;
    else if (/^-?\\d+$/.test(m[1])) { const n = BigInt(m[1]); st = (n > 2n ** 63n - 1n || n < -(2n ** 63n)) ? 255 : Number(BigInt.asUintN(8, n)); }
    else { st = 1; out(m[1]); }
  } else if (e && (e.pyodide_fatal_error || e instanceof WebAssembly.RuntimeError)) st = 134;
  else { st = 99; out("JSERROR " + e); }
}
out("EXIT-STATUS " + st);
"""

NORM = [
    (re.compile(r"<(?:exec|string)>:\d+:"), "<src>:N:"),
    (re.compile(r"/tmp/dp_\d+"), "<B>"),
    (re.compile(r"0x[0-9a-fA-F]{5,}"), "0xADDR"),
    (re.compile(r"[ \r]+$"), ""),
]
NORM_IO = [  # io probes only: process ids, inode numbers, times
    (re.compile(r"\bpid[ =]\d+"), "pid N"),
    (re.compile(r"\b(inode|ino)[ =:]+\d+"), r"\1 N"),
    (re.compile(r"\d+\.\d+s\b"), "<T>"),
]


SQUASH = [  # a trap is reported differently by the two (Pyodide's fatal error with a JS stack, ours with a wasm backtrace)
    (re.compile(r"Pyodide has suffered a fatal error.*?(?=EXIT-STATUS)", re.S), "TRAP\n"),
    (re.compile(r"pyodide-nojs: the guest trapped:.*?(?=EXIT-STATUS)", re.S), "TRAP\n"),
    (
        re.compile(
            r"pyodide-nojs: a host function failed, the guest is dead: .*?Caused by:\s*(.*?)\n \(at[^\n]*\n", re.S
        ),
        r"HOSTFAIL \1\n",
    ),
    (
        re.compile(r"pyodide-nojs: a host function failed, the guest is dead: ([^\n]*?)( \(at [^\n]*\))?\n"),
        "TRAP\n",
    ),
]


def squash(text):
    for rx, rep in SQUASH:
        text = rx.sub(rep, text)
    return text


def norm(text, io=False):
    text = re.sub(r"Traceback \(most recent call last\):\n(?:  .*\n)+", "TRACEBACK ", text)
    lines = []
    for line in text.splitlines():
        for rx, rep in NORM + (NORM_IO if io else []):
            line = rx.sub(rep, line)
        lines.append(line)
    return lines


def prelude_kind(path, src):
    """files, io or None: by a first-line marker `# prelude: NAME`, else by the file name prefix."""
    m = re.match(r"# prelude: (\w+)", src)
    if m:
        return m.group(1) if m.group(1) != "none" else None
    name = os.path.basename(path)
    if name.startswith("files_"):
        return "files"
    if name.startswith(("io_", "loader_", "mmap_")):
        return "io"
    return None


def programs(path):
    src = open(path, encoding="utf8").read()
    here = os.path.dirname(os.path.abspath(path))
    kind = prelude_kind(path, src)
    if kind == "files":
        if "def case(" not in src and "# standalone" not in src:  # the matrix probes of the files area
            src = open(os.path.join(here, "_prelude_files.py"), encoding="utf8").read() + src
    elif kind:
        pre = open(os.path.join(here, "_prelude_%s.py" % kind), encoding="utf8").read()
        if kind == "io":
            sys.path.insert(0, here)
            import _sides  # type: ignore[import-not-found]

            sides = {n: b.hex() for n, b in _sides.build().items()}
            pre = "SIDES = %r\nONLY = None\n" % sides + pre
        src = pre + "\n" + src
    parts = re.split(r"^# ?--- (.*)$", src, flags=re.M)
    if len(parts) == 1:
        return [(os.path.basename(path), src)]
    return [(parts[i], parts[i + 1]) for i in range(1, len(parts), 2)]


def run(cmd, env, cwd, status=False, timeout=None):
    """Output through a file, so that a timeout ($DIFF_TIMEOUT, 170 s: "TIMEOUT") keeps what was printed."""
    with tempfile.TemporaryFile("w+", encoding="utf8", errors="replace") as out:
        proc = subprocess.Popen(
            cmd,
            env=env,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            rc = proc.wait(timeout or float(os.environ.get("DIFF_TIMEOUT", 170)))
            tail = "EXIT-STATUS %d\n" % rc if status else ""
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            tail = "TIMEOUT\n"
        out.seek(0)
        return out.read() + tail


def run_pyodide(code, work, env, site, timeout=None):
    f = os.path.join(work, "p.py")
    open(f, "w", encoding="utf8").write(code)
    m = os.path.join(work, "r.mjs")
    open(m, "w").write(MJS % {"dist": DIST})
    e = dict(env, **({"PYO_SITE": site} if site else {}))
    return run(["node", m, f], e, DIST, timeout=timeout)


def run_ours(code, work, env, flavor, site, extra=(), timeout=None):
    f = os.path.join(work, "p.py")
    open(f, "w", encoding="utf8").write(code)
    cmd = [sys.executable, "-m", "pyodide_nojs", "--flavor", flavor, "--mount", "/dist=" + DIST, *extra]
    if site:
        cmd += ["--site", site]
    return run(cmd + [f], env, None, True, timeout)


def resumable(runner, code):
    """A probe whose cases print `>> case-id` before they run (see c() in the probes): a case that kills the guest is
    reported as `case-id | DEAD` and the program is started again, skipping the cases done (SKIP = n)."""
    final, skip = [], 0
    for _ in range(60):
        text = squash(runner("SKIP = %d\n" % skip + code if skip else code))
        lines, pending, at, count = text.splitlines(), None, 0, 0
        for line in lines:
            if line.startswith(">> "):
                pending, at, count = line[3:], len(final), count + 1
            elif pending is not None and line.startswith(pending + " | "):
                pending = None
                final.append(line)
            else:
                final.append(line)
        if pending is None or ">> " not in text:
            break
        final.insert(at, pending + " | DEAD")
        final = [x for x in final if not x.startswith("EXIT-STATUS")]
        skip += count
    return "\n".join(final) + "\n"


def settle(cid, out):
    """One isolated case: its case line(s), or `id | CRASH` when the run died before the case line."""
    lines = [x for x in squash(out).splitlines() if not x.startswith("EXIT-STATUS") and x != "TRAP"]
    at = [i for i, x in enumerate(lines) if x.startswith(cid + " | ")]
    if at:  # what the case printed before its line is kept, what comes after (a callback that dies later) is not
        return "\n".join(lines[: at[-1] + 1])
    return "%s | CRASH" % cid


def isolated(code, work, env, targets, jobs, runner):
    """Run every case of an io probe alone: ONLY = -1 lists the case ids, ONLY = k runs the k-th."""

    def one(target, k):
        return runner(
            target, code.replace("ONLY = None\n", "ONLY = %d\n" % k, 1), os.path.join(work, "%s%d" % (target[:2], k))
        )

    ids = [x.split(" | ")[0] for x in one("pyodide", -1).splitlines() if x.endswith(" | dry")]
    with concurrent.futures.ThreadPoolExecutor(jobs) as ex:
        futs = {t: [ex.submit(one, t, i) for i in range(len(ids))] for t in targets}
        return {t: "\n".join(settle(ids[i], f.result()) for i, f in enumerate(fs)) for t, fs in futs.items()}


def main(argv):
    flavors, site, tz, files = ["fused", "dynamic"], None, None, []
    extra, isolate, jobs, keep = [], False, 3, os.environ.get("KEEP_DIR")
    it = iter(argv)
    for a in it:
        if a == "--tz":
            tz = next(it)
        elif a == "--site":
            site = next(it)
        elif a == "--flavors":
            flavors = next(it).split(",")
        elif a.startswith("--ours-arg="):
            extra.append(a.split("=", 1)[1])
        elif a == "--isolate":
            isolate = True
        elif a == "--jobs":
            jobs = int(next(it))
        elif a == "--keep":
            keep = next(it)
        else:
            files.append(a)
    env = dict(os.environ)
    if tz:
        env["TZ"] = tz
    bad = 0
    for path in files:
        for name, code in programs(path):
            io = prelude_kind(path, code) == "io" or "SIDES = " in code[:20]
            iso = io and (isolate or "\n# isolate\n" in code)
            with tempfile.TemporaryDirectory(prefix="dpw_") as work:
                if iso:

                    def runner(target, c, w):
                        os.makedirs(w, exist_ok=True)
                        if target == "pyodide":
                            return run_pyodide(c, w, env, site, 60)
                        return run_ours(c, w, env, target, site, extra, 60)

                    raw = isolated(code, work, env, ["pyodide", *flavors], jobs, runner)
                    ref, outs = norm(raw["pyodide"], io), {fl: norm(raw[fl], io) for fl in flavors}
                else:
                    ref = norm(resumable(lambda c: run_pyodide(c, work, env, site), code), io)
                    outs = {
                        fl: norm(resumable(lambda c, fl=fl: run_ours(c, work, env, fl, site, extra), code), io)
                        for fl in flavors
                    }
                for fl in flavors:
                    got = outs[fl]
                    d = list(difflib.unified_diff(ref, got, "pyodide", fl, lineterm="", n=0))
                    n = sum(1 for x in d if x[:1] in "+-" and x[:3] not in ("+++", "---"))
                    print("### %s :: %s :: %s: %d cases (pyodide), %d differing lines" % (path, name, fl, len(ref), n))
                    if d:
                        bad += 1
                        print("\n".join(d))
                    if os.environ.get("KEEP"):
                        open("%s.%s.%s.out" % (path, name, fl), "w").write("\n".join(got))
                    if keep:
                        open(
                            os.path.join(keep, "%s.%s" % (os.path.splitext(os.path.basename(path))[0], fl)), "w"
                        ).write("\n".join(got))
                if os.environ.get("KEEP"):
                    open("%s.%s.pyodide.out" % (path, name), "w").write("\n".join(ref))
                if keep:
                    open(os.path.join(keep, "%s.pyodide" % os.path.splitext(os.path.basename(path))[0]), "w").write(
                        "\n".join(ref)
                    )
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
