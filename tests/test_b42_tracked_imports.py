"""b42 — clean-checkout import integrity tripwire.

Why this file exists (proven, not hypothetical):
  On 2026-08-31 the b40 work added engines/guard_status.py and wired
  hermes_master.py to import it, but committed with `git commit -am ...` —
  which stages MODIFICATIONS to tracked files and silently skips NEW
  untracked files. HEAD (88cac1e) therefore imported a module that was not
  in the repository: a fresh clone/checkout died with ModuleNotFoundError on
  import, and every 15-min cron master tick would have died with it. The
  tree only healed one commit later (c5b1d92).

RULE enforced mechanically:
  For every git-TRACKED production .py file (tests/, legacy_backup/,
  legacy_removed/, backups/ excluded), AST-scan every `import X` /
  `from X import y` / relative import. A first-party module is one whose
  top-level name resolves to a tracked module or package. Every first-party
  dotted path must resolve to a file in THAT SAME tracked set — a module
  that exists only on this disk but not in git is exactly the 88cac1e hole.
  The scan runs TWICE: against the working tree (catches the hole BEFORE
  the commit) and against the HEAD tree (catches a commit that is already
  broken — the 88cac1e shape is invisible from a dirty disk, because the
  missing file exists locally the whole time). Plus a companion check: no
  untracked .py anywhere in the repo (git add -A is the rule; this makes
  skipping it loud even when nothing imports the file yet).

Hole found while finishing this item (2026-08-31): the HEAD-tree scan
crashed on `from bridge_client import BridgeClient` — bridge_client.py is
a plain module, get_src('bridge_client/__init__.py') raised RuntimeError
from `git show` and only OSError/KeyError were caught. Fixed + pinned.

Proof it bites:
  * test_broken_commit_is_flagged replays the ACTUAL 88cac1e tree through
    the same analyzer and asserts hermes_master.py -> engines.guard_status
    is flagged (b41-style: real history, not a strawman).
  * test_synthetic_untracked_import_is_flagged pins the analyzer on a tiny
    in-memory fixture so it cannot rot into a no-op if git output changes.
  * test_scan_actually_scans asserts a minimum number of files and import
    statements were parsed, so a silently-unparsed tree can't pass vacuously.
"""
from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[1]

# Directories that are not production code and must not be scanned.
EXCLUDED_PREFIXES = ('tests/', 'legacy_backup/', 'legacy_removed/', 'backups/')

# The real broken commit found while verifying b40 (see header).
BROKEN_COMMIT = '88cac1e'


def _git(*args: str) -> str:
    r = subprocess.run(['git', *args], cwd=REPO, capture_output=True,
                       text=True)
    if r.returncode != 0:
        raise RuntimeError(f'git {" ".join(args)} failed: {r.stderr.strip()}')
    return r.stdout


def tracked_files(ref: str | None = None) -> set:
    """Set of repo-relative paths tracked at HEAD (index) or at `ref`."""
    if ref is None:
        out = _git('ls-files')
    else:
        out = _git('ls-tree', '-r', '--name-only', ref)
    return {line.strip() for line in out.splitlines() if line.strip()}


def importable_paths(tracked: set) -> set:
    """Dotted-path-as-slash strings that the tracked set provides.

    'engines/paths.py' -> 'engines/paths'; a package needs its __init__.py
    tracked, so 'engines/__init__.py' -> 'engines'. Untracked directories
    (e.g. a stray data dir) never become modules.
    """
    mods = set()
    for p in tracked:
        if not p.endswith('.py'):
            continue
        if p.endswith('/__init__.py'):
            mods.add(p[:-len('/__init__.py')])
        elif p == '__init__.py':
            continue
        else:
            mods.add(p[:-len('.py')])
    return mods


def prod_files(tracked: set) -> list:
    return sorted(p for p in tracked
                  if p.endswith('.py')
                  and not p.startswith(EXCLUDED_PREFIXES))


