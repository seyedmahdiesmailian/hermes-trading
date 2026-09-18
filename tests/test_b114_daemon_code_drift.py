"""b114 — THE LONG-LIVED DAEMONS CAN RUN CODE THAT NO TEST CERTIFIES.

position_daemon.py and signal_daemon.py are systemd services with
Restart=always. Python binds modules at IMPORT, so a commit that changes the
exit ladder, the trail distance or the parser's instrument gate is INERT until
the process restarts. Nothing in the repo recorded which commit a running
daemon booted from, so the drift was invisible: every audit — and every
autopilot run, including the one that shipped b111 — reads the WORKING TREE and
describes behaviour production does not have.

MEASURED 2026-09-07 (scripts/b114_daemon_code_drift.py; the finding is frozen
in data/ops/daemon_code_drift_b114_finding.json, the live re-measurement lands
in data/ops/daemon_code_drift.json):

  * position_daemon booted 2026-09-03T14:45:01Z — 17 SECONDS before 31c64f7
    (b65: balanced runner trail 0.45R -> 0.30R, the arm that "wins in all 4
    independent slices"). The watchdog has managed every position with the OLD,
    looser 0.45R trail ever since, while the funnel, the tests and the backlog
    all quoted 0.30R.
  * signal_daemon booted 2026-09-04T18:44:16Z — 1 SECOND before c32f4e8 (b74g:
    reject non-gold instruments in the LIVE listener, the fix for an FX price
    like 1.15135 being resolved into ~4301 and looking like a valid gold
    signal).
  * Both closures also missed d3a0ba0 (b109 ladder_fields) and 1698e7d (b106
    computed_rr), and the watchdog closure missed engines.defcon (5c17f28) and
    engines.learning (6b65ef1).

WHY THE PINS SPLIT IN TWO: the HISTORICAL claims below read the frozen finding
artifact, because they certify what was measured on 2026-09-07 and must stay
true after the services are restarted (the restart is the operational fix,
filed as b115). The MACHINERY claims read the live ledger, so they re-verify
against whatever is running now. A test that pinned "the watchdog is stale"
would go red the moment the system got healthy — that is the wrong shape.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LIVE = os.path.join(ROOT, "data", "ops", "daemon_code_drift.json")
FINDING = os.path.join(ROOT, "data", "ops", "daemon_code_drift_b114_finding.json")
PROBE = os.path.join(ROOT, "scripts", "b114_daemon_code_drift.py")

# The two commits whose landing raced a daemon boot (b114's finding).
B65_TRAIL_COMMIT = "31c64f7"
B74G_INSTRUMENT_COMMIT = "c32f4e8"


def _load_probe():
    spec = importlib.util.spec_from_file_location("b114_probe", PROBE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read(path):
    with open(path) as fh:
        return json.load(fh)


def _git(*args):
    return subprocess.run(["git", "-C", ROOT, *args],
                          capture_output=True, text=True)


class TestB114ProbeMachinery(unittest.TestCase):
    """The probe must keep working, on today's state, forever."""

    def test_b114_the_probe_reads_process_boots_from_ps_not_prose(self):
        # The whole point is that the boot time comes from the OS, so nobody
        # can keep a claim alive by editing a comment.
        probe = _load_probe()
        self.assertTrue(callable(probe.process_start_utc))
        # hermes_master is NOT a drift risk (cron re-execs it every 15 min);
        # the two daemons are, and the probe must cover both.
        self.assertIn("position_daemon.py", probe.DAEMONS)
        self.assertIn("signal_daemon.py", probe.DAEMONS)
        self.assertNotIn("hermes_master.py", probe.DAEMONS)

    def test_b155_the_dashboard_bot_is_in_the_census(self):
        # b155: scripts/dashboard_bot.py is a THIRD long-lived process
        # (systemd hermes-dashboard, Restart=always) that binds
        # notifier.dashboards at import. Before b155 the census claimed
        # "only the daemons are" a risk and its own comment was the lie:
        # the operator's phone kept rendering the PRE-b152/b154 panel for a
        # week while every drift report said "clean". The entry must be the
        # path systemd actually execs, and the panel module must be in the
        # closure by whatever route (extra or import walk).
        probe = _load_probe()
        self.assertIn("dashboard_bot.py", probe.DAEMONS)
        spec = probe.DAEMONS["dashboard_bot.py"]
        self.assertEqual(spec["entry"], "scripts/dashboard_bot.py")
        closure = probe.import_closure(spec["entry"], spec["extra"])
        self.assertIn("notifier/dashboards.py", closure,
                      "the dashboard's render module is invisible to the "
                      "census — b155's blind spot is back")
        # reality-binding: the entry string must match the actual process
        # line AND the systemd unit's ExecStart, not a hand-typed guess.
        start = probe.process_start_utc("dashboard_bot.py")
        if start is not None:
            led = _read(LIVE)
            self.assertIn("dashboard_bot.py", led["daemons"],
                          "the drift probe has not been re-run since b155 "
                          "added the third daemon")
            unit_path = os.path.expanduser(
                "~/.config/systemd/user/hermes-dashboard.service")
            if os.path.exists(unit_path):
                body = open(unit_path).read()
                self.assertIn(spec["entry"], body,
                              "the census entry no longer matches what "
                              "systemd actually execs")

    def test_b155_import_closure_sees_from_package_submodules(self):
        # The deeper defect b155 caught while wiring the third daemon: the
        # old walk resolved ONLY the dotted module in `from pkg import name`
        # (i.e. pkg/__init__.py) and never the submodule, so every file
        # imported that way was invisible to drift — including
        # engines/paths.py in ALL THREE processes, engines/broker_clock.py
        # in the watchdog and engines/signal_pending.py in the listener.
        # Pin the names the fix restored, and pin the anti-vacuity: a
        # stdlib name imported the same way (pathlib) must NOT appear.
        probe = _load_probe()
        pos = probe.import_closure("position_daemon.py", [])
        self.assertIn("engines/paths.py", pos,
                      "b155: engines/paths.py (from engines import paths) "
                      "fell out of the watchdog closure again")
        self.assertIn("engines/broker_clock.py", pos)
        sig = probe.import_closure("signal_daemon.py", [])
        self.assertIn("engines/signal_pending.py", sig)
        self.assertIn("notifier/dashboards.py", sig)
        bot = probe.import_closure("scripts/dashboard_bot.py", [])
        self.assertIn("engines/paths.py", bot)
        for name, closure in (("pos", pos), ("sig", sig), ("bot", bot)):
            self.assertNotIn("pathlib.py", closure,
                             f"{name}: the submodule walk stopped dropping "
                             "names that have no repo file")

    def test_b114_the_import_closure_finds_the_ladder_module(self):
        # If the closure silently stopped resolving engines/*, the probe would
        # report "no drift" forever — the vacuity this family exists to catch.
        probe = _load_probe()
        closure = probe.import_closure("position_daemon.py", [])
        self.assertIn("engines/trade_management.py", closure)
        self.assertIn("position_daemon.py", closure)
        self.assertGreaterEqual(len(closure), 10,
                                f"the closure collapsed to {len(closure)} files "
                                "— the import walk is broken, so drift would "
                                "read as zero")

    def test_b114_the_live_ledger_is_bound_to_the_running_processes(self):
        # Reality-binding, in the direction that cannot false-alarm:
        #  (a) the ledger's changed-set must be reproducible ARITHMETIC from
        #      its own boot commit + recorded head (so the numbers cannot be
        #      hand-written), and
        #  (b) the ledger's boot commit must be an ANCESTOR of (or equal to)
        #      the boot commit of the process running right now — a process can
        #      only get newer, never older. If it is newer, the ledger is
        #      merely stale (someone restarted the service, e.g. b115) and the
        #      test says so instead of failing, because a suite that goes red
        #      on a HEALTHY restart trains everyone to delete the test.
        led = _read(LIVE)
        probe = _load_probe()
        self.assertEqual(
            _git("merge-base", "--is-ancestor", led["head"],
                 "HEAD").returncode, 0,
            "the drift ledger's head is not an ancestor of the tree under test")
        for name in probe.DAEMONS:
            entry = led["daemons"][name]
            boot = entry["boot_commit"]["sha"]
            self.assertEqual(
                {c["file"] for c in entry["changed_since_boot"]},
                set(_git("diff", "--name-only", boot, led["head"], "--",
                         *entry["closure"]).stdout.split()),
                f"{name}: the changed-closure set is not reproducible from the "
                "ledger's own boot commit — re-run "
                "scripts/b114_daemon_code_drift.py")
            live_start = probe.process_start_utc(name)
            if live_start is None:
                if entry["running"]:
                    print(f"b114: {name} is not running now; the ledger is "
                          "stale — re-run the probe (not a failure)")
                continue
            live_boot = probe.commit_at_or_before(live_start)["sha"]
            self.assertEqual(
                _git("merge-base", "--is-ancestor", boot,
                     live_boot).returncode, 0,
                f"{name}: the ledger claims boot {boot[:9]} but the running "
                "process booted from an OLDER commit — the ledger does not "
                "describe this box")
            if live_boot != boot:
                print(f"b114: {name} restarted since the ledger "
                      f"({boot[:9]} -> {live_boot[:9]}); re-run "
                      "scripts/b114_daemon_code_drift.py to refresh")

    def test_b114_boot_commit_is_always_an_ancestor_of_head(self):
        led = _read(LIVE)
        for name, d in led["daemons"].items():
            if not d.get("running"):
                continue
            self.assertEqual(
                _git("merge-base", "--is-ancestor", d["boot_commit"]["sha"],
                     led["head"]).returncode, 0,
                f"{name}: boot commit is not an ancestor of HEAD — the probe "
                "resolved the wrong tree")


