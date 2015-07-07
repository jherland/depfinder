#!/usr/bin/env python3

from subprocess import Popen, PIPE, CalledProcessError


def call_output_lines(*popenargs, **kwargs):
    '''Like subprocess.check_output(), but yield output lines, lazily.'''
    p = Popen(*popenargs, stdout=PIPE, universal_newlines=True, **kwargs)
    for line in p.stdout:
        yield line.rstrip('\r\n')
    p.wait()


def run_make(*args):
    '''Run make with appropriate options in a subprocess, and return an iterator over its output lines.'''
    argv = ['make', '--print-data-base', '--question'] + list(args)
    return call_output_lines(argv)


def _parse_makedb_vars(lines, stop_at):
    for line in lines:
        if stop_at(line):
            break
        elif not line or line.startswith('#'):
            pass
        else:
            k, _, v = line.partition('= ')
            k = k.rstrip(':').rstrip(' ')
            yield k, v


def _parse_makedb_rules(lines, stop_at):
    target, deps, recipe = None, [], []
    for line in lines:
        if stop_at(line):
            break
        elif not line or line.startswith('#'):
            pass
        elif line.startswith('\t'):
            assert target is not None
            recipe.append(line[1:])
        else:
            # Finish previous target
            if target is not None:
                yield target, deps, recipe
                target, deps, recipe = None, [], []

            target, dep_s = line.split(':', 1)
            deps = dep_s.split()

    # Finish last target
    if target is not None:
        yield target, deps, recipe


def parse_makedb(lines):
    # pre
    for line in lines:
        if line == '# Variables':
            break

    stop_at = lambda l: l == '# Implicit Rules'
    make_vars = dict(_parse_makedb_vars(lines, stop_at))

    make_rules = list(_parse_makedb_rules(lines, lambda l: False))

    return make_vars, make_rules


def main(*make_args):
    # Pass -C and -f (and other) options on to make...
    from pprint import pprint
    pprint(parse_makedb(run_make(*make_args)))


if __name__ == '__main__':
    import sys
    sys.exit(main(*sys.argv[1:]))
