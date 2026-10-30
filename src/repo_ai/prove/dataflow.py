"""Does the scenario check the change's behaviour, or only something the
change set up for it? (Session A's G4, and the sixth and seventh reviews.)

The scenario's candidate side runs on the base plus the code under test. When
the change alters what the scenario feeds into code it does not edit (an
input helper changed from ``[]`` to ``[0]`` and passed to an unchanged
``mean``), or sets up state that other code reads (a registry, an environment
variable, a file), the scenario turns from failing to passing although
nothing it checks was fixed. An expected value the repository computes is the
same problem from the other side.

Inputs, outputs and side effects cannot be told apart from the bytes, and
following them through the repository's code is open-ended (seven review
rounds found a new path each time). So ProofLab supports a claim only for a
scenario of a narrow, checkable shape, and abstains (the claim is
``incomplete``) for anything else:

1. **One entry point.** Everything the scenario (with the test code it
   imports, and the fixtures and hooks it uses) calls in the repository is a
   single function or class, or methods of objects that one returns. A
   second entry point (``configure()`` then ``mean([])``; ``mean(empty())``)
   could set up what the first one reads.
2. **Literal inputs.** Nothing that comes from the repository (a value, a
   function, a module's attribute) is passed to the repository's code, or
   handed to other code that may call it (``map``, ``functools.partial``).
3. **Independent expectations.** A value from the repository is compared
   only with values that do not come from it: literals, computations on
   literals outside the repository (``pytest.approx(0)``), an enum member or
   a class.
4. **A form ProofLab reads.** No dynamic names or imports (``getattr``,
   ``setattr``, ``importlib``, ``exec``), no star imports from the
   repository, no decorators but pytest's and unittest's with literal
   arguments, no fixture but pytest's own or one defined in the scenario or
   the ``conftest.py`` files above it, no ``pytest_generate_tests``, and no
   module-level code beyond imports, definitions and assignments.
5. **No import-time edits.** The change does not edit statements that run
   when a subject module is imported, other than definitions, assignments to
   names, and imports guarded by ``try``/``if``.
6. **No new comparison rules.** The change does not add or edit a class's
   ``__eq__``, ``__bool__``, ``__len__`` and similar methods: a value whose
   ``__eq__`` always holds would pass any comparison with a literal.

Node scenarios are not parsed at all: their claims always abstain.

The cost is false "incomplete" verdicts: a genuine fix observed through a
second function (``render(parse(x))``), compared with an object the code
builds (``== Token("a")``), or set up by a fixture that calls the repository.
Write the scenario as calls of the changed function or class with literal
inputs and literal expectations.
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import Callable, Sequence

from . import conditions

Reader = Callable[[str], "bytes | None"]
MAX_FILES = 60
MAX_PASSES = 25
MAX_FINDINGS = 5
_DYNAMIC_NAMES = frozenset({"getattr", "setattr", "delattr", "globals", "locals", "vars", "exec", "eval", "compile",
                            "__import__", "pytest_generate_tests"})
_DYNAMIC_CHAINS = ("importlib.", "runpy.", "request.getfixturevalue", "metafunc.parametrize", "sys.modules")
SAFE_FIXTURES = frozenset({"tmp_path", "tmp_path_factory", "tmpdir", "tmpdir_factory", "capsys", "capfd",
                           "capsysbinary", "capfdbinary", "caplog", "recwarn"})
_DECORATORS = ("pytest.fixture", "fixture", "pytest.mark.", "mark.", "unittest.skip", "unittest.expectedFailure",
               "skip", "skipIf", "skipUnless", "expectedFailure", "staticmethod", "classmethod", "property")
# calls that compare or describe their arguments and never call them
_ORACLES = frozenset({"pytest.approx", "approx", "pytest.raises", "pytest.warns", "math.isclose", "isinstance",
                      "issubclass", "type", "len", "repr", "str", "bool", "int", "float", "list", "tuple", "set",
                      "frozenset", "dict", "id", "hash", "abs", "round", "sorted", "print"})
_ENUMS = ("Enum", "IntEnum", "StrEnum", "Flag", "IntFlag")
_BUILDERS = frozenset({"locals", "vars", "globals", "setattr", "exec", "eval", "compile", "__import__",
                       "types.new_class", "type.__new__", "object.__setattr__", "importlib.import_module"})
_XUNIT = frozenset({"setup_module", "teardown_module", "setup_function", "teardown_function", "setUpModule",
                    "tearDownModule", "setup", "teardown"})
# what decides a comparison's or an assertion's outcome on a value of the code under test
_COMPARING = frozenset({"__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__", "__bool__", "__len__", "__hash__",
                        "__contains__", "__float__", "__int__", "__index__", "__instancecheck__", "__getattr__",
                        "__getattribute__", "__class_getitem__", "__subclasshook__"})

# a value: the repository code it came from ("ref:" a function, class or attribute named; "obj:" what a call
# returned). Empty: nothing of the repository.
V = frozenset[str]
NONE: V = frozenset()


def _chain(node: ast.AST) -> list[str] | None:
    """`a.b.c` as ["a", "b", "c"], or None when it is not a plain dotted name."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        return [node.id, *reversed(parts)]
    return None


