# CPU Scheduler & Deadlock Simulator

![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)
![No dependencies](https://img.shields.io/badge/dependencies-none-2ea44f)
![Tests](https://img.shields.io/badge/tests-unittest-2ea44f)

This is a discrete-time simulator for a single-core OS scheduler. It runs **preemptive priority scheduling with round-robin** among processes of equal priority, prevents starvation with **aging**, and uses the **deadlock detection algorithm** from *Operating System Concepts* (Silberschatz) with **victim-termination recovery**. Each process is a sequence of CPU and I/O bursts, and a CPU burst can request and release multiple instances of several resource types.

At the end of a run it prints a Gantt chart, per-process waiting and turnaround times, and a log of every deadlock it detected along with how it was resolved.

## Input format

```text
[1,5], [2,3], [5,1]                                   ← resource types: [id, instances]
0 0 1 CPU {R[1,2], 50, F[1,1], 20, F[1,1]}            ← pid arrival priority bursts…
1 5 1 CPU {20} IO{30} CPU{20, R[2,3], 30, F[2,3], 10}
```

Inside a `CPU { … }` burst, a number means *execute for that many ticks*, `R[r,n]` means *request n instances of resource r*, and `F[r,n]` means *free them*. Priorities run from 0 (highest) to 20.

## How it works

| Mechanism | Implementation |
|---|---|
| **Scheduling** | The ready process with the lowest priority number runs. A newly ready process with strictly higher priority preempts the running one. Equal priorities share the CPU round-robin with **quantum = 5**. |
| **Aging** | Every 10 ticks a process spends in the ready queue, its priority number drops by 1 (towards 0), so low-priority work can't starve. |
| **Resource requests** | Granted immediately if enough instances are free. Otherwise the process blocks in the wait queue and is re-checked whenever something is released. |
| **Deadlock detection** | Runs every tick while any process is blocked. Every live process is considered: processes that aren't blocked are assumed to finish and return what they hold (`Work += Allocation`), then blocked processes are satisfied iteratively. Whatever remains is deadlocked. |
| **Recovery** | Terminate the deadlocked process with the lowest priority (highest number), release its resources and wake the waiters. This repeats until the cycle is broken. |
| **Exit** | A terminating process gives back everything it still holds. |

## Run

```bash
python cpu_scheduler.py scenarios/test1_deadlock.txt
```

```text
GANTT CHART
   1 -   6: P0
   6 -  11: P1
  11 -  16: P0
  ...
P0: Arrival=  0, Completion= 114, Waiting=  50, Turnaround= 114
P1: Arrival=  5, Completion= 157, Waiting=  48, Turnaround= 152

Average Waiting Time: 49.00
Average Turnaround Time: 133.00
```

## Scenarios

| File | What it exercises | Result |
|---|---|---|
| `example.txt` | Example from the assignment | No deadlock · avg wait 49.0 |
| `classic_deadlock.txt` | Textbook circular wait: P0 holds R1 and wants R2, P1 holds R2 and wants R1 | 1 deadlock, P0 terminated |
| `test1_deadlock.txt` | 5 processes × 5 CPU bursts, multi-instance requests | Deadlock at t = 144, resolved by terminating 3 victims |
| `test2_starvation_aging.txt` | 3 long low-priority CPU hogs vs. resource-heavy high-priority work | Aging lets everyone finish · no deadlock |
| `test3_resource_contention.txt` | Heavy contention on every resource type | Contention, but no deadlock |
| `test4_extreme_starvation.txt` | Extreme priority spread | Aging prevents starvation |
| `test5_no_deadlock.txt` | Resource use ordered to avoid cycles | No deadlock |
| `wait_then_grant.txt` | Block, then get granted from the wait queue | Regression test for the double-grant bug |

## Tests

```bash
python -m unittest discover -s tests -v
```

The tests check that a real circular wait is detected, that there are **no false positives** when a resource's holder is still running, that a request granted from the wait queue isn't repeated, and that every scenario terminates with **all resources returned**.

## Post-course fixes

The first commit is the version handed in for the course. Writing the tests above exposed two bugs in it, which the second commit fixes:

1. **False-positive deadlocks.** Detection only looked at blocked processes and started from the currently free resources. Any process blocked on a resource held by a *running or ready* process was therefore flagged as deadlocked and killed, even in `test5_no_deadlock`. Detection now follows the standard algorithm: every live process takes part, and processes that aren't blocked are allowed to finish and release what they hold.
2. **Double allocation.** When a blocked request was granted from the wait queue, the process didn't advance past its `REQUEST` op. It re-issued the same request the next time it ran and took a second copy of the resource, which leaked resources and caused cascading "deadlocks".

Processes also now release any resources they still hold when they exit.

---

*Operating Systems (ENCS3390), Birzeit University, Fall 2025.*
