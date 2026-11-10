"""What each `env` import of pyodide.asm.wasm is in Pyodide's own JavaScript, from its source.

    python tools/audit_imports.py PYODIDE_NPM_PACKAGE_DIR [PYODIDE.ASM.WASM]    # a table; --json for the data

For each function import of the main module: its signature (from the module), the JavaScript function that answers it in
`pyodide.asm.mjs` (found through the `wasmImports` object), the size of that function and the names of the JavaScript
facilities it touches. The facilities say what kind of import it is, from the source and not from the name:
the bridge to JavaScript objects (`Hiwire`, `API`, `JsProxy`...), the file system and system calls (`FS`, `SYSCALLS`),
the dynamic loader, time, and so on. The audit of what *this* package does with each is docs/import_audit.json,
checked against this list by tests/test_import_audit.py.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

KINDS = [  # (kind, tokens of the JavaScript source that make it that kind), first match wins
    (
        "js-bridge",
        ("Hiwire", "API.", "JsProxy", "PyProxy", "pyproxy", "Module.pyodide", "globalThis", "Promise", "suspender"),
    ),
    ("dynamic-loader", ("loadDynamicLibrary", "LDSO", "loadWebAssemblyModule", "dlopen", "wasmTable.grow")),
    ("filesystem", ("FS.", "SYSCALLS", "PATH.", "PIPEFS", "SOCKFS", "TTY.")),
    ("time", ("Date.now", "performance", "getTimezoneOffset", "localtime", "tzset")),
    ("runtime", ("abort(", "runtimeKeepalive", "stackSave", "growMemory", "HEAP8", "wasmMemory")),
]


def wasm_imports(wasm: Path) -> list[tuple[str, list[str], list[str]]]:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from pyodide_wasmtime import _engine, _wasm

    module = _engine.load_module(wasm)
    return [(n, ps, rs) for mod, n, ps, rs in _wasm.func_imports(module) if mod == "env"]


def import_map(js: str) -> dict[str, str]:
    """wasmImports={a:_a,b,...}: env name -> the identifier of the JavaScript function (shorthand: the same name)."""
    start = js.index("wasmImports={") + len("wasmImports={")
    depth, i = 1, start
    while depth:
        c = js[i]
        depth += (c == "{") - (c == "}")
        i += 1
    out = {}
    for item in re.split(r",(?![^()\[\]{}]*[)\]}])", js[start : i - 1]):
        name, _, ident = item.partition(":")
        out[name.strip()] = (ident or name).strip()
    return out


def function_source(js: str, ident: str) -> str | None:
    """The source of `function ident(...){...}` or `ident=(...)=>{...}`/`var ident=...`, by bracket matching."""
    for pat in (
        rf"function {re.escape(ident)}\(",
        rf"(?:var |,|;|\n){re.escape(ident)}=(?:async )?(?:function\b|\(|[\w$]+=>)",
    ):
        m = re.search(pat, js)
        if m:
            i = js.index("{", m.start()) if "{" in js[m.start() : m.start() + 400] else m.start()
            depth, j = 0, i
            while j < len(js):
                c = js[j]
                depth += (c == "{") - (c == "}")
                j += 1
                if depth == 0:
                    break
            return js[m.start() : j]
    return None


def kind_of(src: str | None) -> tuple[str, list[str]]:
    if src is None:
        return "no-js-source", []
    touches = sorted({t for _, toks in KINDS for t in toks if t in src})
    for kind, toks in KINDS:
        if any(t in src for t in toks):
            return kind, touches
    return ("trivial" if len(src) < 120 else "other"), touches


def audit(package_dir: Path, wasm: Path) -> list[dict]:
    js = (package_dir / "pyodide.asm.mjs").read_text()
    mapping = import_map(js)
    rows = []
    for name, ps, rs in wasm_imports(wasm):
        ident = mapping.get(name)
        src = function_source(js, ident) if ident else None
        kind, touches = kind_of(src)
        rows.append(
            {
                "name": name,
                "params": ps,
                "results": rs,
                "js": ident,
                "js_size": len(src) if src else 0,
                "kind": kind,
                "touches": touches,
            }
        )
    return rows


if __name__ == "__main__" and "--markdown" not in sys.argv:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    package = Path(args[0])
    # the npm module has the legacy exceptions that wasmtime refuses to compile; the converted one has the same imports
    wasm = (
        Path(args[1])
        if len(args) > 1
        else Path(__file__).resolve().parent.parent / "src/pyodide_wasmtime/data/pyodide.asm.wasm"
    )
    rows = audit(package, wasm)
    if "--json" in sys.argv:
        print(json.dumps(rows, indent=1))
    else:
        counts: dict[str, int] = {}
        for r in rows:
            counts[r["kind"]] = counts.get(r["kind"], 0) + 1
        print(len(rows), "env imports:", counts)
        for r in rows:
            print(f"{r['kind']:15} {r['name']:44} js={r['js_size']:5}  {','.join(r['touches'])}")


# ---------------------------------------------------------------------------------------------------------------------
# The audit file: docs/import_audit.json, one entry per `env` import, and its rendering as docs/IMPORT_AUDIT.md.
#   entry: {"name", "class", "verdict", "gaps": [...], "evidence", "tested"}
#   class:   js-value (a JavaScript value in the signature) | js-bridge (JavaScript in the body, no value in the signature)
#            | os (system calls, files, sockets) | runtime (loader, ffi, memory, exit, time) | hook (a JavaScript-side hook)
#   verdict: full | partial | enosys | stub | n/a        (tests/test_import_audit.py holds the file to the built adapter)
VERDICTS = ("full", "partial", "enosys", "stub", "n/a")


def render_markdown(entries: list[dict]) -> str:
    counts: dict[str, int] = {}
    for e in entries:
        counts[e["verdict"]] = counts.get(e["verdict"], 0) + 1
    out = [
        "# The `env` imports of pyodide.asm.wasm: what this package does with each",
        "",
        "Generated by `python tools/audit_imports.py PYODIDE_NPM_DIR --markdown` from `docs/import_audit.json`; the file is held to the built",
        "adapter by `tests/test_import_audit.py`. `class` is read from Pyodide's own JavaScript and from the signature",
        "(`js-value`: a JavaScript value, `externref`, crosses the boundary), not from the name.",
        "",
        "| verdict | meaning | imports |",
        "|---|---|---|",
        f"| full | the same observable behaviour as Pyodide's JavaScript | {counts.get('full', 0)} |",
        f"| partial | implemented, with the gaps listed | {counts.get('partial', 0)} |",
        f"| enosys | answered with ENOSYS | {counts.get('enosys', 0)} |",
        f"| stub | answered with 0/null and does nothing | {counts.get('stub', 0)} |",
        f"| n/a | has no meaning without JavaScript | {counts.get('n/a', 0)} |",
        f"| | total | {len(entries)} |",
        "",
    ]
    for cls in ("os", "runtime", "hook", "js-bridge", "js-value"):
        group = [e for e in entries if e["class"] == cls]
        if not group:
            continue
        out += [f"## {cls} ({len(group)})", ""]
        if cls == "js-value":
            out += [
                "All of these take or return a JavaScript value; none is answered, by design: "
                + ", ".join(f"`{e['name']}`" for e in group),
                "",
            ]
            continue
        out += ["| import | verdict | gaps | evidence | tested |", "|---|---|---|---|---|"]
        for e in group:
            gaps = "<br>".join(e.get("gaps", [])) or ""
            out.append(f"| `{e['name']}` | {e['verdict']} | {gaps} | {e.get('evidence', '')} | {e.get('tested', '')} |")
        out.append("")
    return "\n".join(out) + "\n"


if __name__ == "__main__" and "--markdown" in sys.argv:
    root = Path(__file__).resolve().parent.parent
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    entries = json.loads((root / "docs/import_audit.json").read_text())
    (root / "docs/IMPORT_AUDIT.md").write_text(render_markdown(entries))
    print("wrote docs/IMPORT_AUDIT.md", len(entries), "entries")
