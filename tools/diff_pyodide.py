"""Differential audit: run one probe on the real Pyodide and on ours (fused and dynamic), print a diff per flavor.

usage: uv run python tools/diff_pyodide.py [-q] PROBE.py [PROBE2.py ...]
   PYO_RUN=path/to/pyo_run.sh (required: a script that runs a Python file in the real Pyodide on Node and prints its
   stdout and stderr)  PYO_TIMEOUT=seconds
A probe without its own `def case(` (or a "# standalone" comment) gets tools/diff_probes/_prelude.py
(case(), w(), tree(), NAMES, P(), fresh(), op()) put in front.
A probe prints one line per case: `case-id | result` (result a value or `ERR ERRNO_NAME`); use a fresh directory
B = '/tmp/dp_' + str(os.getpid()). Exit code 0 when no flavor differs from the Pyodide.
Normalised before comparing: the probe's own directory (any /tmp/dp_<digits> -> /tmp/dp_N), 0x addresses -> 0xADDR,
`<... at 0x...>` reprs, trailing spaces, the wasm engine's warning lines ("warning:" from uv). Nothing else: a probe
must not print inodes, devices, times or pids (print a derived boolean instead).
"""

import difflib
import os
import re
import subprocess
import sys
import tempfile

PYO_RUN = os.environ.get("PYO_RUN", "")
TIMEOUT = int(os.environ.get("PYO_TIMEOUT", "170"))


def normalise(text: str) -> list[str]:
    text = re.sub(r"/tmp/dp_\d+", "/tmp/dp_N", text)
    text = re.sub(r"0x[0-9a-fA-F]{4,}", "0xADDR", text)
    lines = [ln.rstrip() for ln in text.splitlines()]
    return [ln for ln in lines if not ln.startswith("warning:")]


def run(cmd: list[str]) -> list[str]:
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=TIMEOUT, errors="replace", stdin=subprocess.DEVNULL
        )
        out = p.stdout + p.stderr
        if p.returncode:
            out += f"\n[exit {p.returncode}]"
    except subprocess.TimeoutExpired:
        out = "[timeout]"
    return normalise(out)


def main() -> int:
    args = sys.argv[1:]
    quiet = "-q" in args
    probes = [a for a in args if not a.startswith("-")]
    status = 0
    for probe in probes:
        probe = os.path.abspath(probe)
        text = open(probe, encoding="utf-8").read()
        if "def case(" not in text and "# standalone" not in text:  # the probe uses the shared prelude
            tmp = os.path.join(tempfile.mkdtemp(), os.path.basename(probe))
            pre = open(os.path.join(os.path.dirname(probe), "_prelude.py"), encoding="utf-8").read()
            open(tmp, "w", encoding="utf-8").write(pre + text)
            probe = tmp
        if not PYO_RUN:
            raise SystemExit(
                "set PYO_RUN to a script that runs a Python file in the real Pyodide on Node (see the usage)"
            )
        real = run(["sh", PYO_RUN, probe])
        for flavor in ("fused", "dynamic"):
            ours = run([sys.executable, "-m", "pyodide_wasmtime", "--flavor", flavor, probe])
            diff = list(difflib.unified_diff(real, ours, "pyodide", flavor, lineterm="", n=0))
            n = sum(1 for d in diff if d[:1] in "+-" and d[:3] not in ("+++", "---")) // 2
            print(
                f"## {os.path.basename(probe)} {flavor}: {len(real)} pyodide lines, {len(ours)} ours, ~{n} differences"
            )
            if diff and not quiet:
                print("\n".join(diff))
            status |= bool(diff)
    return status


if __name__ == "__main__":
    sys.exit(main())