class TestB114FindingIsFrozen(unittest.TestCase):
    """The 2026-09-07 measurement, pinned against the FROZEN artifact so the
    operational restart (b115) cannot silently delete the evidence."""

    def setUp(self):
        if not os.path.exists(FINDING):
            self.skipTest("b114 finding artifact missing")
        self.led = _read(FINDING)

    def test_b114_the_watchdog_booted_17_seconds_before_the_trail_fix(self):
        d = self.led["daemons"]["position_daemon.py"]
        self.assertTrue(d["running"])
        boot = d["boot_commit"]["sha"]
        # boot must PREDATE the b65 trail commit, and the b65 commit must be in
        # HEAD — i.e. the fix is committed but not necessarily running.
        self.assertEqual(_git("merge-base", "--is-ancestor", boot,
                              B65_TRAIL_COMMIT).returncode, 0,
                         "the recorded boot commit already contains the b65 "
                         "trail fix — this artifact no longer measures the race")
        self.assertEqual(_git("merge-base", "--is-ancestor", B65_TRAIL_COMMIT,
                              self.led["head"]).returncode, 0)
        self.assertIn("engines/trade_management.py",
                      {c["file"] for c in d["changed_since_boot"]},
                      "the trail module is no longer in the watchdog's drifted "
                      "set — re-read the finding before quoting 0.45 vs 0.30")

    def test_b114_the_signal_daemon_booted_one_second_before_the_gate_fix(self):
        d = self.led["daemons"]["signal_daemon.py"]
        self.assertTrue(d["running"])
        self.assertEqual(_git("merge-base", "--is-ancestor",
                              d["boot_commit"]["sha"],
                              B74G_INSTRUMENT_COMMIT).returncode, 0,
                         "the recorded boot commit already contains c32f4e8")
        self.assertIn("engines/signal_parser.py",
                      {c["file"] for c in d["changed_since_boot"]})

    def test_b114_the_two_trail_values_differ_in_the_two_trees(self):
        # The concrete behavioural cost, read out of git rather than asserted:
        # the watchdog's boot tree says 0.45R, the commit it booted 17s short
        # of says 0.30R. Both sides are IMMUTABLE history on purpose — pinning
        # "HEAD's value" would rot the day the trail is retuned, and this test
        # is about the race, not about the current number.
        boot = self.led["daemons"]["position_daemon.py"]["boot_commit"]["sha"]
        boot_src = _git("show", f"{boot}:engines/trade_management.py").stdout
        b65_src = _git("show",
                       f"{B65_TRAIL_COMMIT}:engines/trade_management.py").stdout
        self.assertIn('risk_distance * 0.45, 3.0), 2), "balanced_trail"',
                      boot_src,
                      "the boot tree did not carry the old 0.45R trail — the "
                      "b65-inertia claim needs re-reading")
        self.assertIn('risk_distance * 0.3, 3.0), 2), "balanced_trail"',
                      b65_src,
                      "31c64f7 no longer carries the 0.30R trail — the commit "
                      "this item names has changed shape")

    def test_b114_the_finding_is_not_vacuous(self):
        running = [d for d in self.led["daemons"].values() if d.get("running")]
        self.assertEqual(len(running), 2,
                         "both trading daemons were running when b114 measured "
                         "— a one-sided census cannot support the claim")
        for d in running:
            self.assertGreater(d["closure_files"], 5)
            self.assertTrue(d["changed_since_boot"],
                            "the frozen finding recorded NO drift — then b114 "
                            "is not what this file says it is")


