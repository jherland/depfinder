#!/usr/bin/env python3

import logging
import shlex

from process_trace import ProcessTrace
from strace_helper import run_trace


logging.basicConfig(level=logging.WARNING)


def main(cmd_args):
    p = ProcessTrace.from_events(run_trace(cmd_args))
    p = p.collapsed()

    written = set(t[1] for t in p.paths_written)
    read = set(t[1] for t in p.paths_read)
    present = set(t[1] for t in p.paths_checked if t[2])
    missing = set(t[1] for t in p.paths_checked if not t[2])

    present -= written | read
    missing -= written | read

    print('The command:\n    {}'.format(
         ' '.join(shlex.quote(a) for a in p.argv)))
    if written:
        print('writes these paths:')
        for path in sorted(written):
            print('    {}'.format(path))
    if written:
        print('reads these paths:')
        for path in sorted(read):
            print('    {}'.format(path))
    if present:
        print('depends on the existence of these paths:')
        for path in sorted(present):
            print('    {}'.format(path))
    if missing:
        print('depends on the non-existence of these paths:')
        for path in sorted(missing):
            print('    {}'.format(path))


if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv[1:]))
