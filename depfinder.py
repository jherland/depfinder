#!/usr/bin/env python3

from pprint import pprint
import sys

from strace_helper import run_trace


class Process:
    """Summarize interesting observations about a running process."""

    @classmethod
    def from_events(cls, events):
        p = None
        for pid, event, args in events:
            if p is None:
                p = Process(pid, 0)
                assert event == 'exec'
            getattr(p, event)(*args)
        return p

    def __init__(self, pid, ppid=0):
        self.pid = pid
        self.ppid = ppid  # Parent PID, 0 means unknown/uninteresting
        self.executable = None
        self.argv = None
        self.env = None
        self.paths_read = set()  # Paths read by this process
        self.paths_written = set()  # Paths written by this process
        self.paths_checked = set()  # Paths whose (non-)existence was checked
        self.exit_code = None

    def exec(self, executable, argv, env):
        self.executable = executable
        self.argv = argv
        self.env = env

    def read(self, path):
        self.paths_read.add(path)

    def write(self, path):
        self.paths_written.add(path)

    def check(self, path, exists):
        self.paths_checked.add((path, exists))

    def exit(self, exit_code):
        self.exit_code = exit_code


def main(cmd_args):
    p = Process.from_events(run_trace(cmd_args))
    pprint(p.__dict__, width=160)
    return p.exit_code


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