class TestB115RestartIsHumanGated(unittest.TestCase):
    """THE DELIBERATE NON-ACTION (b102 discipline: a parked decision needs a
    spared-direction pin whose NAME carries the parked item).

    b114 found live drift and this run did NOT restart the services. That is
    not oversight: restarting the process that places and manages real orders
    is a live-path operation, and the autopilot's hard rules forbid it. What
    IS forbidden is the drift becoming invisible, so the pin below certifies
    the measurement stays read-only and loud.
    """

    def test_b115_the_drift_probe_never_restarts_or_touches_the_live_path(self):
        # If the probe ever grew a `systemctl restart` (or any bridge order
        # call) to "fix" what it measures, the autopilot would be restarting
        # the live trader from a cron job. That must fail here, not in prod.
        src = open(PROBE).read()
        for banned in ("systemctl", "os.system", "subprocess.call", "pkill",
                       "SIGKILL", "SIGTERM", "BridgeClient", "requests",
                       "open_position", "close_position", "modify_position"):
            self.assertNotIn(banned, src,
                             f"the b114 probe now mentions {banned!r} — it must "
                             "MEASURE the drift, never act on the live path "
                             "(b115 is a human-gated operation)")
        # and it must still be pure stdlib + git/ps subprocesses
        tree = ast.parse(src, filename=PROBE)
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods.add(node.module.split(".")[0])
        self.assertEqual(mods - {"ast", "json", "os", "subprocess", "sys",
                                 "datetime", "__future__"}, set(),
                         f"the probe gained a new dependency: {mods}")

    def test_b115_the_backlog_records_the_restart_as_pending_not_done(self):
        # The non-action must stay visible: b115 has to remain an open todo
        # until somebody actually restarts the services and re-runs the probe.
        text = open(os.path.join(ROOT, "data", "ops",
                                 "autopilot_backlog.md")).read()
        self.assertIn("- [ ] b115", text,
                      "b115 (guarded daemon restart) is no longer an open todo "
                      "— if the restart happened, re-run the drift probe and "
                      "update b114's finding; if not, this item was closed "
                      "without the fix")


if __name__ == "__main__":
    unittest.main(verbosity=2)
