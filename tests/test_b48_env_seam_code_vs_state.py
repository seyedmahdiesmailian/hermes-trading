"""b48 — test-seam env vars must redirect STATE, never CODE.

The incident (proven, during b47): the first draft of
scripts/autopilot_harvest.py did

    ROOT = Path(os.getenv('HERMES_REPO_ROOT', '/home/ai/hermes-trading'))
    sys.path.insert(0, str(ROOT))
    from engines import dirty_work

A test pointing HERMES_REPO_ROOT at a throwaway repo therefore made the
IMPORT itself die — the seam redirected CODE, not state. And because the
script's own fail-safe (`except Exception: pass`, required so a broken
check never blocks the autopilot run) swallowed the ImportError, the
feature silently printed nothing: the b36-shape test went RED with an
empty string instead of a crash. Two layers of "defensive" design stacked
into the worst failure mode: a silent no-op that looks like "nothing to
do".

The correct shape (autopilot_harvest.py today, autopilot_digest.py):
separate CODE_ROOT (fixed, real repo, the ONLY thing ever inserted into
sys.path) from SCAN_ROOT (the env var, consumed as DATA by the scanner).

RULE enforced mechanically (AST, same family as b41/b42/b44 tripwires):
  For every production script (scripts/*.py + root-level *.py) that reads
  a HERMES_*_ROOT env var (os.environ.get/[]/setdefault or os.getenv with
  a HERMES_*_ROOT key — including HERMES_DATA_ROOT), no variable holding
  that value — directly or through an alias chain — may appear in a
  sys.path.insert/append argument. The env var may build data paths
  freely; it may never decide where code is imported from.

Pinned here:
  * analyzer catches the direct shape, the alias-chain shape, and the
    `from sys import path` shape; a clean CODE_ROOT/SCAN_ROOT script and
    an env var used only for data paths are NOT flagged (anti-vacuity);
  * the REAL repo is violation-free, and the two named seam users
    (autopilot_digest, autopilot_harvest) are proven to be parsed and to
    carry the correct shape — so a dead scan or a regression that merges
    SCAN back into the sys.path insert is caught;
  * minimum-findings count: at least 2 scripts must be seen reading a
    HERMES_*_ROOT, so a broken parse can't pass by finding nothing;
  * BEHAVIOURAL proof of the exact silent-death mode: run the real
    harvester with HERMES_REPO_ROOT at a directory that contains a
    broken `engines/` shadowing package — if the seam ever leaks into
    sys.path again, the import resolves to the throwaway tree, the
    fail-safe eats it, and STEP 0 vanishes. Today the fixed CODE_ROOT
    makes the output identical to the normal run.
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

ROOT_ENV_RE = re.compile(r'^HERMES_.*_ROOT$')


def _root_env_keys(node: ast.AST) -> list[str]:
    """Keys of os.environ.get('HERMES_*_ROOT') / os.environ[...] /
    os.getenv('HERMES_*_ROOT') / os.environ.setdefault(...) calls."""
    if not isinstance(node, ast.Call):
        return []
    f = node.func
    parts = None
    if isinstance(f, ast.Attribute):
        base = f.value
        base_name = base.id if isinstance(base, ast.Name) else None
        if base_name == 'os' or base_name == 'environ':
            parts = (base_name, f.attr)
        elif isinstance(base, ast.Attribute) and \
                isinstance(base.value, ast.Name) and base.value.id == 'os' \
                and base.attr == 'environ':
            parts = ('os.environ', f.attr)
    elif isinstance(f, ast.Name):
        if f.id in ('getenv', 'environ'):
            parts = ('bare', f.id)
    if parts is None:
        return []
    attr = parts[1]
    if attr not in ('get', 'getenv', '__getitem__', 'setdefault'):
        return []
    if not node.args:
        return []
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str) \
            and ROOT_ENV_RE.match(first.value):
        return [first.value]
    return []


def _root_env_subscripts(tree: ast.AST) -> list[str]:
    """os.environ['HERMES_*_ROOT'] reads (ast.Subscript, not a Call)."""
    hits = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Subscript):
            continue
        v = n.value
        is_env = (isinstance(v, ast.Attribute) and v.attr == 'environ'
                  and isinstance(v.value, ast.Name) and v.value.id == 'os') \
            or (isinstance(v, ast.Name) and v.id == 'environ')
        if not is_env:
            continue
        sl = n.slice
        if isinstance(sl, ast.Constant) and isinstance(sl.value, str) \
                and ROOT_ENV_RE.match(sl.value):
            hits.append(sl.value)
    return hits


def _call_root_env_keys(node: ast.AST) -> list[str]:
    """env keys read anywhere in an expression, incl. subscript form."""
    keys = []
    for sub in ast.walk(node):
        keys.extend(_root_env_keys(sub))
        keys.extend(_root_env_subscripts(sub))
    return keys


def _syspath_call_targets(node: ast.AST) -> list[ast.expr]:
    """If node is sys.path.insert(...)/sys.path.append(...) (or the
    `from sys import path` shape), return its argument expressions."""
    if not isinstance(node, ast.Call) or not isinstance(node.func,
                                                        ast.Attribute):
        return []
    if node.func.attr not in ('insert', 'append'):
        return []
    f = node.func.value
    is_syspath = (isinstance(f, ast.Attribute) and f.attr == 'path'
                  and isinstance(f.value, ast.Name) and f.value.id == 'sys') \
        or (isinstance(f, ast.Name) and f.id == 'path')
    if not is_syspath:
        return []
    return list(node.args)


def analyze_source(src: str, name: str = '<memory>') -> list[dict]:
    """Return violations: sys.path mutations whose args reference a
    variable transitively holding a HERMES_*_ROOT env value."""
    tree = ast.parse(src, filename=name)

    # names imported bare from sys (e.g. `from sys import path`)
    sys_bare = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module == 'sys':
            for a in n.names:
                if a.name == 'path':
                    sys_bare.add(a.asname or a.name)

    env_vars: dict[str, str] = {}   # var -> env key it holds
    aliases: dict[str, str] = {}    # var -> source var (x = y chain)
    violations = []

    def resolve(var: str, depth: int = 0) -> str | None:
        if depth > 10:
            return None
        if var in env_vars:
            return env_vars[var]
        if var in aliases:
            return resolve(aliases[var], depth + 1)
        return None

    def expr_env_key(expr: ast.expr) -> str | None:
        """Env key directly readable from an expression (Call/subscript or
        a Name that transitively holds one)."""
        keys = _call_root_env_keys(expr)
        if keys:
            return keys[0]
        if isinstance(expr, ast.Name):
            return resolve(expr.id)
        if isinstance(expr, ast.Call):  # Path(env_var) / str(env_var)
            for a in list(expr.args) + [kw.value for kw in expr.keywords]:
                k = expr_env_key(a)
                if k:
                    return k
        if isinstance(expr, ast.JoinedStr):  # f-string seam
            for v in expr.values:
                k = expr_env_key(v) if isinstance(v, ast.FormattedValue) \
                    else None
                if k:
                    return k
        if isinstance(expr, ast.BinOp):
            return expr_env_key(expr.left) or expr_env_key(expr.right)
        return None

    # pass 1+2: collect env vars and aliases (statement order matters for
    # aliases defined before use; iterate to fixed point for forward refs)
    assigns = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)]
    for _ in range(5):  # fixed point for alias chains
        changed = False
        for n in assigns:
            targets = [t.id for t in n.targets if isinstance(t, ast.Name)]
            if len(targets) != 1:
                continue
            var = targets[0]
            k = expr_env_key(n.value)
            if k and var not in env_vars:
                env_vars[var] = k
                changed = True
            elif isinstance(n.value, ast.Name) and resolve(n.value.id) \
                    and var not in env_vars and var not in aliases:
                aliases[var] = n.value.id
                changed = True
        if not changed:
            break

    # pass 3: any sys.path mutation whose args reference a tainted name
    for n in ast.walk(tree):
        for arg in _syspath_call_targets(n):
            for sub in ast.walk(arg):
                bad = None
                if isinstance(sub, ast.Name) and resolve(sub.id):
                    bad = f"variable '{sub.id}' (holds ${{{resolve(sub.id)}}})"
                elif _call_root_env_keys(sub):
                    bad = f"direct read of ${{{ _call_root_env_keys(sub)[0] }}}"
                if bad:
                    violations.append({
                        'file': name, 'line': getattr(n, 'lineno', 0),
                        'why': bad,
                    })
                    break

    # also flag: env var used to build the value that is inserted, even
    # when the insert arg is a fresh Name assigned from it two lines up —
    # covered by alias chain above. Sanity: bare `path` import + insert.
    return violations


def production_scripts() -> list[Path]:
    files = sorted((REPO / 'scripts').glob('*.py'))
    files += sorted(REPO.glob('*.py'))
    return [f for f in files if f.name != '__init__.py']


def reads_root_env(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except (SyntaxError, OSError):
        return False
    for n in ast.walk(tree):
        if _call_root_env_keys(n):
            return True
    return False


class TripwireAnalyzer(unittest.TestCase):
    """The analyzer itself, against synthetic fixtures — proven to bite."""

    def test_direct_env_seam_into_syspath_is_flagged(self):
        src = (
            "import os, sys\n"
            "ROOT = os.getenv('HERMES_REPO_ROOT', '/x')\n"
            "sys.path.insert(0, str(ROOT))\n"
            "from engines import dirty_work\n")
        v = analyze_source(src, 'bad_direct.py')
        self.assertEqual(len(v), 1, v)
        self.assertIn('HERMES_REPO_ROOT', v[0]['why'])

    def test_alias_chain_is_flagged(self):
        src = (
            "import os, sys\n"
            "from pathlib import Path\n"
            "SEAM = os.environ.get('HERMES_DATA_ROOT')\n"
            "P = Path(SEAM)\n"
            "Q = P\n"
            "sys.path.insert(0, str(Q))\n")
        v = analyze_source(src, 'bad_alias.py')
        self.assertEqual(len(v), 1, v)
        self.assertIn('HERMES_DATA_ROOT', v[0]['why'])

    def test_from_sys_import_path_shape_is_flagged(self):
        src = (
            "import os\n"
            "from sys import path\n"
            "R = os.environ['HERMES_REPO_ROOT']\n"
            "path.insert(0, str(R))\n")
        self.assertEqual(len(analyze_source(src, 'bad_bare.py')), 1)

    def test_env_read_without_syspath_is_clean(self):
        # the LEGITIMATE shape: env var builds DATA paths only
        src = (
            "import os, sys\n"
            "sys.path.insert(0, '/home/ai/hermes-trading')\n"
            "REPO = os.getenv('HERMES_REPO_ROOT', '/home/ai/hermes-trading')\n"
            "STATE = REPO / 'data/ops/state.json'\n"
            "from engines import dirty_work\n"
            "dirty_work.scan(REPO)\n")
        self.assertEqual(analyze_source(src, 'good.py'), [])

    def test_fixed_code_root_insert_is_clean(self):
        src = (
            "import os, sys\n"
            "from pathlib import Path\n"
            "ROOT = Path(__file__).resolve().parent.parent\n"
            "sys.path.insert(0, str(ROOT))\n"
            "REPO = Path(os.getenv('HERMES_REPO_ROOT', str(ROOT)))\n")
        self.assertEqual(analyze_source(src, 'good2.py'), [])


class RealRepoAudit(unittest.TestCase):
    def test_no_production_script_leaks_root_env_into_syspath(self):
        bad = []
        for f in production_scripts():
            try:
                v = analyze_source(f.read_text(), f.name)
            except SyntaxError:
                continue
            bad.extend(v)
        self.assertEqual(bad, [],
                         'test-seam env var used as a CODE path: '
                         + '; '.join(f"{b['file']}:{b['line']} {b['why']}"
                                     for b in bad))

    def test_seam_users_are_actually_parsed_and_clean(self):
        # anti-vacuity: the two named HERMES_REPO_ROOT users must be seen
        # by the scan (reads the env var) and must insert a NON-env root.
        seen = [f.name for f in production_scripts() if reads_root_env(f)]
        self.assertIn('autopilot_digest.py', seen)
        self.assertIn('autopilot_harvest.py', seen)
        for name in ('autopilot_digest.py', 'autopilot_harvest.py'):
            src = (REPO / 'scripts' / name).read_text()
            self.assertEqual(analyze_source(src, name), [])

    def test_minimum_findings_so_a_dead_scan_cannot_pass(self):
        seen = [f.name for f in production_scripts() if reads_root_env(f)]
        self.assertGreaterEqual(len(seen), 2,
                                'the seam scan found almost nothing — it is '
                                'probably broken, not the repo being clean')

    def test_harvest_code_root_is_hardcoded_not_env_derived(self):
        # the whole b48 lesson in one line: CODE_ROOT must never become
        # SCAN_ROOT again (b47's first draft did exactly this).
        src = (REPO / 'scripts' / 'autopilot_harvest.py').read_text()
        tree = ast.parse(src)
        code_root_value = None
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == 'CODE_ROOT'
                    for t in n.targets):
                code_root_value = n.value
        self.assertIsNotNone(code_root_value, 'CODE_ROOT vanished')
        consts = [c.value for c in ast.walk(code_root_value)
                  if isinstance(c, ast.Constant)]
        self.assertIn('/home/ai/hermes-trading', consts,
                      'CODE_ROOT must be the fixed real repo path')
        self.assertEqual(_call_root_env_keys(code_root_value), [],
                         'CODE_ROOT must not read any env var')


class SilentDeathBehavioural(unittest.TestCase):
    """The failure mode the tripwire guards: seam points at a tree whose
    engines/ package SHADOWS the real one with a broken module. If the
    env var ever reaches sys.path, `from engines import dirty_work`
    resolves into the throwaway tree, raises, the script's fail-safe
    swallows it, and STEP 0 silently disappears — a test would see an
    empty string, not a crash."""

    def _run(self, repo_root, extra_path=None):
        env = dict(os.environ)
        env['HERMES_REPO_ROOT'] = str(repo_root)
        r = subprocess.run(
            [sys.executable, str(REPO / 'scripts/autopilot_harvest.py')],
            capture_output=True, text=True, timeout=60, env=env,
            cwd=str(REPO))
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        return r.stdout

    def _abandoned_repo(self, root: Path):
        (root / 'tests').mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        subprocess.run(['git', 'config', 'user.email', 't@t'], cwd=root,
                       check=True)
        subprocess.run(['git', 'config', 'user.name', 't'], cwd=root,
                       check=True)
        p = root / 'tests/leftover.py'
        p.write_text('# finished, never committed\n')
        subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
        subprocess.run(['git', 'commit', '-qm', 'base'], cwd=root,
                       check=True)
        p.write_text('# plus unstaged edits\n')
        ts = (datetime.now(timezone.utc)
              - timedelta(minutes=180)).timestamp()
        os.utime(p, (ts, ts))
        return p

    def test_broken_shadow_engines_package_cannot_silence_the_harvest(self):
        with tempfile.TemporaryDirectory(prefix='b48_shadow_') as td:
            root = Path(td)
            self._abandoned_repo(root)
            # a package that would EXPLODE on import if it shadowed the
            # real engines/ (the b47 first-draft failure, made loud here)
            eng = root / 'engines'
            eng.mkdir()
            (eng / '__init__.py').write_text(
                'raise RuntimeError("shadow engines imported — the seam '
                'leaked into sys.path")\n')
            (eng / 'dirty_work.py').write_text('raise RuntimeError("x")\n')
            out = self._run(root)
            self.assertIn('STEP 0', out,
                          'harvest went silent with a shadowing engines/ '
                          'in the seam root — CODE is being imported from '
                          'the STATE path again')
            self.assertIn('tests/leftover.py', out)


if __name__ == '__main__':
    unittest.main()
