import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from makeparser import Makefile
import test_utils


logging.basicConfig(level=logging.DEBUG)
test_utils.prepare_trace_environment()


class TestMakefile_empty(unittest.TestCase):
    def run(self, *args, **kwargs):
        with TemporaryDirectory() as tmpdir:
            self.testdir = Path(tmpdir)
            self.m = Makefile.parse('-C', str(self.testdir))
            super().run(*args, **kwargs)

    def test_env_vars(self):
        # environment
        self.assertEqual(self.m.variables['PATH'], os.environ['PATH'])

    def test_make_vars(self):
        # makefile
        self.assertEqual(self.m.variables['RM'], 'rm -f')
        # default
        self.assertEqual(self.m.variables['CXX'], 'g++')

    def test_rules(self):
        self.assertTrue('.DEFAULT' in self.m.rules)
        rule = self.m.rules['.DEFAULT']
        self.assertEqual(rule.deps, [])
        self.assertEqual(rule.recipe, [])


class TestMakefile_simple(unittest.TestCase):

    maxDiff = None

    Makefile = '''\
PROGRAM = hello

$(PROGRAM): $(PROGRAM).source
\tcp $^ $@

.PHONY: clean
clean:
\trm -f $(PROGRAM)
'''

    hello_source = 'foobar\n'

    def run(self, *args, **kwargs):
        with TemporaryDirectory() as tmpdir:
            self.testdir = Path(tmpdir)
            self.makefile_path = self.testdir / 'Makefile'
            self.source_path = self.testdir / 'hello.source'
            self.target_path = self.testdir / 'hello'
            with self.makefile_path.open('w') as f:
                f.write(self.Makefile)
            with self.source_path.open('w') as f:
                f.write(self.hello_source)
            self.m = Makefile.parse('-C', str(self.testdir))
            super().run(*args, **kwargs)

    def test_vars(self):
        self.assertEqual(self.m.variables['PROGRAM'], 'hello')

    def test_rules(self):
        self.assertTrue('hello' in self.m.rules)
        rule = self.m.rules['hello']
        self.assertEqual(rule.deps, ['hello.source'])
        self.assertEqual(rule.recipe, ['cp $^ $@'])


if __name__ == '__main__':
    unittest.main()
