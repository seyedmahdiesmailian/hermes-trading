"""b216 — the master cycle's hard ceiling must fit inside its own period.

THE DRIFT: scripts/hermes_cron.sh capped the cycle at 840s with the comment
"hard ceiling below the 15-min period". The live crontab
(ops/cron/crontab.root.txt, pulled off the running box in b79e) fires that
script every 5 MINUTES. 840s is nearly three of those periods.

Why that is not merely untidy: flock makes a stuck cycle SKIP the next tick
rather than race it, which is correct — but every skipped tick is a plan
refresh and an entry opportunity that silently never happened. With the
ceiling longer than the period, one wedged cycle could swallow two further
ticks before being killed. The ceiling must be shorter than the period so a
wedged cycle dies before the next one is due.

This test pins the RELATIONSHIP, not the numbers, so changing the cron
cadence forces the ceiling to be reconsidered in the same commit.

It also pins which scheduler owns the cycle. Two references disagreed —
crontab says */5, ops/systemd/hermes-trading.timer says 15min — and they
invoke the SAME script. The crontab is authoritative: it was pulled from
the live box, and setup.sh installs the crontab while never copying that
timer. A future edit that enables both must trip this test.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CRON_SH = ROOT / "scripts" / "hermes_cron.sh"
CRONTAB = ROOT / "ops" / "cron" / "crontab.root.txt"
TIMER = ROOT / "ops" / "systemd" / "hermes-trading.timer"
SETUP = ROOT / "setup.sh"


def cron_period_seconds() -> int:
    """The real cadence of the master cycle, read from the live crontab."""
    for line in CRONTAB.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "hermes_cron.sh" not in line:
            continue
        minute = line.split()[0]
        m = re.fullmatch(r"\*/(\d+)", minute)
        if m:
            return int(m.group(1)) * 60
        if minute == "*":
            return 60
    raise AssertionError("no hermes_cron.sh entry found in crontab.root.txt")


def script_timeout_seconds() -> int:
    m = re.search(r"^timeout\s+(\d+)\s+python3",
                  CRON_SH.read_text(encoding="utf-8"), re.M)
    assert m, "no `timeout N python3` line in hermes_cron.sh"
    return int(m.group(1))


class CeilingFitsInsideThePeriod(unittest.TestCase):

    def test_timeout_is_shorter_than_the_cron_period(self):
        period, ceiling = cron_period_seconds(), script_timeout_seconds()
        self.assertLess(
            ceiling, period,
            f"the master cycle can run {ceiling}s but fires every {period}s — "
            "a wedged cycle holds the flock past the next tick and those "
            "ticks are silently skipped plan refreshes")

    def test_there_is_real_headroom(self):
        """Not just under the wire: the kill must land before the next tick."""
        period, ceiling = cron_period_seconds(), script_timeout_seconds()
        self.assertLessEqual(ceiling, period - 10,
                             "less than 10s of headroom before the next tick")

    def test_the_ceiling_is_not_uselessly_small(self):
        """Anti-vacuity: a 5s ceiling would pass the test above and kill every
        real cycle."""
        self.assertGreaterEqual(script_timeout_seconds(), 120)

    def test_the_period_is_the_one_we_measured(self):
        """If the cadence changes, re-read b216 rather than trusting it."""
        self.assertEqual(cron_period_seconds(), 300)


class OneSchedulerOwnsTheCycle(unittest.TestCase):

    def test_setup_installs_the_crontab(self):
        self.assertIn("crontab ops/cron/crontab.root.txt",
                      SETUP.read_text(encoding="utf-8"))

    def test_setup_does_not_install_the_duplicate_timer(self):
        """The timer runs the SAME script on a different cadence; installing
        both makes the effective frequency unpredictable."""
        self.assertNotIn("hermes-trading.timer",
                         SETUP.read_text(encoding="utf-8"))

    def test_the_duplication_is_documented_where_an_operator_looks(self):
        """The timer file is kept as a mirror of the live box, so the hazard
        has to be written down next to it rather than silently removed."""
        readme = (ROOT / "ops" / "README.md").read_text(encoding="utf-8")
        self.assertIn("hermes-trading.timer", readme)
        self.assertIn("b216", readme)

    def test_both_schedulers_really_do_invoke_the_same_script(self):
        """The premise of the warning — pinned so it cannot rot."""
        self.assertIn("hermes_cron.sh", TIMER.with_name(
            "hermes-trading.service").read_text(encoding="utf-8"))
        self.assertIn("hermes_cron.sh", CRONTAB.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
