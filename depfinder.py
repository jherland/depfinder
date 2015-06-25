#!/usr/bin/env python3

from pathlib import Path
import subprocess
import sys


Strace = 'strace'
StraceParser = Path(__file__).resolve().with_name('parse_strace.py')
assert StraceParser.is_file()


def main(cmd_args):
    assert len(cmd_args) > 0

    args = [
        Strace, '-D', '-f', '-q', '-v', '-s', '4096',
        '-e', 'trace=file', '-e', 'verbose=!stat',
        '-o', '|' + str(StraceParser),
    ]
    print('Running', repr(args), 'followed by', repr(cmd_args))
    return subprocess.call(args + cmd_args)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
