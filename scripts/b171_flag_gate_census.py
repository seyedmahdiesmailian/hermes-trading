"""b171 REUSABLE PROCEDURE — writer/reader census for every dict-flag gate key.

The rule (filed by b170, 2026-09-09): a reader-side source pin proves
NOTHING about whether a flag-keyed gate is live. `d.get(flag)` can only fire
if some PRODUCTION writer sets that exact key; conversely a writer that no
production reader ever consults is a veto nobody can see. Both halves of the
census must run in the SAME pass, or the mismatch hides for months
(blocked_by_macro shipped dead for exactly that reason).

This script walks every non-test, non-legacy, non-scripts .py file with `ast`
and reports per flag key:
  writers     — dict-literal keys, subscript stores, setdefault, update()
  readers     — .get()/[]/pop loads and `key in d` compares
  verdict     — LIVE (writers+readers), DEAD (no writer), WRITE-ONLY (no reader)

Read-only: prints a report, writes nothing. Exit code 0 always; the paired
test (tests/test_b171_flag_gate_census.py) turns the verdicts into pins.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Flag keys named by the b171 rule (both lanes): entry vetoes, guard
# degradation, DEFCON permission bits.
FLAGS = [
    "blocked",
    "blocked_by_macro",
    "spread_blocked",
    "calendar_unavailable",
    "macro_blocked",
    "stale_rates",
    "stale_tick",
    "stale",
    "degraded",
    "unavailable",
    "trade_allowed",
    "runner_allowed",
    "scale_in_allowed",
    # b172 (2026-09-09): the REPORT-DICT family. b171's rule says the census
    # must run both ways over the keys the runtime WRITES for reporting too —
    # a write-only veto is an observability defect exactly like a read-only
    # gate is a wiring defect. skip_reason/skip_reasons/reasons are the
    # Telegram/brief carriers; degraded is the calendar's "served from an aged
    # cache because both live sources failed" bit.
    "skip_reason",
    "skip_reasons",
    "reasons",
]

EXCLUDE_PARTS = ("legacy", "tests", "scripts", ".git", ".venv", "node_modules")


def production_sources():
    for p in sorted(ROOT.rglob("*.py")):
        rel = str(p.relative_to(ROOT))
        parts = rel.replace("\\", "/").split("/")
        if any(part in EXCLUDE_PARTS or "legacy" in part for part in parts[:-1]) \
                or rel.split("/")[0] in EXCLUDE_PARTS:
            continue
        if "legacy" in rel:
            continue
        yield rel, p


def const_str(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def reads_same_key(node, name):
    """Value of a dict-literal entry that just copies the key back in."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                and sub.func.attr in ("get", "pop") and sub.args \
                and const_str(sub.args[0]) == name:
            return True
        if isinstance(sub, ast.Subscript) and const_str(sub.slice) == name:
            return True
    return False


class _Walk(ast.NodeVisitor):
    def __init__(self, rel, flags=None):
        self.rel = rel
        # b172: the census must filter against the CALLER's wanted set.
        # `census(flags=[...])` used to narrow only the reporting loop while
        # the walker kept comparing against the module-level FLAGS — so a
        # census over any NEW key (skip_reason, reasons, degraded beyond the
        # default list) returned all-zero writer/reader sets that READ like
        # "DEAD-NO-WRITER" findings but were an artifact of the tool.
        self.flags = set(flags if flags is not None else FLAGS)
        self.sites = []  # (flag, 'W'|'R'|'P', lineno)

    def visit_Dict(self, node):
        for k, v in zip(node.keys, node.values):
            name = const_str(k)
            if name in self.flags:
                kind = "P" if reads_same_key(v, name) else "W"
                self.sites.append((name, kind, k.lineno))
        self.generic_visit(node)

    def visit_Subscript(self, node):
        name = const_str(node.slice)
        if name in self.flags:
            if isinstance(node.ctx, ast.Store):
                self.sites.append((name, "W", node.lineno))
            elif isinstance(node.ctx, ast.Load):
                self.sites.append((name, "R", node.lineno))
        self.generic_visit(node)

    def visit_Call(self, node):
        f = node.func
        if isinstance(f, ast.Attribute):
            if f.attr in ("get", "pop") and node.args:
                name = const_str(node.args[0])
                if name in self.flags:
                    self.sites.append((name, "R", node.lineno))
            elif f.attr == "setdefault" and node.args:
                name = const_str(node.args[0])
                if name in self.flags:
                    self.sites.append((name, "W", node.lineno))
            elif f.attr == "update":
                for a in node.args:
                    if isinstance(a, ast.Dict):
                        for k in a.keys:
                            name = const_str(k)
                            if name in self.flags:
                                self.sites.append((name, "W", node.lineno))
                for kw in node.keywords:
                    if kw.arg in self.flags:
                        self.sites.append((kw.arg, "W", node.lineno))
        self.generic_visit(node)

    def visit_Compare(self, node):
        if any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
            name = const_str(node.left)
            if name in self.flags:
                self.sites.append((name, "R", node.lineno))
        self.generic_visit(node)


def census(flags=None):
    """Return {flag: {'writers': [...], 'readers': [...], 'passthrough': [...]}}."""
    wanted = set(flags or FLAGS)
    out = {f: {"writers": set(), "readers": set(), "passthrough": set()}
           for f in wanted}
    n_files = 0
    for rel, p in production_sources():
        n_files += 1
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        w = _Walk(rel, wanted)
        w.visit(tree)
        for flag, kind, lineno in w.sites:
            if flag not in wanted:
                continue
            site = f"{rel}:{lineno}"
            bucket = {"W": "writers", "R": "readers",
                      "P": "passthrough"}[kind]
            out[flag][bucket].add(site)
    out["_meta"] = {"files": n_files}
    return out


def verdict(info):
    w = info["writers"] - info["passthrough"]
    r = info["readers"]
    if not w:
        return "DEAD-NO-WRITER"
    if not r:
        return "WRITE-ONLY"
    return "LIVE"


def main():
    data = census()
    print(f"censused {data['_meta']['files']} production files "
          f"(tests/legacy/scripts excluded)\n")
    print(f"{'FLAG':22} {'W':>3} {'R':>3}  VERDICT")
    print("-" * 70)
    for f in FLAGS:
        info = data[f]
        v = verdict(info)
        print(f"{f:22} {len(info['writers']):>3} {len(info['readers']):>3}  {v}")
        for s in sorted(info["writers"])[:4]:
            print(f"{'':24}W {s}")
        for s in sorted(info["readers"])[:4]:
            print(f"{'':24}R {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
