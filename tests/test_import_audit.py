"""docs/import_audit.json is held to the built adapter: every `env` import of pyodide.asm.wasm has an entry, and what an
entry claims about being answered agrees with what adapter.wasm really exports. A new export, or a removed one, fails
here until the audit says what it is."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from wasmtime import FuncType

from pyodide_wasmtime import _engine, _wasm, data_dir

AUDIT = Path(__file__).resolve().parent.parent / "docs" / "import_audit.json"
VERDICTS = {"full", "partial", "enosys", "stub", "n/a"}
CLASSES = {"js-value", "js-bridge", "os", "runtime", "hook"}


@pytest.fixture(scope="module")
def built():
    main, adapter = data_dir() / "pyodide.asm.wasm", data_dir() / "adapter.wasm"
    if not (main.exists() and adapter.exists()):
        pytest.skip("not built (tools/build_data.sh)")
    imports = {n: (ps, rs) for mod, n, ps, rs in _wasm.func_imports(_engine.load_module(main)) if mod == "env"}
    answered = {e.name for e in _engine.load_module(adapter).exports if isinstance(e.type, FuncType)}
    answered.add(_wasm.TRAMP)  # answered by the trampoline module, not by the adapter
    return imports, answered


@pytest.fixture(scope="module")
def audit():
    if not AUDIT.exists():
        pytest.skip("docs/import_audit.json is not written yet")
    return {e["name"]: e for e in json.loads(AUDIT.read_text())}


def test_every_import_has_an_entry_and_no_entry_is_stale(built, audit):
    imports, _ = built
    assert set(imports) - set(audit) == set(), "imports without an audit entry"
    assert set(audit) - set(imports) == set(), "audit entries for imports that no longer exist"


def test_entries_are_well_formed(audit):
    for name, e in audit.items():
        assert e["verdict"] in VERDICTS, name
        assert e["class"] in CLASSES, name
        if e["verdict"] == "partial":
            assert e["gaps"], f"{name}: partial without a named gap"
        if e["verdict"] in ("full", "partial"):
            assert e.get("evidence"), f"{name}: no evidence"
            assert e.get("tested"), f"{name}: 'tested' is a test id or 'no'"


def test_verdicts_agree_with_the_built_adapter(built, audit):
    """An exported function can be anything but n/a (a lying `stub` and an always-failing `enosys` included);
    one that is not exported is a stub, ENOSYS (a system call) or has no meaning without JavaScript."""
    _, answered = built
    for name, e in audit.items():
        if name in answered:
            assert e["verdict"] != "n/a", f"{name} is exported by the adapter but the audit says n/a"
        else:
            assert e["verdict"] in ("enosys", "stub", "n/a"), (
                f"{name} is not answered but the audit says {e['verdict']}"
            )
        if name.startswith("__syscall_") and name not in answered:
            assert e["verdict"] == "enosys", f"{name}: an unanswered system call returns ENOSYS"


def test_js_values_are_never_answered(built, audit):
    imports, answered = built
    for name, (ps, rs) in imports.items():
        if any(t == "externref" for t in [*ps, *rs]):
            assert name not in answered, f"{name} takes a JavaScript value but the adapter answers it"
            assert audit[name]["class"] == "js-value", name
