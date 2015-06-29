#!/usr/bin/env python3

from pprint import pprint

from process_trace import ProcessTrace
from strace_helper import run_trace


def main(cmd_args):
    p = ProcessTrace.from_events(run_trace(cmd_args))
    pprint(p.__dict__, width=160)
    return p.exit_code


if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv[1:]))
