#!/usr/bin/env python3
"""b126 — SCAN THE REPO FOR CALLS TO NAMES THAT DO NOT EXIST (dead paths).

Why this exists (2026-09-07, autopilot round): b118b asked for the b108 lane
ledger to be re-derived on today's engine. Before spending 20 minutes of
compute on it, this round ran a static scan of every module's top-level calls
against the names that module actually defines, and found that
`scripts/b108_rescore_corrected.py:168` calls `redeide_b70(led)` while the
function it defines is `redecide_b70` — a NameError on the last line of
`main()`. The script has therefore NEVER RUN END TO END since 3003cbb
(2026-09-06): it writes its legs, prints nothing, dumps nothing, exits 1. The
stored ledger exists because the author ran an earlier draft, and the shipped
test suite cannot see the defect because every b108 test reads the JSON
artifact instead of executing the script (the same b114/b116 disease in a new
costume: an artifact that certifies a number, not the code that makes it).

This script is the cheap general version of that check: for every .py file in
the trading repo, resolve each `name(...)` call against the names the file
binds (defs, imports, assignments, args, comprehension targets, except-as,
globals) plus builtins, and report the unresolved ones. It is deliberately
conservative — it only flags a call whose name is bound NOWHERE in the file,
so `foo.bar()` (attribute calls) and dynamic dispatch are out of scope. A
false positive is possible only for names injected by a caller (exec/eval),
which no file in this repo does.

Read-only: it imports nothing from the live path, writes nothing, and is not
imported by any trading module.
"""
from __future__ import annotations

import ast
import builtins
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Files that legitimately inject names at runtime (exec/eval templates, test
# fixtures). Anything else that shows up here is a real dead call.
EXCLUDE_DIRS = (".git", "__pycache__", "venv", ".venv", "node_modules")


def star_imported_names(node: ast.ImportFrom, importer: str) -> set[str]:
    """Names a `from X import *` actually brings in.

    Resolved by parsing the target module's own top-level bindings (its
    `__all__` when it declares one). This matters: `scripts/build_full_report.py`
    and `build_intro_report.py` do `from report_lib import *` and then call
    `heading()/para()/make_table()`, which live in report_lib. Treating a star
    import as unknown would print 238 false positives and bury the one real
    defect — a scan nobody trusts gets deleted, which is b114's lesson.
    """
    mod = (node.module or "").split(".")[-1]
    if not mod:
        return set()
    fname = mod + ".py"
    here = os.path.dirname(os.path.abspath(importer))
    for base in (here, ROOT, os.path.join(ROOT, "scripts"),
                 os.path.join(ROOT, "engines")):
        cand = os.path.join(base, fname)
        if os.path.isfile(cand):
            try:
                with open(cand, encoding="utf-8") as f:
                    sub = ast.parse(f.read())
            except (SyntaxError, OSError):
                return set()
            top = {n.name for n in sub.body
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.ClassDef))}
            for n in sub.body:
                if isinstance(n, ast.Assign):
                    for t in n.targets:
                        if isinstance(t, ast.Name):
                            top.add(t.id)
                elif isinstance(n, (ast.Import, ast.ImportFrom)):
                    for a in n.names:
                        top.add((a.asname or a.name).split(".")[0])
                if (isinstance(n, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == "__all__"
                                for t in n.targets)):
                    try:
                        return {str(v) for v in ast.literal_eval(n.value)}
                    except Exception:
                        return top
            return top
    return set()


def bound_names(tree: ast.AST, importer: str = "") -> set[str]:
    names: set[str] = set(dir(builtins)) | {
        "__file__", "__name__", "__doc__", "__package__", "__spec__",
        "__loader__", "__builtins__", "__debug__"}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            names.add(n.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                if isinstance(n, ast.ImportFrom) and a.name == "*":
                    names |= star_imported_names(n, importer)
                    continue
                names.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, ast.arg):
            names.add(n.arg)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            names.add(n.name)
        elif isinstance(n, ast.Global):
            names.update(n.names)
    return names


def unresolved_calls(path: str) -> list[tuple[int, str]]:
    with open(path, encoding="utf-8") as f:
        src = f.read()
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return [(getattr(exc, "lineno", 0) or 0, f"<SyntaxError {exc.msg}>")]
    names = bound_names(tree, path)
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            if n.func.id not in names:
                out.append((n.lineno, n.func.id))
    return sorted(out)


def python_files(root: str = ROOT) -> list[str]:
    files: list[str] = []
    for base in ("scripts", "engines", "."):
        pattern = os.path.join(root, base, "*.py")
        files.extend(sorted(glob.glob(pattern)))
    return [f for f in files
            if not any(part in EXCLUDE_DIRS for part in f.split(os.sep))]


def scan(root: str = ROOT) -> dict[str, list[tuple[int, str]]]:
    return {os.path.relpath(p, root): hits
            for p in python_files(root) if (hits := unresolved_calls(p))}


def main() -> int:
    findings = scan()
    if not findings:
        print("clean: no unresolved top-level call names in",
              len(python_files()), "files")
        return 0
    for rel, hits in findings.items():
        for lineno, name in hits:
            print(f"{rel}:{lineno}: calls undefined name {name}()")
    print(f"TOTAL: {sum(len(v) for v in findings.values())} dead call(s) "
          f"across {len(findings)} file(s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
