"""b41 — monkeypatch-the-wrong-binding tripwire.

Why this file exists (the class of bug, twice proven in this repo):
  * test_market_closed_blocks_signal_order patched
    `engines.market_hours.is_market_open`, but auto_executor does
    `from engines.market_hours import is_market_open` at module level —
    the import COPIES the function into the caller's namespace, so the
    patch changed nothing for that caller. The test was vacuous from the
    day it was written and only surfaced when the real market closed
    (2026-08-31, found during b39).
  * The mirror hazard (leak): test_audit_fixes documents that if
    hermes_runtime's FIRST import happens inside a patch window on
    `engines.storage.load_current_plan`, hermes_runtime permanently binds
    the fake at module level — every later real cycle dies on KeyError.
    Patching the SOURCE module is only safe for consumers that import
    LAZILY (inside a function, resolved at call time).

RULE enforced mechanically:
  For every test patch site `MOD.attr = fake` / `patch.object(MOD,'attr')`
  / `setattr(MOD,'attr',...)` where MOD DEFINES attr, find every production
  module that does a MODULE-LEVEL `from MOD import attr` (a shadowing
  binding). For each such consumer:
    (1) LEAK check — the test file must import the consumer at its own
        module level, so the consumer's real binding is captured BEFORE any
        patch window can poison it. No exemption possible; it is cheap.
    (2) VACUITY check — if the consumer references attr as a bare name
        (i.e. uses its own copied binding), the source patch is a NO-OP for
        that code path. That is only acceptable when the test exercises a
        DIFFERENT (lazy-importing) caller — recorded in ALLOWED with a
        reason, and pinned by test_allowed_entries_are_still_real so a
        stale exemption cannot linger as a silent hole.

Patching the CONSUMER's own binding (e.g. `ae.is_market_open = fake`) is
the correct pattern and is deliberately not flagged.

The tripwire is proven to bite: TestTripwireBites feeds it a synthetic
fixture reproducing the exact market_closed bug and asserts it is caught.
"""
from __future__ import annotations

import ast
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO / 'tests'

# Production packages whose module-level bindings tests must respect.
PROD_ROOTS = ['engines', 'notifier', 'execution']
PROD_TOP = ['hermes_runtime.py', 'hermes_master.py', 'position_daemon.py',
            'signal_daemon.py', 'signal_monitor.py', 'bridge_client.py',
            'cli.py', 'env_loader.py']

# (test_file, 'source.module.attr', consumer_module) -> why the source patch
# is still meaningful even though `consumer` holds a module-level copy.
ALLOWED = {
    ('test_b37_guard_visibility.py', 'notifier.telegram.send_ops',
     'hermes_master'):
        'hermes_master.main() uses its own copied binding (lines 189/198/240), '
        'but the path under test — alert_degraded_guards — re-imports send_ops '
        'LAZILY inside the function (b37), so the patch reaches it. No test '
        'calls main(). The leak half is closed by the module-level '
        '`import hermes_master` in that test file.',
    ('test_b40_guard_observability.py', 'notifier.telegram.send_ops',
     'hermes_master'):
        'same shape as the b37 exemption: the writer under test '
        '(alert_degraded_guards) re-imports send_ops LAZILY inside the '
        'function, so the patch reaches it; no test calls main(). The leak '
        'half is closed by the module-level `import hermes_master` in that '
        'file (b41 discipline, stated in its header).',
    ('test_audit_fixes.py', 'engines.storage.load_current_plan',
     'hermes_runtime'):
        'patch targets signal_listener\'s LAZY import (inside run_signal_check); '
        'hermes_runtime keeps the real binding thanks to the up-front '
        '`import hermes_runtime` at the top of that file.',
    ('test_audit_fixes.py', 'engines.storage.append_execution_log',
     'hermes_runtime'):
        'same as load_current_plan: lazy consumer under test, real binding '
        'pre-captured by the up-front import.',
    ('test_failclosed_news_spread.py', 'engines.storage.load_current_plan',
     'hermes_runtime'):
        'same pattern as test_audit_fixes; the file now also pre-imports '
        'hermes_runtime at module level (b41 fix) so the leak half is closed '
        'even when this file runs alone.',
    ('test_failclosed_news_spread.py', 'engines.storage.append_execution_log',
     'hermes_runtime'):
        'same as load_current_plan.',
    ('test_b140_signal_lane_regime.py', 'engines.risk.assess_account_policy',
     'hermes_runtime'):
        'patch targets signal_listener.check_signals\'s LAZY b140 import (the '
        'fail-closed path under test); the sizer\'s module-level binding in '
        'hermes_runtime stays real because BOTH this test file and the census '
        'module import hermes_runtime up front, so the patch can never poison '
        'it even when this file runs alone.',
}


# ───────────────────────── static analysis helpers ─────────────────────────

def _is_module(dotted: str) -> bool:
    """True if `dotted` names an importable module/package (not a function)."""
    try:
        __import__(dotted)
        import importlib
        return importlib.util.find_spec(dotted) is not None
    except Exception:
        return False