def _key(parts: Sequence[str]) -> str:
    parts = list(parts)
    if parts and parts[0] == "cls":  # class attributes set in setUpClass, read through self
        parts = ["self", *parts[1:]]
    return ".".join(parts)


def _literal(node: ast.AST) -> bool:
    try:
        ast.literal_eval(node)
        return True
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False


def _parse(data: bytes | None) -> ast.Module | None:
    if data is None or len(data) > conditions.MAX_PARSE_BYTES:
        return None
    try:
        return ast.parse(data.decode("utf-8", "replace"))
    except (SyntaxError, ValueError, RecursionError):
        return None


def _binds(stmt: ast.stmt) -> list[str]:
    """The module-level names one statement binds ([] when it binds none, or
    rebinds something else: `x.y = …`, `x[k] = …`)."""
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [stmt.name]
    if isinstance(stmt, (ast.Import, ast.ImportFrom)):
        return [a.asname or a.name.split(".")[0] for a in stmt.names if a.name != "*"]
    targets: list[ast.expr] = []
    if isinstance(stmt, ast.Assign):
        targets = list(stmt.targets)
    elif isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
        targets = [stmt.target]
    out: list[str] = []
    for t in targets:
        for n in (t.elts if isinstance(t, (ast.Tuple, ast.List)) else [t]):
            if isinstance(n, ast.Name):
                out.append(n.id)
            else:
                return []
    return out


def _main_guard(stmt: ast.stmt) -> bool:
    return isinstance(stmt, ast.If) and "__name__" in ast.dump(stmt.test) and "__main__" in ast.dump(stmt.test)


def _docstring(stmt: ast.stmt) -> bool:
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)


def _harmless(stmt: ast.stmt) -> bool:
    """A module-level statement that only binds names: definitions,
    assignments to names, imports, also inside `try` and `if` (an optional
    import with a fallback)."""
    if _binds(stmt) or _docstring(stmt) or _main_guard(stmt) or isinstance(stmt, ast.Pass):
        return True
    if isinstance(stmt, ast.If):
        return all(_harmless(s) for s in [*stmt.body, *stmt.orelse])
    if isinstance(stmt, ast.Try):
        return all(_harmless(s) for s in [*stmt.body, *stmt.orelse, *stmt.finalbody,
                                         *(s for h in stmt.handlers for s in h.body)])
    return False


def _oracle(func: ast.AST) -> bool:
    c = _chain(func) or []
    return ".".join(c) in _ORACLES or (len(c) == 2 and c[0] == "self" and c[1].startswith("assert"))


class _Tree:
    """The files the scenario's candidate side runs (the base plus the subject)."""

    def __init__(self, scenario: str, files: set[str], read: Reader, cwd: str):
        self.scenario, self.present, self.read, self.cwd = scenario, files, read, cwd
        self._parsed: dict[str, ast.Module | None] = {}

    def parse(self, rel: str) -> ast.Module | None:
        if rel not in self._parsed:
            self._parsed[rel] = _parse(self.read(rel))
        return self._parsed[rel]

    def module(self, rel: str, parts: list[str], level: int) -> str | None:
        if level:
            anchor = PurePosixPath(rel).parent
            for _ in range(level - 1):
                anchor = anchor.parent
            bases = [anchor.as_posix()]
        else:
            bases = conditions.roots_for(self.scenario, self.cwd)
        for b in bases:
            stem = "/".join([b, *parts]) if b not in {"", "."} else "/".join(parts)
            for cand in (f"{stem}.py", f"{stem}/__init__.py"):
                if cand in self.present:
                    return cand
        return None

    def descend(self, file: str, attrs: list[str]) -> tuple[str, list[str]]:
        while attrs and file.endswith("__init__.py"):
            folder = PurePosixPath(file).parent.as_posix()
            stem = f"{folder}/{attrs[0]}" if folder not in {"", "."} else attrs[0]
            sub = next((c for c in (f"{stem}.py", f"{stem}/__init__.py") if c in self.present), None)
            if sub is None:
                break
            file, attrs = sub, attrs[1:]
        return file, attrs


