"""Every mutable piece of the host's state has one owner: the components of `_host.py`'s split (`Guest`, `Net`, and
`Pyodide` for what has not moved yet) assign disjoint sets of attributes, and a component is reached from another class
only through its public methods (`Net`) or as a read-only handle (`Guest`). The check is an AST walk of the package's
sources (no wasm needed); `check_ownership` takes source text, so the self-tests can show that it fails on bad code.
Pyright's `reportPrivateUsage` (pyproject.toml) enforces the underscore on the other side."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "pyodide_nojs"

# The component classes. A later step of the split adds its class here (Loader, Ffi, Snapshot...).
COMPONENTS = ("Guest", "Net", "Pyodide")
# `self.<handle>` is a reference to another component, not state of this one: assigned in each class that holds it.
HANDLES = frozenset({"guest"})
# Components reached from another class as `<expr>.<attribute>.<name>`: only a method of the owner may be named
# (Net); for the read-only handle (Guest) a public name may be read but never assigned.
METHODS_ONLY = {"net": "Net"}
READ_ONLY = {"guest": "Guest"}
# Components whose own state is all private (`_x`): nothing outside can name it without pyright's complaint.
PRIVATE_STATE = frozenset({"Net"})
# The one class that may touch the stack of call contexts (`Guest.wrap` pushes and pops, inline: the hot path).
CUR_OWNERS = frozenset({"Guest"})
# The one read of `cur` allowed elsewhere: the context of the running host function, `<expr>.guest.cur[-1]`.
ALLOWED_CUR_INDEX = "-1"
# A public method of a component must not return an internal dict/list/set (the caller could change it). Methods
# that do on purpose are named here as "Class.method", each with the reason; none today.
RETURNS_OK: frozenset[str] = frozenset()
MUTABLE_CALLS = frozenset({"dict", "list", "set", "bytearray", "WeakSet", "deque", "defaultdict"})
HANDLE_NAMES = frozenset({*READ_ONLY, *METHODS_ONLY})


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
    elif isinstance(node, ast.Delete):
        found = list(node.targets)
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


def _chain_has(target: ast.expr, pred) -> bool:
    """Does the attribute chain of `target` (`a.b[i].c`...) contain an Attribute node that `pred` accepts?"""
    chain = target
    while isinstance(chain, (ast.Attribute, ast.Subscript)):
        if isinstance(chain, ast.Attribute) and pred(chain):
            return True
        chain = chain.value
    return False


def _is_mutable(value: ast.expr | None) -> bool:
    if isinstance(value, (ast.Dict, ast.List, ast.Set, ast.DictComp, ast.ListComp, ast.SetComp)):
        return True
    if isinstance(value, ast.Call):
        f = value.func
        return (f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else "") in MUTABLE_CALLS
    return False


def mutable_attributes(cls: ast.ClassDef) -> set[str]:
    """The attributes of a class that are given a dict, list, set or the like (`self.X = {}`, or in the class body)."""
    names: set[str] = set()
    for node in ast.walk(cls):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and _is_mutable(node.value):
            for t in _targets(node):
                if isinstance(t, ast.Name) and node in cls.body:
                    names.add(t.id)
                elif isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                    names.add(t.attr)
    return names


def _allowed_cur_reads(top: ast.AST) -> set[int]:
    """The Attribute nodes `cur` of the one allowed read, `<expr>.guest.cur[-1]`."""
    found: set[int] = set()
    for node in ast.walk(top):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.ctx, ast.Load)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "cur"
            and isinstance(node.value.value, ast.Attribute)
            and node.value.value.attr == "guest"
            and ast.unparse(node.slice) == ALLOWED_CUR_INDEX
        ):
            found.add(id(node.value))
    return found


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
    for c in (c for c in COMPONENTS if c in classes):
        mutable = mutable_attributes(classes[c])
        for fn in (n for n in classes[c].body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
            if fn.name.startswith("_") or f"{c}.{fn.name}" in RETURNS_OK:
                continue
            for ret in (n for n in ast.walk(fn) if isinstance(n, ast.Return)):
                v = ret.value
                if isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name) and v.value.id == "self":
                    if v.attr in mutable:
                        problems.append(f"{c}.{fn.name} returns its internal mutable self.{v.attr}")
    methods = {
        c: {n.name for n in classes[c].body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for c in METHODS_ONLY.values()
        if c in classes
    }

    for fname, tree in trees.items():
        for top in tree.body:
            inside = top.name if isinstance(top, ast.ClassDef) else ""
            allowed_cur = _allowed_cur_reads(top)

            def foreign(a: ast.Attribute, inside: str = inside) -> bool:
                """`cur` of anything, or `<expr>.guest.<name>`, outside the class that owns it."""
                if a.attr == "cur":
                    return inside not in CUR_OWNERS
                return isinstance(a.value, ast.Attribute) and a.value.attr in READ_ONLY and inside != "Guest"

            for node in ast.walk(top):
                where = f"{fname}:{getattr(node, 'lineno', 0)} in {inside or 'module'}"
                # a store (assignment, augmented assignment, del, for/with target) at any depth of its target
                for t in _targets(node):
                    if _chain_has(t, foreign):
                        problems.append(f"{where}: {ast.unparse(t)} modifies the shared handle outside Guest")
                if isinstance(node, ast.Attribute):
                    name = node.attr
                    handle = node.value.attr if isinstance(node.value, ast.Attribute) else None
                    if handle in METHODS_ONLY and inside != METHODS_ONLY[handle]:
                        if name.startswith("_") or name not in methods.get(METHODS_ONLY[handle], ()):
                            owner = METHODS_ONLY[handle]
                            problems.append(f"{where}: .{handle}.{name} is not a public method of {owner}")
                    if handle in READ_ONLY and inside != READ_ONLY[handle] and name.startswith("_"):
                        problems.append(f"{where}: .{handle}.{name} is private to {READ_ONLY[handle]}")
                    if name == "cur" and inside not in CUR_OWNERS and id(node) not in allowed_cur:
                        problems.append(f"{where}: .cur is read outside Guest (only .guest.cur[-1] may be)")
                    if name == "__dict__" and isinstance(node.value, (ast.Attribute, ast.Name)):
                        last = node.value.attr if isinstance(node.value, ast.Attribute) else node.value.id
                        if last in HANDLE_NAMES:
                            problems.append(f"{where}: __dict__ of a handle")
                # an alias of a handle in a local: it could be used where the checks above do not look
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
                    v = node.value
                    tg = node.targets if isinstance(node, ast.Assign) else [node.target]
                    if (
                        isinstance(v, ast.Attribute)
                        and v.attr in HANDLE_NAMES
                        and any(isinstance(t, ast.Name) for t in tg)
                        and inside != {**READ_ONLY, **METHODS_ONLY}[v.attr]
                    ):
                        problems.append(f"{where}: aliases a handle (.{v.attr}) in a local")
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.args:
                    if node.func.id in {"setattr", "delattr", "vars"}:
                        a0 = node.args[0]
                        last = a0.attr if isinstance(a0, ast.Attribute) else a0.id if isinstance(a0, ast.Name) else ""
                        if last in HANDLE_NAMES:
                            problems.append(f"{where}: {node.func.id}() on a handle")
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


PRELUDE = """
class Guest:
    def __init__(self):
        self.store = None
        self.ex = {}
        self.cur = []
