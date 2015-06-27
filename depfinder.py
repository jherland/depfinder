#!/usr/bin/env python3

from contextlib import contextmanager
import os
from pprint import pprint
import subprocess
import sys
from tempfile import TemporaryDirectory

from strace_parser import strace_output_events


@contextmanager
def temp_fifo(mode=0o666, suffix='', prefix='tmp', dir=None):
    """Return path to temporary FIFO that will be deleted at end of context."""
    with TemporaryDirectory(suffix, prefix, dir) as tempdir:
        fifo_path = os.path.join(tempdir, 'temp_fifo')
        os.mkfifo(fifo_path, mode)
        assert os.path.exists(fifo_path)
        yield fifo_path


def start_trace(cmd_args, trace_output):
    assert len(cmd_args) > 0

    args = [
        'strace', '-f', '-q', '-v', '-s', '4096',
        '-e', 'trace=file', '-e', 'verbose=!stat,lstat',
        '-o', trace_output,
    ]
    print('Running', repr(args), 'followed by', repr(cmd_args))
    return subprocess.Popen(args + cmd_args)


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
        self.ppid = ppid # Parent PID, 0 means unknown/uninteresting
        self.executable = None
        self.argv = None
        self.env = None
        self.paths_read = set() # Paths read by this process
        self.paths_written = set() # Paths written by this process
        self.paths_checked = set() # Paths whose (non-)existence was checked
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


def run_trace(cmd_args):
    with temp_fifo() as fifo:
        with start_trace(cmd_args, fifo) as trace:
            with open(fifo) as f:
                p = Process.from_events(strace_output_events(f))
    assert p.exit_code == trace.returncode
    return p


def main(cmd_args):
    p = run_trace(cmd_args)
    pprint(p.__dict__, width=160)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
