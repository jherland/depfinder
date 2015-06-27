#!/usr/bin/env python3

from pathlib import Path
import subprocess
import sys


strace = 'strace'
strace_parser = Path(__file__).resolve().with_name('strace_parser.py')
assert strace_parser.is_file()


def start_trace(cmd_args):
    assert len(cmd_args) > 0

    args = [
        strace, '-D', '-f', '-q', '-v', '-s', '4096',
        '-e', 'trace=file', '-e', 'verbose=!stat,lstat',
        '-o', '|' + str(strace_parser),
    ]
    print('Running', repr(args), 'followed by', repr(cmd_args))
    return subprocess.Popen(args + cmd_args)


def main(cmd_args):
    with start_trace(cmd_args) as proc:
        pass
    return proc.returncode


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
