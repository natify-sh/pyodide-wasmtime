"""Every mutable piece of the host's state has one owner: the components of `_host.py`'s split (`Guest`, `Net`, and
`Pyodide` for what has not moved yet) assign disjoint sets of attributes, and a component is reached from another class
only through its public methods (`Net`) or as a read-only handle (`Guest`). The check is an AST walk of the package's
sources (no wasm needed); `check_ownership` takes source text, so the last test can show that it fails on bad code.
Pyright's `reportPrivateUsage` (pyproject.toml) enforces the underscore on the other side."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "pyodide_nojs"

# The component classes. A later step of the split adds its class here (Loader, Ffi, Snapshot...).
COMPONENTS = ("Guest", "Net", "Pyodide")
# `self.<handle>` is a reference to another component, not state of this one: assigned in each class that holds it.
HANDLES = frozenset({"guest", "g"})
# Components reached from another class as `<expr>.<attribute>.<name>`: only a method of the owner may be named
# (Net); for the read-only handle (Guest) a public name may be read but never assigned.
METHODS_ONLY = {"net": "Net"}
READ_ONLY = {"guest": "Guest"}
# Components whose own state is all private (`_x`): nothing outside can name it without pyright's complaint.
PRIVATE_STATE = frozenset({"Net"})
# The classes that may change the stack of call contexts: `Guest`, and its `with` object that pushes and pops.
CUR_OWNERS = frozenset({"Guest", "_Entered"})
MUTATORS = frozenset({"append", "pop", "clear", "extend", "insert", "remove"})


def _root_attr(target: ast.expr) -> str | None:
    """`self.X` of an assignment target `self.X`, `self.X[i]`, `self.X.y`..., else None."""
    chain = target
    while isinstance(chain, (ast.Attribute, ast.Subscript)):
        inner = chain.value
        if isinstance(chain, ast.Attribute) and isinstance(inner, ast.Name) and inner.id == "self":
            return chain.attr
        chain = inner
    return None


def _targets(node: ast.AST) -> list[ast.expr]:
    found: list[ast.expr]
    if isinstance(node, ast.Assign):
        found = list(node.targets)
    elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
        found = [node.target]
    elif isinstance(node, (ast.For, ast.AsyncFor)):
        found = [node.target]
    elif isinstance(node, ast.withitem):
        found = [node.optional_vars] if node.optional_vars is not None else []
    else:
        return []
    out: list[ast.expr] = []
    while found:
        t = found.pop()
        if isinstance(t, (ast.Tuple, ast.List)):
            found += t.elts
        elif isinstance(t, ast.Starred):
            found.append(t.value)
        else:
            out.append(t)
    return out


def assigned_attributes(cls: ast.ClassDef) -> set[str]:
    """The names a class assigns through `self.X = ...` (any depth of target) and in its class body."""
    names: set[str] = set()
    for stmt in cls.body:  # class-level constants and tables
        for t in _targets(stmt):
            if isinstance(t, ast.Name):
                names.add(t.id)
    for node in ast.walk(cls):
        for t in _targets(node):
            if (name := _root_attr(t)) is not None:
                names.add(name)
    return names


def check_ownership(sources: dict[str, str]) -> list[str]:
    """What breaks the single ownership of state in these sources ({file name: text}); empty if nothing does."""
    problems: list[str] = []
    classes: dict[str, ast.ClassDef] = {}
    trees = {name: ast.parse(text) for name, text in sources.items()}
    for tree in trees.values():
        classes.update({n.name: n for n in tree.body if isinstance(n, ast.ClassDef)})
    owned = {c: assigned_attributes(classes[c]) for c in COMPONENTS if c in classes}
    for a, b in ((a, b) for a in owned for b in owned if a < b):
        for name in sorted(owned[a] & owned[b] - HANDLES):
            problems.append(f"{a} and {b} both assign self.{name}")
    for c in PRIVATE_STATE & owned.keys():
        for name in sorted(owned[c] - HANDLES):
            if not name.startswith("_"):
                problems.append(f"{c}.{name} is state and is not private (start it with an underscore)")
    methods = {
        c: {n.name for n in classes[c].body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for c in {*METHODS_ONLY.values(), *READ_ONLY.values()}
        if c in classes
    }

    for fname, tree in trees.items():
        for top in tree.body:
            inside = top.name if isinstance(top, ast.ClassDef) else ""
            for node in ast.walk(top):
                if not isinstance(node, ast.Attribute):
                    continue
                where = f"{fname}:{node.lineno} in {inside or 'module'}"
                if isinstance(node.value, ast.Attribute):
                    handle, name = node.value.attr, node.attr
                    if handle in METHODS_ONLY and inside != METHODS_ONLY[handle]:
                        if name.startswith("_") or name not in methods.get(METHODS_ONLY[handle], ()):
                            problems.append(
                                f"{where}: .{handle}.{name} is not a public method of {METHODS_ONLY[handle]}"
                            )
                    if handle in READ_ONLY and inside != READ_ONLY[handle]:
                        if not isinstance(node.ctx, ast.Load):
                            problems.append(f"{where}: .{handle}.{name} is assigned outside {READ_ONLY[handle]}")
                        elif name.startswith("_"):
                            problems.append(f"{where}: .{handle}.{name} is private to {READ_ONLY[handle]}")
                # the stack of call contexts: its one mutator is `Guest.entered`
                if node.attr == "cur" and inside not in CUR_OWNERS:
                    if not isinstance(node.ctx, ast.Load):
                        problems.append(f"{where}: .cur is assigned outside Guest")
            if inside not in CUR_OWNERS:
                for call in (n for n in ast.walk(top) if isinstance(n, ast.Call)):
                    f = call.func
                    if (
                        isinstance(f, ast.Attribute)
                        and f.attr in MUTATORS
                        and isinstance(f.value, ast.Attribute)
                        and f.value.attr == "cur"
                    ):
                        problems.append(f"{fname}:{call.lineno}: .cur.{f.attr}() outside Guest")
    return problems


def package_sources() -> dict[str, str]:
    return {p.name: p.read_text() for p in sorted(SRC.glob("*.py"))}


def test_the_components_are_in_the_package() -> None:
    sources = package_sources()
    classes = {n.name for text in sources.values() for n in ast.parse(text).body if isinstance(n, ast.ClassDef)}
    assert set(COMPONENTS) <= classes


def test_every_piece_of_state_has_one_owner() -> None:
    assert check_ownership(package_sources()) == []


def test_the_new_modules_are_in_the_snapshot_key(tmp_path: Path) -> None:
    """The snapshot's key hashes every module of the package: a change of `_guest.py` or `_net.py` makes a new one."""
    from pyodide_nojs._consts import code_hash

    for p in SRC.glob("*.py"):
        (tmp_path / p.name).write_bytes(p.read_bytes())
    for name in ("_guest.py", "_net.py"):
        before = code_hash(tmp_path)
        with (tmp_path / name).open("a") as f:
            f.write("# changed\n")
        assert code_hash(tmp_path) != before, name


