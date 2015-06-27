#!/usr/bin/env python3

from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory


strace = 'strace'
strace_parser = Path(__file__).resolve().with_name('strace_parser.py')
assert strace_parser.is_file()


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
        strace, '-D', '-f', '-q', '-v', '-s', '4096',
        '-e', 'trace=file', '-e', 'verbose=!stat,lstat',
        '-o', trace_output,
    ]
    print('Running', repr(args), 'followed by', repr(cmd_args))
    return subprocess.Popen(args + cmd_args)


def main(cmd_args):
    with start_trace(cmd_args, '|' + str(strace_parser)) as proc:
        pass
    return proc.returncode


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