def _prod_files(root: Path):
    files = []
    for pkg in PROD_ROOTS:
        files += sorted((root / pkg).glob('*.py'))
    for name in PROD_TOP:
        p = root / name
        if p.exists():
            files.append(p)
    return files


def consumer_map(root: Path) -> dict:
    """{'source.module': {'attr': {consumer_module: uses_bare_name}}}

    Only MODULE-LEVEL (unindented, tree-body) `from source import attr`
    count — a function-level import re-resolves the source attribute on
    every call, which is exactly what makes a source patch work.
    """
    out: dict = {}
    for f in _prod_files(root):
        mod = f.relative_to(root).with_suffix('')
        mod_name = '.'.join(mod.parts)
        try:
            tree = ast.parse(f.read_text(encoding='utf-8'))
        except SyntaxError:
            continue
        shadowed = {}  # attr -> source module it was copied from
        for node in tree.body:  # module level ONLY
            if isinstance(node, ast.ImportFrom) and node.module:
                for a in node.names:
                    if a.name == '*':
                        continue
                    full = f'{node.module}.{a.name}'
                    if _is_module(full):
                        continue  # `from engines import paths` — module obj
                    local = a.asname or a.name
                    shadowed[local] = node.module
        if not shadowed:
            continue
        bare = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for local, src in shadowed.items():
            out.setdefault(src, {})[local] = {
                mod_name: (local in bare)}
    return out


def _alias_table(tree: ast.Module) -> dict:
    """local name -> dotted module, for every import in the file (any depth)."""
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                aliases[a.asname or a.name.split('.')[0]] = a.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for a in node.names:
                if a.name == '*':
                    continue
                aliases[a.asname or a.name] = f'{node.module}.{a.name}'
    return aliases


def _module_level_imports(tree: ast.Module) -> set:
    """Dotted names imported at file top level (executed at collection)."""
    mods = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.add(a.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
            for a in node.names:
                mods.add(f'{node.module}.{a.name}')
    return mods


def _defines_attr(tree: ast.Module, attr: str) -> bool:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)) and node.name == attr:
            return True
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == attr:
                    return True
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.asname or a.name for a in node.names]
            if attr in names:
                return True
    return False


def patch_sites(test_file: Path) -> list:
    """[(dotted_module, attr)] — every place the test replaces a module attr."""
    tree = ast.parse(test_file.read_text(encoding='utf-8'))
    aliases = _alias_table(tree)
    sites = []
    for node in ast.walk(tree):
        # MOD.attr = fake
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if (isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                        and t.value.id in aliases):
                    sites.append((aliases[t.value.id], t.attr))
        # setattr(MOD, 'attr', ...)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == 'setattr' and len(node.args) >= 2
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id in aliases
                and isinstance(node.args[1], ast.Constant)):
            sites.append((aliases[node.args[0].id], node.args[1].value))
        # patch.object(MOD, 'attr') / patch('dotted.attr')
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ('object', 'patch')
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in ('patch', 'mock')):
            args = node.args
            if node.func.attr == 'object' and len(args) >= 2 \
                    and isinstance(args[0], ast.Name) \
                    and args[0].id in aliases \
                    and isinstance(args[1], ast.Constant):
                sites.append((aliases[args[0].id], args[1].value))
            elif node.func.attr == 'patch' and args \
                    and isinstance(args[0], ast.Constant) \
                    and isinstance(args[0].value, str) and '.' in args[0].value:
                target = args[0].value
                mod, _, attr = target.rpartition('.')
                sites.append((mod, attr))
    return sorted(set(sites))


def analyze(root: Path):
    """Return (violations, findings) for the whole repo under `root`."""
    cmap = consumer_map(root)
    violations, findings = [], []
    for tf in sorted((root / 'tests').glob('test_*.py')):
        try:
            tree = ast.parse(tf.read_text(encoding='utf-8'))
        except SyntaxError:
            continue
        top_imports = _module_level_imports(tree)
        for src_mod, attr in patch_sites(tf):
            src_file = root / Path(*src_mod.split('.'))
            src_file = src_file.with_suffix('.py') if src_file.suffix != '.py' else src_file / '__init__.py'
            if not src_file.exists():
                continue
            try:
                src_tree = ast.parse(src_file.read_text(encoding='utf-8'))
            except SyntaxError:
                continue
            if not _defines_attr(src_tree, attr):
                continue  # patching a consumer's own binding — correct pattern
            consumers = cmap.get(src_mod, {}).get(attr, {})
            for consumer, uses_bare in consumers.items():
                key = (tf.name, f'{src_mod}.{attr}', consumer)
                # (1) leak check — unconditional
                if consumer not in top_imports:
                    violations.append(
                        f'{tf.name}: patches {src_mod}.{attr} but does not '
                        f'import the shadowing consumer "{consumer}" at module '
                        f'level — if {consumer} is first imported inside the '
                        f'patch window it permanently binds the fake')
                # (2) vacuity check — only when the consumer uses its copy
                if uses_bare and key not in ALLOWED:
                    violations.append(
                        f'{tf.name}: patches {src_mod}.{attr}, but '
                        f'"{consumer}" from-imports it at module level and '
                        f'calls it by bare name — the patch is a NO-OP for '
                        f'that path (b41). Add an ALLOWED entry with a reason '
                        f'if the test exercises a different (lazy) caller.')
                findings.append((key, uses_bare))
    return violations, findings


