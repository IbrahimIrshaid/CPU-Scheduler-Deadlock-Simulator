import contextlib
import io
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from cpu_scheduler import CPUScheduler, ProcessState  # noqa: E402

SCENARIOS = os.path.join(ROOT, "scenarios")


def simulate(name, quantum=5):
    s = CPUScheduler(os.path.join(SCENARIOS, name), time_quantum=quantum)
    with contextlib.redirect_stdout(io.StringIO()):
        s.run()
    return s


class DeadlockDetection(unittest.TestCase):
    def test_classic_circular_wait_is_detected(self):
        # P0 holds R1 and wants R2; P1 holds R2 and wants R1.
        s = simulate("classic_deadlock.txt")
        self.assertEqual(len(s.deadlock_events), 1)

    def test_no_false_positive_when_holder_is_not_blocked(self):
        s = simulate("test5_no_deadlock.txt")
        self.assertEqual(s.deadlock_events, [])

    def test_designed_deadlock_scenario_is_detected(self):
        s = simulate("test1_deadlock.txt")
        self.assertGreater(len(s.deadlock_events), 0)


class ResourceAccounting(unittest.TestCase):
    def test_request_granted_from_wait_queue_is_not_repeated(self):
        # P1 blocks on R1 while P0 holds both instances. When P0 frees them, P1 must
        # be granted exactly one instance, and must not re-issue the same request.
        s = simulate("wait_then_grant.txt")
        self.assertEqual(s.available_resources, {1: 2})
        self.assertEqual(s.deadlock_events, [])


class Invariants(unittest.TestCase):
    def test_every_scenario_terminates_and_returns_all_resources(self):
        for name in sorted(os.listdir(SCENARIOS)):
            with self.subTest(scenario=name):
                s = simulate(name)
                self.assertLess(s.time, 10000, "simulation timed out")
                self.assertTrue(all(p.state == ProcessState.TERMINATED for p in s.processes))
                self.assertEqual(s.available_resources, s.resources)


if __name__ == "__main__":
    unittest.main()
