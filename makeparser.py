#!/usr/bin/env python3

from subprocess import Popen, PIPE, DEVNULL, CalledProcessError


def call_output_lines(*args, **kwargs):
    '''Like subprocess.check_output(), but yield output lines, lazily.'''
    with Popen(*args, stdout=PIPE, universal_newlines=True, **kwargs) as p:
        for line in p.stdout:
            yield line.rstrip('\r\n')


class Makefile:

    class Rule:
        def __init__(self):
            self.target = None
            self.deps = []
            self.recipe = []
            self.is_target = True

        def __str__(self):
            ret = []
            if not self.is_target:
                ret.append('# Not a target:')
            ret.append('{}: {}'.format(self.target, ' '.join(self.deps)))
            for line in self.recipe:
                ret.append('\t' + line)
            return '\n'.join(ret)

        def __lt__(self, other):
            return (self.target, self.deps) < (other.target, other.deps)

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

    @classmethod
    def _parse_rules(cls, lines, stop_at):
        cur = cls.Rule()
        for line in lines:
            if stop_at(line):
                break
            elif not line:  # Empty line - between rules
                if cur.target is not None:
                    yield cur
                    cur = cls.Rule()
            elif line == '# Not a target:':
                cur.is_target = False
            elif line.startswith('#'):
                pass
            elif line.startswith('\t'):
                assert cur.target is not None
                cur.recipe.append(line[1:])
            else:
                cur.target, dep_s = line.split(':', 1)
                cur.deps = dep_s.split()

        assert cur.target is None

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
        lines = call_output_lines(argv, stderr=DEVNULL)
        for line in lines:
            if line == '# Variables':
                break

        stop_at = lambda l: l == '# Implicit Rules'
        ret.variables = dict(cls._parse_vars(lines, stop_at))

        rule_gen = cls._parse_rules(lines, lambda l: False)
        ret.rules = dict((r.target, r) for r in rule_gen)

        return ret

    def __init__(self):
        self.variables = {}  # key -> value
        self.rules = {}  # target name -> Rule object


def main(*make_args):
    m = Makefile.parse(*make_args)
    for rule in sorted(m.rules.values()):
        if rule.is_target:
            print('{} <- {}'.format(rule.target, ', '.join(rule.deps)))


if __name__ == '__main__':
    import sys
    sys.exit(main(*sys.argv[1:]))