# Source extensions whose absence from git breaks a fresh checkout. .py is
# the b42 class; .sh was added by b44 after scripts/verify_head.sh — the
# b44 deliverable itself — sat untracked (a .py-only scan cannot see a
# shell script: nothing imports it).
STRAY_SOURCE_SUFFIXES = ('.py', '.sh')


def stray_source_files(git_others_listing: str) -> list:
    """Repo-relative untracked SOURCE files from a
    `git ls-files --others --exclude-standard` listing."""
    return sorted(l.strip() for l in git_others_listing.splitlines()
                  if l.strip().endswith(STRAY_SOURCE_SUFFIXES))


def _resolve(dotted_slash: str, importables: set):
    """Return (resolved_prefix, exact). exact=True means the FULL slash
    path itself is a tracked module/package."""
    parts = dotted_slash.split('/')
    for i in range(len(parts), 0, -1):
        prefix = '/'.join(parts[:i])
        if prefix in importables:
            return prefix, i == len(parts)
    return None, False  # not first-party at all (stdlib/third-party)


def _defines_name(src: str, name: str) -> bool:
    """Module-level def/class/assign/import alias, or any star import
    (conservative bail-out: re-exports may be dynamic)."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return True
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)) and node.name == name:
            return True
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return True
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                if a.name == '*':
                    return True
                if (a.asname or a.name.split('.')[0]) == name:
                    return True
    return False


def untracked_first_party_imports(rel_path: str, src: str,
                                  importables: set,
                                  get_src=None) -> list:
    """[(lineno, dotted_module)] — first-party imports that do NOT resolve
    inside `importables`. `rel_path` is repo-relative, used for relative
    imports. `get_src(path)` reads a tracked file (needed to tell a
    submodule from a re-exported attribute in `from pkg import name`)."""
    if get_src is None:
        def get_src(path):
            return (REPO / path).read_text(encoding='utf-8')
    bad = []
    tree = ast.parse(src)
    pkg_dir = '/'.join(rel_path.split('/')[:-1])

    def check(dotted_slash: str, lineno: int):
        if not dotted_slash:
            return
        prefix, exact = _resolve(dotted_slash, importables)
        if prefix is not None and not exact:
            bad.append((lineno, dotted_slash.replace('/', '.')))

    def check_from_name(root_slash: str, name: str, lineno: int):
        """`from <root> import <name>`: name is only a violation if root is
        a tracked PACKAGE and name is neither a tracked submodule nor a
        module-level name defined in that package's __init__."""
        if not root_slash:
            return
        prefix, exact = _resolve(root_slash, importables)
        if prefix is None or not exact:
            return  # root itself already flagged (or third-party)
        child = f'{root_slash}/{name}'
        if child in importables:
            return  # tracked submodule
        try:
            init = get_src(root_slash + '/__init__.py')
        except Exception:
            # root is a PLAIN module (e.g. `from bridge_client import X`):
            # name is an attribute of it, not a missing submodule. Must be
            # broad — via a git ref a missing blob raises RuntimeError from
            # _git, not OSError (this exact hole made analyze_ref('HEAD')
            # crash on first use, 2026-08-31).
            init = None
        if init is None:
            return
        if _defines_name(init, name):
            return  # re-exported attribute
        bad.append((lineno, child.replace('/', '.')))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                check(a.name.replace('.', '/'), node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg_dir
                for _ in range(node.level - 1):
                    base = '/'.join(base.split('/')[:-1])
                root = '/'.join(x for x in
                                (base, (node.module or '').replace('.', '/'))
                                if x)
                check(root, node.lineno)
                for a in node.names:
                    if a.name != '*':
                        check_from_name(root, a.name, node.lineno)
            else:
                root = (node.module or '').replace('.', '/')
                check(root, node.lineno)
                for a in node.names:
                    if a.name != '*':
                        check_from_name(root, a.name, node.lineno)
    return bad


def analyze_ref(ref: str | None) -> list:
    """Scan every tracked production file AT `ref` (None = working tree)."""
    tracked = tracked_files(ref)
    importables = importable_paths(tracked)

    if ref is None:
        def get_src(path):
            return (REPO / path).read_text(encoding='utf-8')
    else:
        def get_src(path):
            return _git('show', f'{ref}:{path}')

    findings = []
    n_imports = 0
    for p in prod_files(tracked):
        src = get_src(p)
        if not src.strip():
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        n_imports += sum(1 for n in ast.walk(tree)
                         if isinstance(n, (ast.Import, ast.ImportFrom)))
        for lineno, mod in untracked_first_party_imports(
                p, src, importables, get_src=get_src):
            findings.append((p, lineno, mod))
    analyze_ref.last_import_count = n_imports
    analyze_ref.last_file_count = len(prod_files(tracked))
    return findings


class TestTrackedImports(unittest.TestCase):
    def test_head_is_import_complete(self):
        """The rule: no tracked production module may import a first-party
        module that is not itself tracked."""
        findings = analyze_ref(None)
        self.assertEqual(
            findings, [],
            'tracked production files import modules missing from git '
            f'(a fresh checkout would crash): {findings}')

    def test_head_commit_itself_is_import_complete(self):
        """Same rule against the COMMITTED tree, not the working tree.

        This is the half that actually kills production: cron and any
        fresh checkout read HEAD, never this disk. `git commit -am` leaves
        the working tree perfect and HEAD broken (88cac1e), so a
        working-tree-only check is not enough.
        """
        findings = analyze_ref('HEAD')
        self.assertEqual(
            findings, [],
            'HEAD imports modules missing from the commit — a fresh '
            f'checkout/cron tick dies: {findings}')

    def test_no_untracked_production_python(self):
        """A source file that exists on disk but is not tracked is invisible
        to a fresh clone even when nothing imports it yet (fixtures,
        scripts, tools). `git add -A` is the rule; this makes skipping it
        loud. .gitignore'd paths (logs/, backups/, __pycache__, .env) are
        excluded via --exclude-standard.

        b44 extension (2026-08-31): .sh is scanned too. The b44 deliverable
        itself — scripts/verify_head.sh — sat UNTRACKED right after it was
        written, exactly the shape this check exists for; a .py-only scan
        was blind to it because shell scripts are never imported."""
        stray = stray_source_files(_git('ls-files', '--others',
                                        '--exclude-standard'))
        self.assertEqual(
            stray, [],
            'untracked source files would vanish on a fresh checkout: '
            f'{stray}')

    def test_stray_filter_catches_shell_not_just_python(self):
        """Synthetic pin (b44): the filter must flag .sh and .py and ignore
        data/log noise, so the check cannot silently regress to .py-only."""
        listing = '\n'.join([
            'scripts/tool.py', 'scripts/verify_head.sh',
            'data/x.json', 'logs/y.log', 'README.md', 'notes.txt',
        ])
        self.assertEqual(stray_source_files(listing),
                         ['scripts/tool.py', 'scripts/verify_head.sh'])

    def test_scan_actually_scans(self):
        """Anti-vacuity: the analyzer must parse a real amount of code."""
        analyze_ref(None)
        self.assertGreaterEqual(analyze_ref.last_file_count, 60)
        self.assertGreaterEqual(analyze_ref.last_import_count, 200)
        analyze_ref('HEAD')
        self.assertGreaterEqual(analyze_ref.last_file_count, 60)
        self.assertGreaterEqual(analyze_ref.last_import_count, 200)

    def test_plain_module_attribute_import_survives_a_ref_scan(self):
        """`from bridge_client import BridgeClient` — bridge_client.py is a
        PLAIN module, so the name is an attribute, not a missing submodule.
        This shape exists in production and CRASHED analyze_ref('HEAD') on
        its first run: get_src() raised RuntimeError from `git show` for the
        non-existent bridge_client/__init__.py and only OSError/KeyError
        were caught. Pinned so the HEAD half cannot rot back to a crash."""
        tracked = {'app.py', 'bridge_client.py'}
        importables = importable_paths(tracked)
        src = 'from bridge_client import BridgeClient\nimport bridge_client\n'

        def boom(path):
            raise RuntimeError(f'git show HEAD:{path} ... not exist')

        findings = untracked_first_party_imports(
            'app.py', src, importables, get_src=boom)
        self.assertEqual(findings, [])
        # and the real production tree must be clean through the ref scan
        self.assertEqual(analyze_ref('HEAD'), [])


class TestTripwireBites(unittest.TestCase):
    def test_broken_commit_is_flagged(self):
        """The ACTUAL 88cac1e tree (committed via `git commit -am`, which
        skipped the new untracked engines/guard_status.py) must be flagged
        by the same analyzer — real history, not a strawman."""
        tracked = tracked_files(BROKEN_COMMIT)
        self.assertIn('hermes_master.py', tracked)
        self.assertNotIn(
            'engines/guard_status.py', tracked,
            'precondition broken: guard_status is now tracked at 88cac1e?')
        importables = importable_paths(tracked)
        src = _git('show', f'{BROKEN_COMMIT}:hermes_master.py')
        findings = untracked_first_party_imports(
            'hermes_master.py', src, importables)
        self.assertIn('engines.guard_status', [m for _, m in findings],
                      f'analyzer missed the real bug: {findings}')

    def test_synthetic_untracked_import_is_flagged(self):
        """Fixture pinning: a tracked file importing a module that exists
        only in the tracked set is fine; one resolving to nothing is
        flagged; third-party imports are not."""
        tracked = {'app.py', 'pkg/__init__.py', 'pkg/mod.py'}
        importables = importable_paths(tracked)
        src = (
            'import os\n'
            'from pkg.mod import thing\n'
            'import pkg.mod\n'
            'import pkg.missing\n'
            'from pkg import missing2\n'
            'from requests import get\n'
        )
        sources = {'pkg/__init__.py': 'X = 1\n'}
        findings = untracked_first_party_imports(
            'app.py', src, importables, get_src=sources.get)
        mods = [m for _, m in findings]
        self.assertIn('pkg.missing', mods)
        self.assertIn('pkg.missing2', mods)
        self.assertNotIn('pkg.mod', mods)
        self.assertNotIn('pkg', mods)
        self.assertNotIn('requests', mods)
        self.assertNotIn('os', mods)

    def test_reexported_attribute_is_not_flagged(self):
        """`from pkg import name` where __init__ defines/re-exports `name`
        is an attribute import, not a missing submodule."""
        tracked = {'app.py', 'pkg/__init__.py', 'pkg/impl.py'}
        importables = importable_paths(tracked)
        src = 'from pkg import helper\nfrom pkg import gone\n'
        sources = {'pkg/__init__.py':
                   'from pkg.impl import helper\n'}
        findings = untracked_first_party_imports(
            'app.py', src, importables, get_src=sources.get)
        mods = [m for _, m in findings]
        self.assertIn('pkg.gone', mods)
        self.assertNotIn('pkg.helper', mods)

    def test_relative_imports_are_checked(self):
        tracked = {'pkg/__init__.py', 'pkg/a.py'}
        importables = importable_paths(tracked)
        src = 'from . import b\nfrom . import a\n'
        sources = {'pkg/__init__.py': ''}
        findings = untracked_first_party_imports(
            'pkg/a.py', src, importables, get_src=sources.get)
        mods = [m for _, m in findings]
        self.assertIn('pkg.b', mods)
        self.assertNotIn('pkg.a', mods)


if __name__ == '__main__':
    unittest.main()