GOOD = """
class Guest:
    def __init__(self):
        self.store = None
        self.cur = []
    def entered(self, ctx):
        self.cur.append(ctx)
class Net:
    def __init__(self, guest):
        self.guest = guest
        self._socks = {}
    def ops(self):
        return self.guest.store, self.guest.cur[-1]
class Pyodide:
    def __init__(self):
        self.guest = Guest()
        self.net = Net(self.guest)
        self.data = 1
    def run(self):
        return self.net.ops(), self.guest.store
"""

BAD = """
class Guest:
    def __init__(self):
        self.store = None
        self.cur = []
class Net:
    def __init__(self, guest):
        self.guest = guest
        self.socks = {}
        self.data = 2
    def ops(self):
        self.guest.cur.append(1)
class Pyodide:
    def __init__(self):
        self.guest = Guest()
        self.net = Net(self.guest)
        self.data = 1
        self.data, (self.cur, self.extra[0]) = 1, (2, 3)
    def _helper(self):
        self.guest.store = 5
        self.net._socks.clear()
        return self.net.socks, self.net.nothing, self.guest._hidden
"""


def test_the_checker_passes_good_code_and_reports_bad_code() -> None:
    assert check_ownership({"good.py": GOOD}) == []
    report = "\n".join(check_ownership({"bad.py": BAD}))
    for must in (
        "Net and Pyodide both assign self.data",  # one state, two owners (any depth of target)
        "Guest and Pyodide both assign self.cur",  # ... in a tuple target
        "Net.socks is state and is not private",
        ".net._socks is not a public method of Net",
        ".net.socks is not a public method of Net",
        ".net.nothing is not a public method of Net",
        ".guest.store is assigned outside Guest",
        ".guest._hidden is private to Guest",
        ".cur.append() outside Guest",
    ):
        assert must in report, (must, report)
