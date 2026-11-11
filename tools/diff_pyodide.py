# ruff: noqa: E501, UP031
"""Differential audit: run one probe on the real Pyodide (Node) and on ours (fused, dynamic); print a diff per flavor.

Usage (from the repository root, with the data built):
    uv run python tools/diff_pyodide.py [--tz TZ] [--site DIR] [--flavors fused,dynamic] PROBE.py [PROBE.py ...]
    PYODIDE_DIST=<folder with pyodide.mjs> (default: work/dl/dist of this repository, made by tools/fetch.sh), $KEEP=1 keeps the outputs.

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

import difflib
import os
import re
import signal
import subprocess
import sys
import tempfile

# the folder tools/fetch.sh makes (WORKDIR/dl/dist: Pyodide's release with pyodide.mjs); node and the npm package are build tools
DIST = os.environ.get("PYODIDE_DIST") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "work", "dl", "dist"
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


SQUASH = [  # a trap is reported differently by the two (Pyodide's fatal error with a JS stack, ours with a wasm backtrace)
    (re.compile(r"Pyodide has suffered a fatal error.*?(?=EXIT-STATUS)", re.S), "TRAP\n"),
    (re.compile(r"pyodide-wasmtime: the guest trapped:.*?(?=EXIT-STATUS)", re.S), "TRAP\n"),
    (
        re.compile(
            r"pyodide-wasmtime: a host function failed, the guest is dead: .*?Caused by:\s*(.*?)\n \(at[^\n]*\n", re.S
        ),
        r"HOSTFAIL \1\n",
    ),
    (
        re.compile(r"pyodide-wasmtime: a host function failed, the guest is dead: ([^\n]*?)( \(at [^\n]*\))?\n"),
        "TRAP\n",
    ),
]


def squash(text):
    for rx, rep in SQUASH:
        text = rx.sub(rep, text)
    return text


def norm(text):
    text = re.sub(r"Traceback \(most recent call last\):\n(?:  .*\n)+", "TRACEBACK ", text)
    lines = []
    for line in text.splitlines():
        for rx, rep in NORM:
            line = rx.sub(rep, line)
        lines.append(line)
    return lines


def programs(path):
    src = open(path, encoding="utf8").read()
    prelude = os.path.join(os.path.dirname(os.path.abspath(path)), "_prelude.py")
    if (
        "def case(" not in src and "# standalone" not in src and os.path.exists(prelude)
    ):  # the matrix probes of the files area
        src = open(prelude, encoding="utf8").read() + src
    parts = re.split(r"^# ?--- (.*)$", src, flags=re.M)
    if len(parts) == 1:
        return [(os.path.basename(path), src)]
    return [(parts[i], parts[i + 1]) for i in range(1, len(parts), 2)]


def run(cmd, env, cwd, status=False):
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
            rc = proc.wait(float(os.environ.get("DIFF_TIMEOUT", 170)))
            tail = "EXIT-STATUS %d\n" % rc if status else ""
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            tail = "TIMEOUT\n"
        out.seek(0)
        return out.read() + tail


def run_pyodide(code, work, env, site):
    f = os.path.join(work, "p.py")
    open(f, "w", encoding="utf8").write(code)
    m = os.path.join(work, "r.mjs")
    open(m, "w").write(MJS % {"dist": DIST})
    e = dict(env, **({"PYO_SITE": site} if site else {}))
    return run(["node", m, f], e, DIST)


def run_ours(code, work, env, flavor, site):
    f = os.path.join(work, "p.py")
    open(f, "w", encoding="utf8").write(code)
    cmd = [sys.executable, "-m", "pyodide_wasmtime", "--flavor", flavor]
    if site:
        cmd += ["--site", site]
    return run(cmd + [f], env, None, True)


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


def main(argv):
    flavors, site, tz, files = ["fused", "dynamic"], None, None, []
    it = iter(argv)
    for a in it:
        if a == "--tz":
            tz = next(it)
        elif a == "--site":
            site = next(it)
        elif a == "--flavors":
            flavors = next(it).split(",")
        else:
            files.append(a)
    env = dict(os.environ)
    if tz:
        env["TZ"] = tz
    bad = 0
    for path in files:
        for name, code in programs(path):
            with tempfile.TemporaryDirectory(prefix="dpw_") as work:
                ref = norm(resumable(lambda c: run_pyodide(c, work, env, site), code))
                for fl in flavors:
                    got = norm(resumable(lambda c, fl=fl: run_ours(c, work, env, fl, site), code))
                    d = list(difflib.unified_diff(ref, got, "pyodide", fl, lineterm="", n=0))
                    n = sum(1 for x in d if x[:1] in "+-" and x[:3] not in ("+++", "---"))
                    print("### %s :: %s :: %s: %d cases (pyodide), %d differing lines" % (path, name, fl, len(ref), n))
                    if d:
                        bad += 1
                        print("\n".join(d))
                    if os.environ.get("KEEP"):
                        open("%s.%s.%s.out" % (path, name, fl), "w").write("\n".join(got))
                if os.environ.get("KEEP"):
                    open("%s.%s.pyodide.out" % (path, name), "w").write("\n".join(ref))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
