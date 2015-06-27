#!/usr/bin/env python3

from contextlib import contextmanager
import os
from pprint import pprint
import subprocess
import sys
from tempfile import TemporaryDirectory

import strace_parser


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


def main(cmd_args):
    with temp_fifo() as fifo:
        with start_trace(cmd_args, fifo) as trace:
            with open(fifo) as f:
                for e in strace_parser.events(strace_parser.parse_strace_output(f)):
                    pprint(e, width=160)
    return trace.returncode


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
