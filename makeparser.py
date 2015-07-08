#!/usr/bin/env python3

from subprocess import Popen, PIPE, CalledProcessError


def call_output_lines(*popenargs, **kwargs):
    '''Like subprocess.check_output(), but yield output lines, lazily.'''
    p = Popen(*popenargs, stdout=PIPE, universal_newlines=True, **kwargs)
    for line in p.stdout:
        yield line.rstrip('\r\n')
    p.wait()


class Makefile:

    @staticmethod
    def _parse_vars(lines, stop_at):
        for line in lines:
            if stop_at(line):
                break
            elif not line or line.startswith('#'):
                pass
            else:
                k, _, v = line.partition('= ')
                k = k.rstrip(':').rstrip(' ')
                yield k, v

    @staticmethod
    def _parse_rules(lines, stop_at):
        target, deps, recipe = None, [], []
        for line in lines:
            if stop_at(line):
                break
            elif line == '# Not a target:':
                not_a_target = True
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

    @classmethod
    def parse(cls, *make_args):
        '''Create a Makefile object from running make --print-data-base.

        Run make with appropriate options to build nothing, but instead print
        its internal database, and then parse this database output into a
        new Makefile instance. Any arguments passed to this method are passed
        on to the make command line.
        '''
        ret = cls()
        argv = ['make', '--print-data-base', '--question'] + list(make_args)
        lines = call_output_lines(argv)
        for line in lines:
            if line == '# Variables':
                break

        stop_at = lambda l: l == '# Implicit Rules'
        ret.variables = dict(cls._parse_vars(lines, stop_at))

        ret.rules = list(cls._parse_rules(lines, lambda l: False))

        return ret

    def __init__(self):
        self.variables = {}
        self.rules = []


def main(*make_args):
    # Pass -C and -f (and other) options on to make...
    m = Makefile.parse(*make_args)
    for target, deps, recipe in m.rules:
        print('{} <= {}'.format(target, ', '.join(deps)))


if __name__ == '__main__':
    import sys
    sys.exit(main(*sys.argv[1:]))