class Net:
    def __init__(self, guest):
        self.guest = guest
        self._socks = {}
    def ops(self):
        return self.guest.store, self.guest.cur[-1], self.guest.ex["malloc"]
"""


def program(net: str = "pass", pyodide: str = "pass", net_more: str = "") -> str:
    """The prelude, then a method `bad(self, x)` of Net and one of Pyodide with these bodies."""

    def ind(body: str) -> str:
        return "".join(f"        {line}\n" for line in body.strip().splitlines())

    return (
        PRELUDE
        + f"    def bad(self, x):\n{ind(net)}{net_more}"
        + "class Pyodide:\n    def __init__(self):\n        self.guest = Guest()\n        self.net = Net(self.guest)\n"
        + f"    def bad(self, x):\n{ind(pyodide)}"
    )


GOOD = program(
    net="return self.guest.cur[-1], self.guest.ex['malloc']", pyodide="return self.net.ops(), self.guest.store"
)

CUR = ".cur is read outside Guest"
STORE = "modifies the shared handle"
# What must be reported: (what it is, the source, a part of the report). Each one fooled an earlier checker.
BAD = [
    ("store into cur", program(net="self.guest.cur[-1] = x"), STORE),
    ("slice store into cur", program(net="self.guest.cur[:] = []"), STORE),
    ("del from cur", program(net="del self.guest.cur[-1]"), STORE),
    ("alias of cur", program(net="c = self.guest.cur\nc.append(x)"), CUR),
    ("reverse cur", program(net="self.guest.cur.reverse()"), CUR),
    ("__setitem__ of cur", program(net="self.guest.cur.__setitem__(0, x)"), CUR),
    ("append to cur", program(net="self.guest.cur.append(x)"), CUR),
    ("another index of cur", program(net="return self.guest.cur[0]"), CUR),
    ("store into the exports", program(net="self.guest.ex['malloc'] = x"), STORE),
    ("augmented store", program(net="self.guest.store += 1"), STORE),
    ("store of an attribute", program(pyodide="self.guest.store = 5"), STORE),
    ("alias of the handle", program(net="g = self.guest\ng.store = 1"), "aliases a handle (.guest)"),
    ("alias of the other handle", program(pyodide="n = self.net\nn.x = 1"), "aliases a handle (.net)"),
    ("setattr on the handle", program(net="setattr(self.guest, 'store', 1)"), "setattr() on a handle"),
    ("delattr on the handle", program(net="delattr(self.guest, 'store')"), "delattr() on a handle"),
    ("vars of the handle", program(net="vars(self.guest)['store'] = 1"), "vars() on a handle"),
    ("__dict__ of the handle", program(net="self.guest.__dict__['store'] = 1"), "__dict__ of a handle"),
    ("a private name of the handle", program(net="return self.guest._hidden"), ".guest._hidden is private to Guest"),
    (
        "a public method that gives an internal dict away",
        program(
            net_more="    def sockets(self):\n        return self._socks\n",
            pyodide="self.net.sockets().clear()",
        ),
        "Net.sockets returns its internal mutable self._socks",
    ),
    ("a private method of a component", program(pyodide="return self.net._helper()"), "is not a public method of Net"),
    ("a data attribute of a component", program(pyodide="return self.net.nothing"), "is not a public method of Net"),
]

PAIR = """
class Guest:
    def __init__(self):
        self.store = None
        self.cur = []
class Net:
    def __init__(self, guest):
        self.guest = guest
        self.socks = {}
        self.data = 2
class Pyodide:
    def __init__(self):
        self.guest = Guest()
        self.net = Net(self.guest)
        self.data = 1
        self.data, (self.cur, self.extra[0]) = 1, (2, 3)
"""


def test_the_checker_passes_good_code() -> None:
    assert check_ownership({"good.py": GOOD}) == []


@pytest.mark.parametrize(("what", "source", "expected"), BAD, ids=[b[0] for b in BAD])
def test_the_checker_reports_what_fooled_it_before(what: str, source: str, expected: str) -> None:
    report = "\n".join(check_ownership({"bad.py": source}))
    assert expected in report, (what, report)


def test_the_checker_reports_two_owners_of_one_attribute() -> None:
    report = "\n".join(check_ownership({"pair.py": PAIR}))
    for must in (
        "Net and Pyodide both assign self.data",  # one state, two owners (any depth of target)
        "Guest and Pyodide both assign self.cur",  # ... in a tuple target
        "Net.socks is state and is not private",
    ):
        assert must in report, (must, report)