class _Imports:
    def __init__(self, tree: _Tree, rel: str):
        self.names: dict[str, tuple[str, list[str]]] = {}
        self.stars: list[str] = []
        self.defined: set[str] = set()
        mod = tree.parse(rel)
        if mod is None:
            return
        for top in mod.body:
            if not isinstance(top, (ast.Import, ast.ImportFrom)):
                self.defined.update(_binds(top))
        for node in ast.walk(mod):
            if isinstance(node, ast.Import):
                for a in node.names:
                    parts = a.name.split(".")
                    f = tree.module(rel, parts if a.asname else parts[:1], 0)
                    if f:
                        self.names[a.asname or parts[0]] = (f, [])
            elif isinstance(node, ast.ImportFrom):
                parts = [p for p in (node.module or "").split(".") if p]
                for a in node.names:
                    if a.name == "*":
                        f = tree.module(rel, parts, node.level)
                        if f:
                            self.stars.append(f)
                        continue
                    sub = tree.module(rel, [*parts, a.name], node.level)
                    if sub:
                        self.names[a.asname or a.name] = (sub, [])
                        continue
                    f = tree.module(rel, parts, node.level)
                    if f:
                        self.names[a.asname or a.name] = (f, [a.name])


class Analysis:
    def __init__(self, scenario: str, files: set[str], read: Reader, subject: set[str], cwd: str = "",
                 read_base: Reader | None = None):
        self.tree = _Tree(scenario, files, read, cwd)
        self.subject = subject
        self.read_base = read_base
        self._imports: dict[str, _Imports] = {}
        group = [scenario, *sorted(conditions.closure(scenario, sorted(files), read, cwd))]
        self.conftests = []
        for d in conditions._ancestors(scenario):
            c = f"{d}/conftest.py" if d else "conftest.py"
            if c in files and c not in group:
                group.append(c)
                self.conftests.append(c)
                # the test code a conftest.py imports (fixtures kept in a helper module)
                group += [t for t in sorted(conditions.closure(c, sorted(files), read, cwd)) if t not in group]
        # pytest's machinery: every plugin module conftest files or the configuration load (`pytest_plugins`, -p)
        machinery, _reach = conditions.harness(sorted(files), read, cwd)
        group += [m for m in sorted(machinery) if m not in group and PurePosixPath(m).name != "conftest.py"]
        self.group = [g for g in group if g.endswith(".py")][:MAX_FILES]
        self.env: dict[str, dict[str, V]] = {g: {} for g in self.group}
        self.returns: dict[tuple[str, str], V] = {}
        self.funcs: dict[str, dict[str, ast.FunctionDef | ast.AsyncFunctionDef]] = {g: {} for g in self.group}
        self.fixtures: dict[str, list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]] = {}
        self.active: set[tuple[str, str]] = set()  # functions of test helpers and conftest files that run
        self.entries: dict[str, str] = {}  # the repository's entry points the scenario calls -> where
        self.findings: list[str] = []

    def imports(self, rel: str) -> _Imports:
        if rel not in self._imports:
            self._imports[rel] = _Imports(self.tree, rel)
        return self._imports[rel]

    # ------------------------------------------------------------ the change's import-time code
    def _import_time(self) -> None:
        for f in sorted(self.subject):
            if not f.endswith(".py"):
                continue
            cand = self.tree.parse(f)
            base = _parse(self.read_base(f)) if self.read_base is not None else None

            def other(mod: ast.Module | None) -> list[str]:
                return sorted(ast.dump(st) for st in (mod.body if mod is not None else []) if not _harmless(st))
            if cand is not None and other(cand) != other(base):
                self._note(f"the change edits code that runs when {f} is imported (statements other than "
                           "definitions, assignments to names and imports): it can set up state that other code "
                           "reads, which ProofLab cannot follow")

            def dunders(mod: ast.Module | None) -> dict[str, str]:
                out: dict[str, str] = {}
                for c in ast.walk(mod) if mod is not None else []:
                    if isinstance(c, ast.ClassDef):
                        for st in c.body:
                            for n in _binds(st):
                                if n in _COMPARING:
                                    out[f"{c.name}.{n}"] = ast.dump(st)
                return out
            new, old = dunders(cand), dunders(base)
            edited = sorted(k for k in new if new[k] != old.get(k))
            # a changed definition that builds classes or attributes at run time can define how its values compare
            # without a class body ProofLab reads (`type("Z", (float,), {"__eq__": ...})`, `locals()[...] = ...`)
            before = {ast.dump(st) for st in (base.body if base is not None else [])}
            for st in (cand.body if cand is not None else []):
                if ast.dump(st) in before:
                    continue
                for n in ast.walk(st):
                    c = ".".join(_chain(n.func) or []) if isinstance(n, ast.Call) else ""
                    dyn = (c in _BUILDERS or (c == "type" and isinstance(n, ast.Call) and len(n.args) == 3)
                           or (isinstance(n, ast.Attribute) and n.attr in {"__class__", "__dict__"}
                               and isinstance(n.ctx, ast.Store)))
                    if dyn:
                        self._note(f"{f}:{getattr(n, 'lineno', 0)}: the change builds classes or attributes at run "
                                   f"time ({c or getattr(n, 'attr', '')}): it could decide how its values compare, "
                                   "which ProofLab cannot read")
                        break
            if edited:
                self._note(f"the change defines how values of {f} compare or test true ({', '.join(edited[:3])}): a "
                           "comparison with a literal would then check nothing")

    # ------------------------------------------------------------ names
    def resolve(self, file: str, attrs: list[str], depth: int = 0) -> tuple[str, list[str]]:
        """Follow re-exports to the module that defines the name."""
        file, attrs = self.tree.descend(file, attrs)
        if not attrs or depth > 10 or file in self.group:
            return file, attrs
        imp = self.imports(file)
        if attrs[0] in imp.names and attrs[0] not in imp.defined:
            f2, a2 = imp.names[attrs[0]]
            return self.resolve(f2, [*a2, *attrs[1:]], depth + 1)
        return file, attrs

    def _repo(self, rel: str, parts: list[str]) -> tuple[str, list[str]] | None:
        imp = self.imports(rel)
        if parts[0] in imp.names:
            f, attrs = imp.names[parts[0]]
            return self.resolve(f, [*attrs, *parts[1:]])
        return None

    def _identity(self, file: str, rest: list[str]) -> bool:
        """A class, or a member of an enum: a value the code cannot change by
        being called (an expected `Status.OK`, an exception type)."""
        mod = self.tree.parse(file)
        if mod is None or not rest or len(rest) > 2:
            return False
        for st in mod.body:
            if isinstance(st, ast.ClassDef) and st.name == rest[0]:
                if file in self.subject and self.read_base is not None:
                    # a class the change edits (an enum member made an alias of another) is not independent
                    base = _parse(self.read_base(file)) if self.read_base is not None else None
                    old = [ast.dump(b) for b in (base.body if base is not None else [])
                           if isinstance(b, ast.ClassDef) and b.name == st.name]
                    if old != [ast.dump(st)]:
                        return False
                if len(rest) == 1:
                    return True
                return any((_chain(b) or [""])[-1] in _ENUMS for b in st.bases)
        return False

    def _entry(self, ref: str, more: Sequence[str]) -> str:
        """The entry point a call through a local name reaches: an alias of a
        module (`m = mypkg; m.configure()`) reaches that module's attribute, an
        alias of a function or object reaches it (and its attribute)."""
        file, _, sym = ref.rpartition(":")
        if sym == "*" and more:
            f2, rest = self.resolve(file, list(more))
            return f"{f2}:{'.'.join(rest) or '*'}"
        return ref + ("." + ".".join(more) if more and sym != "*" else "")

    def _outside_code(self, file: str) -> bool:
        return conditions.testish(file, self.tree.scenario, self.tree.present)

    def value(self, rel: str, node: ast.AST | None) -> V:
        if node is None or isinstance(node, ast.Constant):
            return NONE
        if isinstance(node, (ast.Name, ast.Attribute)):
            parts = _chain(node)
            if parts is not None:
                env = self.env[rel]
                for i in range(len(parts), 0, -1):
                    if _key(parts[:i]) in env:
                        return env[_key(parts[:i])]
                hit = self._repo(rel, parts)
                if hit is None:
                    return NONE
                f, rest = hit
                if f in self.group:
                    return self.env[f].get(rest[0], NONE) if rest else NONE
                if self._outside_code(f) or self._identity(f, rest):
                    return NONE
                return frozenset({f"ref:{f}:{'.'.join(rest) or '*'}"})
            return self.value(rel, node.value if isinstance(node, ast.Attribute) else None)
        if isinstance(node, ast.Call):
            return self.call(rel, node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return NONE
        out: set[str] = set()
        for c in ast.iter_child_nodes(node):
            out |= self.value(rel, c)
        return frozenset(out)

    # ------------------------------------------------------------ calls
    def callee(self, rel: str, func: ast.AST) -> tuple[str, set[str], V, tuple[str, str] | None]:
        """(kind, the entry points it is, its value, the test-code function):
        kind is "repo" (a function or class of the repository), "method" (of
        an object the repository returned), "group" (test code ProofLab
        reads) or "external"."""
        if _oracle(func):
            return "external", set(), NONE, None
        parts = _chain(func)
        if parts is not None:
            env = self.env[rel]
            for i in range(len(parts), 0, -1):
                k = _key(parts[:i])
                if k in env and env[k]:
                    v = env[k]
                    refs = {self._entry(r[4:], parts[i:]) for r in v if r.startswith("ref:")}
                    return ("repo" if refs else "method"), refs, v, None
            k = _key(parts)
            if k in self.funcs[rel]:
                return "group", set(), NONE, (rel, k)
            hit = self._repo(rel, parts)
            if hit is not None:
                f, rest = hit
                if f in self.group:
                    if rest and rest[0] in self.funcs[f]:
                        return "group", set(), NONE, (f, rest[0])
                    return "external", set(), NONE, None
                if self._outside_code(f):
                    return "external", set(), NONE, None
                name = f"{f}:{'.'.join(rest) or '*'}"
                return "repo", {name}, frozenset({f"ref:{name}"}), None
            return "external", set(), NONE, None
        v = self.value(rel, func.value if isinstance(func, ast.Attribute) else func)
        refs = {r[4:] for r in v if r.startswith("ref:")}
        if refs:
            return "repo", refs, v, None
        return ("method" if v else "external"), set(), v, None

    def call(self, rel: str, node: ast.Call) -> V:
        args = [*node.args, *(k.value for k in node.keywords)]
        vals = [self.value(rel, a) for a in args]
        given = frozenset().union(*vals) if vals else NONE
        kind, entries, fv, fn = self.callee(rel, node.func)
        name = ".".join(_chain(node.func) or ["(an expression)"])
        if kind in {"repo", "method"} and given:
            self._note(f"{rel}:{node.lineno} passes a value of the repository ({_names(given)}) to {name}: what "
                       "the code under test receives must be literal, or the change may alter the scenario's input "
                       "rather than the behaviour it checks")
        if kind == "external" and any(r.startswith("ref:") for r in given):
            self._note(f"{rel}:{node.lineno} hands the repository's code ({_names(given)}) to {name}, which may call "
                       "it with inputs ProofLab cannot see")
        for e in entries:
            self.entries.setdefault(e, f"{rel}:{node.lineno}")
        if fn is not None:
            self.active.add(fn)
            self._bind_call(fn, node, vals)
            out = self.returns.get(fn, NONE) | given
        elif kind == "repo":
            out = frozenset(f"obj:{e}" for e in entries) | given
        elif kind == "method":
            out = fv | given
        else:
            out = given
        if isinstance(node.func, ast.Attribute) and node.func.attr.startswith("assert") and len(node.args) >= 2:
            self._compare(rel, node.args[:2], node.lineno)
        return out

    def _bind_call(self, fn: tuple[str, str], node: ast.Call, vals: list[V]) -> None:
        f, k = fn
        d = self.funcs[f].get(k)
        if d is None:
            return
        params = [a.arg for a in [*d.args.posonlyargs, *d.args.args]]
        if params and params[0] in {"self", "cls"}:
            params = params[1:]
        everything = params + [a.arg for a in d.args.kwonlyargs] + [a.arg for a in (d.args.vararg, d.args.kwarg)
                                                                   if a is not None]
        for i, v in enumerate(vals[:len(node.args)]):
            if isinstance(node.args[i], ast.Starred) or i >= len(params):
                for p in everything:
                    self._bind(f, ast.Name(id=p), v)
            else:
                self._bind(f, ast.Name(id=params[i]), v)
        for kw, v in zip(node.keywords, vals[len(node.args):], strict=False):
            for p in ([kw.arg] if kw.arg and kw.arg in everything else everything):
                self._bind(f, ast.Name(id=p), v)

    def _compare(self, rel: str, operands: Sequence[ast.AST], line: int) -> None:
        vals = [self.value(rel, o) for o in operands]
        derived = [o for o, v in zip(operands, vals, strict=True) if v]
        named = [o for o, v in zip(operands, vals, strict=True) if any(r.startswith("ref:") for r in v)]
        if len(derived) >= 2 or named:
            o = (named or derived)[-1]
            self._note(f"{rel}:{line} compares with {ast.unparse(o)[:60]}, which holds a value of the repository "
                       "besides the result under test: an expected value must be a literal, an enum member or a "
                       "class, and the repository's own values (a module constant) must not enter the comparison")

    # ------------------------------------------------------------ binding
    def _bind(self, rel: str, target: ast.AST, value: V) -> None:
        if not value:
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            for e in target.elts:
                self._bind(rel, e, value)
            return
        if isinstance(target, ast.Starred):
            self._bind(rel, target.value, value)
            return
        parts = _chain(target)
        if parts is None:
            if isinstance(target, ast.Subscript):
                self._bind(rel, target.value, value)
            return
        k = _key(parts)
        self.env[rel][k] = self.env[rel].get(k, NONE) | value

    def _state(self) -> str:
        return repr((sorted((f, sorted((k, sorted(v)) for k, v in e.items())) for f, e in self.env.items()),
                     sorted((k, sorted(v)) for k, v in self.returns.items()), sorted(self.active)))

    def _nodes(self, rel: str, mod: ast.Module):
        """What runs: the scenario entirely; in test helpers and conftest
        files, module-level code and the functions that are used."""
        if rel == self.tree.scenario:
            yield from ast.walk(mod)
            return
        todo: list[ast.AST] = []
        for st in mod.body:
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if (rel, st.name) in self.active or st.name.startswith("pytest_"):
                    todo.append(st)
            elif isinstance(st, ast.ClassDef):
                todo.append(st)
            else:
                todo.append(st)
        for t in todo:
            yield from ast.walk(t)

    def _pass(self) -> bool:
        before = self._state()
        for rel in self.group:
            mod = self.tree.parse(rel)
            if mod is None:
                continue
            for node in self._nodes(rel, mod):
                if isinstance(node, ast.Assign):
                    v = self.value(rel, node.value)
                    for t in node.targets:
                        self._bind(rel, t, v)
                elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and node.value is not None:
                    self._bind(rel, node.target, self.value(rel, node.value))
                elif isinstance(node, ast.NamedExpr):
                    self._bind(rel, node.target, self.value(rel, node.value))
                elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
                    self._bind(rel, node.target, self.value(rel, node.iter))
                elif isinstance(node, (ast.With, ast.AsyncWith)):
                    for item in node.items:
                        v = self.value(rel, item.context_expr)
                        if item.optional_vars is not None:
                            self._bind(rel, item.optional_vars, v)
                elif isinstance(node, ast.Try):
                    got = self.value(rel, ast.Module(body=node.body, type_ignores=[]))
                    for h in node.handlers:
                        if h.name:
                            self._bind(rel, ast.Name(id=h.name), got)
                elif isinstance(node, ast.Match):
                    got = self.value(rel, node.subject)
                    for case in node.cases:
                        for p in ast.walk(case.pattern):
                            for n in (getattr(p, "name", None), getattr(p, "rest", None)):
                                if isinstance(n, str):
                                    self._bind(rel, ast.Name(id=n), got)
                elif isinstance(node, ast.ClassDef):
                    for name in self._usefixtures(node):
                        self._use_fixture(rel, node, name)
                    for st in node.body:
                        if isinstance(st, (ast.Assign, ast.AnnAssign)) and st.value is not None:
                            v = self.value(rel, st.value)
                            for t in (st.targets if isinstance(st, ast.Assign) else [st.target]):
                                if isinstance(t, ast.Name):
                                    self._bind(rel, ast.Name(id=f"self.{t.id}"), v)
                                    self._bind(rel, ast.Name(id=f"{node.name}.{t.id}"), v)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self._function(rel, node)
                elif isinstance(node, ast.Compare):
                    self._compare(rel, [node.left, *node.comparators], node.lineno)
                elif isinstance(node, ast.Call):
                    self.call(rel, node)
        return before != self._state()

    def _function(self, rel: str, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        args = node.args
        positional = [*args.posonlyargs, *args.args]
        for a, d in zip(positional[len(positional) - len(args.defaults):], args.defaults, strict=True):
            self._bind(rel, ast.Name(id=a.arg), self.value(rel, d))
        for a, kd in zip(args.kwonlyargs, args.kw_defaults, strict=True):
            if kd is not None:
                self._bind(rel, ast.Name(id=a.arg), self.value(rel, kd))
        runs = rel == self.tree.scenario or (rel, node.name) in self.active
        if runs and (node.name.startswith("test") or self._fixture_name(node)[0]):
            bound = self._parametrized(node)
            for a in [*positional, *args.kwonlyargs]:
                if a.arg in {"self", "cls"} or a.arg in bound or a.arg in SAFE_FIXTURES:
                    continue
                self._use_fixture(rel, node, a.arg)
            for name in self._usefixtures(node):
                self._use_fixture(rel, node, name)
        ret: set[str] = set()
        for sub in ast.walk(node):
            if isinstance(sub, (ast.Return, ast.Yield, ast.YieldFrom)) and sub.value is not None:
                ret |= self.value(rel, sub.value)
        if ret:
            for k in {node.name, f"self.{node.name}"}:
                self.returns[(rel, k)] = self.returns.get((rel, k), NONE) | frozenset(ret)

    def _use_fixture(self, rel: str, node: ast.AST, name: str) -> None:
        defs = self.fixtures.get(name)
        if not defs:
            self._note(f"{rel}:{getattr(node, 'lineno', 0)} uses the fixture {name!r}, which is neither pytest's own "
                       "nor defined in the scenario, the conftest.py files above it or the plugins pytest loads")
            return
        for f, d in defs:  # pytest picks the closest definition; every one is taken to run
            self.active.add((f, d.name))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._bind(rel, ast.Name(id=name), self.returns.get((f, d.name), NONE))

    @staticmethod
    def _usefixtures(node: ast.AST) -> list[str]:
        """`@pytest.mark.usefixtures("a", "b")` on a function or class, and in `pytestmark`."""
        out: list[str] = []
        decorators = list(getattr(node, "decorator_list", []))
        if isinstance(node, ast.Module):
            for st in node.body:
                if isinstance(st, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "pytestmark"
                                                      for t in st.targets):
                    decorators += st.value.elts if isinstance(st.value, (ast.List, ast.Tuple)) else [st.value]
        for d in decorators:
            if isinstance(d, ast.Call) and (_chain(d.func) or [""])[-1] == "usefixtures":
                out += [a.value for a in d.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        return out

    @staticmethod
    def _fixture_name(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, bool]:
        """The fixture's name ("" when it is not one), and whether it is autouse."""
        for d in node.decorator_list:
            c = _chain(d.func if isinstance(d, ast.Call) else d) or []
            if ".".join(c) in {"pytest.fixture", "fixture"}:
                name, auto = node.name, False
                if isinstance(d, ast.Call):
                    for kw in d.keywords:
                        if kw.arg == "name" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                            name = kw.value.value
                        if kw.arg == "autouse" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                            auto = True
                return name, auto
        return "", False

    @staticmethod
    def _parametrized(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
        out: set[str] = set()
        for d in node.decorator_list:
            if isinstance(d, ast.Call) and (_chain(d.func) or [""])[-1] == "parametrize" and d.args:
                first = d.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    out |= {n.strip() for n in first.value.split(",")}
                elif isinstance(first, (ast.List, ast.Tuple)):
                    out |= {str(e.value).strip() for e in first.elts if isinstance(e, ast.Constant)}
        return out

    # ------------------------------------------------------------ the scenario's form
    def _form(self) -> None:
        for rel in self.group:
            mod = self.tree.parse(rel)
            if mod is None:
                continue
            for s in self.imports(rel).stars:
                if not self._outside_code(s):
                    self._note(f"{rel} star-imports {s}: ProofLab cannot follow its names")
            if rel not in self.conftests:
                for st in mod.body:
                    if not (isinstance(st, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef,
                                            ast.ClassDef, ast.Assign, ast.AnnAssign)) or _docstring(st)
                            or _main_guard(st)):
                        self._note(f"{rel}:{st.lineno} runs module-level code ProofLab does not follow")
            for node in ast.walk(mod):
                if isinstance(node, ast.Name) and node.id in _DYNAMIC_NAMES:
                    self._note(f"{rel}:{node.lineno} uses {node.id}: ProofLab cannot follow dynamic names")
                elif isinstance(node, ast.Attribute):
                    c = ".".join(_chain(node) or [])
                    if node.attr == "__dict__" or any(c.startswith(p) or c == p.rstrip(".") for p in _DYNAMIC_CHAINS):
                        self._note(f"{rel}:{node.lineno} uses {c or node.attr}: ProofLab cannot follow dynamic "
                                   "imports or attributes")
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    for d in node.decorator_list:
                        c = ".".join(_chain(d.func if isinstance(d, ast.Call) else d) or [])
                        ok = any(c == p or (p.endswith(".") and c.startswith(p)) for p in _DECORATORS)
                        lit = not isinstance(d, ast.Call) or all(_literal(a) for a in [*d.args,
                                                                                       *(k.value for k in d.keywords)])
                        if not (ok and lit):
                            self._note(f"{rel}:{d.lineno} decorates {node.name} with {c or 'an expression'}"
                                       + ("" if ok else " (not pytest's or unittest's)")
                                       + ("" if lit else " with arguments that are not literals")
                                       + ": ProofLab cannot follow what it supplies")
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self.funcs[rel][node.name] = node
                        self.funcs[rel][f"self.{node.name}"] = node
                        fx, auto = self._fixture_name(node)
                        if fx:
                            self.fixtures.setdefault(fx, []).append((rel, node))
                            if auto:
                                self.active.add((rel, node.name))
                        if node.name in _XUNIT:  # setup_module and the like run without being asked for
                            self.active.add((rel, node.name))
            # every name the scenario imports from test code is taken to run there (an imported setup_module)
            if rel == self.tree.scenario:
                for name, (f, attrs) in self.imports(rel).names.items():
                    if f in self.group:
                        self.active.add((f, attrs[0] if attrs else name))

    # ------------------------------------------------------------ the result
    def _note(self, text: str) -> None:
        if text not in self.findings and len(self.findings) < MAX_FINDINGS:
            self.findings.append(text)

    def check(self) -> list[str]:
        self._import_time()
        self._form()
        scen = self.tree.parse(self.tree.scenario)
        if scen is not None:
            for name in self._usefixtures(scen):
                self._use_fixture(self.tree.scenario, scen, name)
        for _ in range(MAX_PASSES):
            if not self._pass():
                break
        else:
            self._note("the scenario's values did not settle within ProofLab's analysis bound")
        if len(self.entries) > 1:
            self._note("the scenario calls more than one entry point of the repository ("
                       + ", ".join(f"{e.replace(':', ' ')} at {w}" for e, w in sorted(self.entries.items())[:4])
                       + "): one can set up what another reads, so a supported claim needs a scenario that "
                       "exercises one function or class")
        return self.findings


def _names(items: V) -> str:
    out = sorted({i.split(":", 1)[1].replace(":", " ") for i in items})
    return ", ".join(out[:3]) + (" …" if len(out) > 3 else "")


NODE_REASON = ("ProofLab does not parse JavaScript, so it cannot tell whether a node scenario checks the change's "
               "behaviour or only something the change set up for it (Session A's G4): a node claim is never "
               "supported; the observations are recorded")


def findings(scenario: str, kind: str, files: set[str], read: Reader, subject: set[str], cwd: str = "",
             read_base: Reader | None = None) -> list[str]:
    """Why the scenario may not check the change's behaviour, or []."""
    if kind == "node":
        return [NODE_REASON]
    if not subject or kind not in {"pytest", "unittest"} or not scenario.endswith(".py"):
        return []
    return Analysis(scenario, files, read, subject, cwd, read_base).check()