# ─────────────────────────────── the checks ────────────────────────────────

class B41PatchBindingAudit(unittest.TestCase):
    def test_no_unaudited_shadowed_patches(self):
        violations, findings = analyze(REPO)
        self.assertEqual(
            violations, [],
            'monkeypatch-the-wrong-binding violations:\n  ' +
            '\n  '.join(violations))
        self.assertGreaterEqual(
            len(findings), len(ALLOWED),
            'audit found fewer shadowed patch sites than ALLOWED entries — '
            'a test file may have stopped parsing (silent tripwire bypass)')

    def test_allowed_entries_are_still_real(self):
        _, findings = analyze(REPO)
        found = {key for key, bare in findings if bare}
        for key in ALLOWED:
            self.assertIn(
                key, found,
                f'ALLOWED entry {key} no longer matches any patch site — '
                f'remove it (a dead exemption hides the next real violation)')

    def test_known_good_patches_are_not_flagged(self):
        """The b39-fixed market_closed patch (consumer binding) must pass."""
        sites = patch_sites(TESTS_DIR / 'test_safety_gates.py')
        self.assertIn(('engines.auto_executor', 'is_market_open'), sites)
        violations, _ = analyze(REPO)
        self.assertFalse([v for v in violations
                          if 'test_safety_gates' in v])


class TestTripwireBites(unittest.TestCase):
    """The audit itself must not be vacuous: a synthetic fixture reproducing
    the exact market_closed bug must be caught by analyze()."""

    def _fixture(self, root: Path):
        (root / 'engines').mkdir(parents=True)
        (root / 'engines' / '__init__.py').write_text('')
        (root / 'engines' / 'clock_mod.py').write_text(
            'def is_open():\n    return True\n')
        (root / 'engines' / 'gate_mod.py').write_text(
            'from engines.clock_mod import is_open\n\n\n'
            'def check():\n    return is_open()\n')
        t = root / 'tests'
        t.mkdir()
        (t / 'test_bad.py').write_text(
            'import engines.clock_mod as cm\n'
            'cm.is_open = lambda: False\n')

    def test_synthetic_vacuous_patch_is_caught(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._fixture(root)
            violations, findings = analyze(root)
            self.assertTrue(any('NO-OP' in v for v in violations),
                            f'tripwire missed the synthetic bug: {violations}')
            self.assertTrue(any('does not import' in v for v in violations),
                            f'tripwire missed the leak hazard: {violations}')
            self.assertIn(
                ('test_bad.py', 'engines.clock_mod.is_open', 'engines.gate_mod'),
                [k for k, _ in findings])

    def test_synthetic_consumer_patch_is_clean(self):
        """Patching the consumer's OWN binding (the b39 fix shape) passes."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._fixture(root)
            (root / 'tests' / 'test_bad.py').write_text(
                'import engines.gate_mod as gm\n'
                'gm.is_open = lambda: False\n')
            violations, _ = analyze(root)
            self.assertEqual(violations, [],
                             f'correct pattern wrongly flagged: {violations}')

    def test_real_historical_bug_shape_is_caught(self):
        """Not synthetic: the ACTUAL pre-b39 test_safety_gates.py (commit
        24a6d3a~1, patched market_hours instead of auto_executor's binding)
        must be flagged by analyze(). If someone weakens the tripwire until
        it misses the very bug it was written for, this goes red."""
        import subprocess
        # Find ANY historical revision of the file that still has the vacuous
        # shape (patched market_hours directly) — robust against rebases.
        revs = subprocess.run(
            ['git', '-C', str(REPO), 'log', '--format=%H', '--',
             'tests/test_safety_gates.py'],
            capture_output=True, text=True).stdout.split()
        old_src = None
        for rev in revs:
            r = subprocess.run(
                ['git', '-C', str(REPO), 'show',
                 f'{rev}:tests/test_safety_gates.py'],
                capture_output=True, text=True)
            if r.returncode == 0 and 'market_hours.is_market_open = ' in r.stdout:
                old_src = r.stdout
                break
        if old_src is None:
            # history rotated (rebase/squash) — skip honestly rather than
            # pass vacuously
            self.skipTest('historical buggy revision no longer reachable')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            import shutil
            for p in ('engines', 'notifier'):
                shutil.copytree(REPO / p, root / p)
                (root / p / '__init__.py').touch()
            for f in PROD_TOP:
                src = REPO / f
                if src.exists():
                    shutil.copy(src, root / f)
            (root / 'tests').mkdir()
            (root / 'tests' / 'test_safety_gates.py').write_text(old_src)
            violations, _ = analyze(root)
            self.assertTrue(
                any('test_safety_gates' in v and 'NO-OP' in v
                    for v in violations),
                f'tripwire missed the real historical bug: {violations}')


if __name__ == '__main__':
    unittest.main()
