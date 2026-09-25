import re
from collections import deque
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from enum import Enum

class ProcessState(Enum):
    NEW = "NEW"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    IO = "IO"
    TERMINATED = "TERMINATED"

@dataclass
class Process:
    pid: int
    arrival_time: int
    priority: int
    bursts: List
    state: ProcessState = ProcessState.NEW
    current_burst_index: int = 0
    burst_progress: int = 0
    waiting_time: int = 0
    turnaround_time: int = 0
    completion_time: int = 0
    time_in_ready: int = 0
    allocated_resources: Dict[int, int] = field(default_factory=dict)
    waiting_for_resource: Optional[Tuple[int, int]] = None
    io_completion_time: int = 0
    
    def get_current_burst(self):
        if self.current_burst_index < len(self.bursts):
            return self.bursts[self.current_burst_index]
        return None

@dataclass
class CPUBurst:
    operations: List  # List of tuples: ('EXEC', time) or ('REQUEST', rid, count) or ('FREE', rid, count)

@dataclass
class IOBurst:
    duration: int

class CPUScheduler:
    def __init__(self, input_file: str, time_quantum: int = 5):
        self.time = 0
        self.time_quantum = time_quantum
        self.processes: List[Process] = []
        self.resources: Dict[int, int] = {}  # {resource_id: total_instances}
        self.available_resources: Dict[int, int] = {}  # {resource_id: available_instances}
        self.allocation: Dict[int, Dict[int, int]] = {}  # {pid: {resource_id: count}}
        self.ready_queue = deque()
        self.waiting_queue = []
        self.io_queue = []
        self.current_process: Optional[Process] = None
        self.gantt_chart = []
        self.quantum_remaining = time_quantum
        self.deadlock_events = []
        
        self.parse_input(input_file)
    
    def parse_input(self, filename: str):
        with open(filename, 'r') as f:
            lines = f.readlines()
        
        # Parse resources
        resource_line = lines[0].strip()
        resources = re.findall(r'\[(\d+),(\d+)\]', resource_line)
        for rid, instances in resources:
            rid, instances = int(rid), int(instances)
            self.resources[rid] = instances
            self.available_resources[rid] = instances
        
        # Parse processes
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            
            parts = line.split()
            pid = int(parts[0])
            arrival = int(parts[1])
            priority = int(parts[2])
            
            # Parse bursts
            bursts = []
            rest = ' '.join(parts[3:])
            
            # Split by CPU and IO
            burst_pattern = r'(CPU|IO)\s*\{([^}]+)\}'
            matches = re.findall(burst_pattern, rest)
            
            for burst_type, content in matches:
                if burst_type == 'CPU':
                    operations = self.parse_cpu_burst(content)
                    bursts.append(CPUBurst(operations))
                else:  # IO
                    duration = int(content.strip())
                    bursts.append(IOBurst(duration))
            
            process = Process(pid, arrival, priority, bursts)
            self.processes.append(process)
            self.allocation[pid] = {}
    
    def parse_cpu_burst(self, content: str) -> List:
        operations = []
        # Match R[id,count], F[id,count], and numbers
        tokens = re.findall(r'R\[(\d+),(\d+)\]|F\[(\d+),(\d+)\]|(\d+)', content)
        
        for token in tokens:
            if token[0]:  # Request
                operations.append(('REQUEST', int(token[0]), int(token[1])))
            elif token[2]:  # Free
                operations.append(('FREE', int(token[2]), int(token[3])))
            elif token[4]:  # Execute
                operations.append(('EXEC', int(token[4])))
        
        return operations
    
    def detect_deadlock(self) -> List[int]:
        """Deadlock detection (Silberschatz, single request per blocked process).

        Every live process is considered, not just the blocked ones: a process
        that is running, ready or doing IO has no outstanding request, so it can
        run to completion and return what it holds. Only blocked processes whose
        request can never be satisfied, even after all of that is returned,
        are deadlocked.
        """
        if not self.waiting_queue:
            return []

        work = self.available_resources.copy()
        live = [p for p in self.processes
                if p.state not in (ProcessState.NEW, ProcessState.TERMINATED)]
        finish = {p.pid: p.waiting_for_resource is None for p in live}
        for p in live:
            if finish[p.pid]:
                for rid, count in p.allocated_resources.items():
                    work[rid] = work.get(rid, 0) + count

        changed = True
        while changed:
            changed = False
            for process in self.waiting_queue:
                if finish[process.pid]:
                    continue
                rid, count = process.waiting_for_resource
                if work.get(rid, 0) >= count:
                    finish[process.pid] = True
                    for r_id, r_count in process.allocated_resources.items():
                        work[r_id] = work.get(r_id, 0) + r_count
                    changed = True

        return [p.pid for p in self.waiting_queue if not finish[p.pid]]

    def recover_from_deadlock(self, deadlocked_pids: List[int]):
        """Terminate the lowest priority process in deadlock"""
        if not deadlocked_pids:
            return
        
        # Find process with lowest priority (highest number)
        victim_pid = max(deadlocked_pids, 
                        key=lambda pid: next(p.priority for p in self.waiting_queue if p.pid == pid))
        
        victim = next(p for p in self.waiting_queue if p.pid == victim_pid)
        
        # Release all resources held by victim
        for rid, count in victim.allocated_resources.items():
            self.available_resources[rid] += count
            self.allocation[victim_pid][rid] = 0
        
        victim.allocated_resources.clear()
        victim.state = ProcessState.TERMINATED
        victim.completion_time = self.time
        
        self.waiting_queue.remove(victim)
        
        event = f"Time {self.time}: Deadlock detected! Terminated P{victim_pid} (priority={victim.priority})"
        self.deadlock_events.append(event)
        print(event)
        
        # Try to move waiting processes to ready
        self.check_waiting_queue()
    
    def request_resource(self, process: Process, rid: int, count: int) -> bool:
        """Try to allocate resource to process"""
        if self.available_resources.get(rid, 0) >= count:
            self.available_resources[rid] -= count
            process.allocated_resources[rid] = process.allocated_resources.get(rid, 0) + count
            self.allocation[process.pid][rid] = process.allocated_resources[rid]
            return True
        return False
    
    def release_resource(self, process: Process, rid: int, count: int):
        """Release resource from process"""
        if rid in process.allocated_resources:
            process.allocated_resources[rid] -= count
            if process.allocated_resources[rid] <= 0:
                del process.allocated_resources[rid]
                self.allocation[process.pid][rid] = 0
            else:
                self.allocation[process.pid][rid] = process.allocated_resources[rid]
            
            self.available_resources[rid] += count
    
    def check_waiting_queue(self):
        """Check if any waiting process can now proceed"""
        to_remove = []
        for process in self.waiting_queue:
            if process.waiting_for_resource:
                rid, count = process.waiting_for_resource
                if self.request_resource(process, rid, count):
                    process.waiting_for_resource = None
                    process.burst_progress += 1  # the REQUEST op is now satisfied
                    process.state = ProcessState.READY
                    process.time_in_ready = 0
                    self.ready_queue.append(process)
                    to_remove.append(process)
        
        for process in to_remove:
            self.waiting_queue.remove(process)
    
    def age_processes(self):
        """Apply aging to processes in ready queue"""
        for process in list(self.ready_queue):
            process.time_in_ready += 1
            if process.time_in_ready >= 10:
                if process.priority > 0:
                    process.priority -= 1
                    process.time_in_ready = 0
    
    def get_highest_priority_process(self) -> Optional[Process]:
        """Get process with highest priority (lowest number)"""
        if not self.ready_queue:
            return None
        
        min_priority = min(p.priority for p in self.ready_queue)
        for process in self.ready_queue:
            if process.priority == min_priority:
                self.ready_queue.remove(process)
                return process
        return None
    
    def run(self):
        """Main simulation loop"""
        while True:
            # Check for new arrivals
            for process in self.processes:
                if process.arrival_time == self.time and process.state == ProcessState.NEW:
                    process.state = ProcessState.READY
                    process.time_in_ready = 0
                    self.ready_queue.append(process)
            
            # Check IO completions
            completed_io = []
            for process in self.io_queue:
                if self.time >= process.io_completion_time:
                    process.state = ProcessState.READY
                    process.time_in_ready = 0
                    process.current_burst_index += 1
                    self.ready_queue.append(process)
                    completed_io.append(process)
            
            for process in completed_io:
                self.io_queue.remove(process)
            
            # Check if we need to preempt current process
            if self.current_process and self.ready_queue:
                highest = min(self.ready_queue, key=lambda p: p.priority)
                if highest.priority < self.current_process.priority:
                    # Preempt
                    self.current_process.state = ProcessState.READY
                    self.current_process.time_in_ready = 0
                    self.ready_queue.appendleft(self.current_process)
                    self.current_process = None
                    self.quantum_remaining = self.time_quantum
            
            # Select process if CPU is idle
            if not self.current_process and self.ready_queue:
                self.current_process = self.get_highest_priority_process()
                self.current_process.state = ProcessState.RUNNING
                self.quantum_remaining = self.time_quantum
            
            # Execute current process
            if self.current_process:
                burst = self.current_process.get_current_burst()
                
                if isinstance(burst, CPUBurst):
                    if self.current_process.burst_progress < len(burst.operations):
                        op = burst.operations[self.current_process.burst_progress]
                        
                        if op[0] == 'EXEC':
                            exec_time = op[1]
                            if exec_time > 0:
                                burst.operations[self.current_process.burst_progress] = ('EXEC', exec_time - 1)
                                self.gantt_chart.append((self.time, self.current_process.pid))
                                self.quantum_remaining -= 1
                                
                                if exec_time == 1:
                                    self.current_process.burst_progress += 1
                            else:
                                self.current_process.burst_progress += 1
                        
                        elif op[0] == 'REQUEST':
                            rid, count = op[1], op[2]
                            if self.request_resource(self.current_process, rid, count):
                                self.current_process.burst_progress += 1
                            else:
                                # Move to waiting queue
                                self.current_process.waiting_for_resource = (rid, count)
                                self.current_process.state = ProcessState.WAITING
                                self.waiting_queue.append(self.current_process)
                                self.current_process = None
                                self.quantum_remaining = self.time_quantum
                        
                        elif op[0] == 'FREE':
                            rid, count = op[1], op[2]
                            self.release_resource(self.current_process, rid, count)
                            self.current_process.burst_progress += 1
                            self.check_waiting_queue()
                    
                    else:
                        # CPU burst complete
                        self.current_process.burst_progress = 0
                        self.current_process.current_burst_index += 1
                        
                        next_burst = self.current_process.get_current_burst()
                        if next_burst is None:
                            # Process terminates: return anything it still holds
                            for rid, count in list(self.current_process.allocated_resources.items()):
                                self.release_resource(self.current_process, rid, count)
                            self.check_waiting_queue()
                            self.current_process.state = ProcessState.TERMINATED
                            self.current_process.completion_time = self.time
                            self.current_process = None
                        elif isinstance(next_burst, IOBurst):
                            # Move to IO
                            self.current_process.state = ProcessState.IO
                            self.current_process.io_completion_time = self.time + next_burst.duration
                            self.io_queue.append(self.current_process)
                            self.current_process = None
                        
                        self.quantum_remaining = self.time_quantum
                
                # Round robin quantum check
                if self.current_process and self.quantum_remaining <= 0:
                    if self.ready_queue:
                        self.current_process.state = ProcessState.READY
                        self.current_process.time_in_ready = 0
                        self.ready_queue.append(self.current_process)
                        self.current_process = None
                    self.quantum_remaining = self.time_quantum
            
            else:
                # CPU idle
                self.gantt_chart.append((self.time, -1))
            
            # Update waiting times
            for process in self.ready_queue:
                process.waiting_time += 1
            
            # Age processes in ready queue
            self.age_processes()
            
            # Deadlock detection
            if self.waiting_queue:
                deadlocked = self.detect_deadlock()
                if deadlocked:
                    self.recover_from_deadlock(deadlocked)
            
            # Check termination condition
            all_terminated = all(p.state == ProcessState.TERMINATED for p in self.processes)
            if all_terminated and not self.ready_queue and not self.io_queue and not self.waiting_queue:
                break
            
            self.time += 1
            
            # Safety check
            if self.time > 10000:
                print("Simulation timeout!")
                break
    
    def print_results(self):
        """Print Gantt chart and statistics"""
        print("\n" + "="*80)
        print("GANTT CHART")
        print("="*80)
        
        # Compress gantt chart
        compressed = []
        for time, pid in self.gantt_chart:
            if not compressed or compressed[-1][1] != pid:
                compressed.append([time, pid, time])
            else:
                compressed[-1][2] = time
        
        for start, pid, end in compressed:
            if pid == -1:
                print(f"{start:4d}-{end+1:4d}: IDLE")
            else:
                print(f"{start:4d} -{end+1:4d}: P{pid}")
        
        print("\n" + "="*80)
        print("PROCESS STATISTICS")
        print("="*80)
        
        total_waiting = 0
        total_turnaround = 0
        
        for process in sorted(self.processes, key=lambda p: p.pid):
            turnaround = process.completion_time - process.arrival_time
            process.turnaround_time = turnaround
            total_waiting += process.waiting_time
            total_turnaround += turnaround
            
            print(f"P{process.pid}: Arrival={process.arrival_time:3d}, "
                  f"Completion={process.completion_time:4d}, "
                  f"Waiting={process.waiting_time:4d}, "
                  f"Turnaround={turnaround:4d}")
        
        n = len(self.processes)
        print(f"\nAverage Waiting Time: {total_waiting/n:.2f}")
        print(f"Average Turnaround Time: {total_turnaround/n:.2f}")
        
        if self.deadlock_events:
            print("\n" + "="*80)
            print("DEADLOCK EVENTS")
            print("="*80)
            for event in self.deadlock_events:
                print(event)
        else:
            print("\n" + "="*80)
            print("NO DEADLOCKS DETECTED")
            print("="*80)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    else:
        input_file = "test5_no_deadlock.txt"
    
    scheduler = CPUScheduler(input_file, time_quantum=5)
    print(f"Starting simulation with {len(scheduler.processes)} processes...")
    scheduler.run()
    scheduler.print_results()
