import logging
import os
from pathlib import Path
import shutil
from subprocess import check_output, DEVNULL
from tempfile import TemporaryDirectory
import unittest

from process_trace import ProcessTrace
import strace_helper
import test_utils


logging.basicConfig(level=logging.DEBUG)
test_utils.prepare_trace_environment()


def load_libs_from_ld_so_cache():
    d = {}
    for line in check_output(['ldconfig', '-p']).decode('ascii').splitlines():
        try:
            s, path = line.strip().split(' => ')
            if not s.startswith('lib') or not 'x86-64' in s:
                raise ValueError
            name = s.split('.', 1)[0][3:]
            if name not in d:
                d[name] = path  # prefer the first entry for 'name'
        except:
            pass
    return d


class ExpectedProcessTrace(ProcessTrace):
    '''Helper class for setting up an expected ProcessTrace object.

    In tests, we set up expected ProcessTrace instances to compare against
    ProcessTrace instances built from actual trace events.

    This class consists mostly of helper methods for filling in common
    processes' execution patterns.
    '''

    Libs = load_libs_from_ld_so_cache()

    def __init__(self, argv, *, cwd=None, env=None, exit_code=0):
        cwd = Path.cwd() if cwd is None else Path(cwd)
        if argv[0].startswith('./'):
            executable = Path(cwd, argv[0])
        else:
            executable = Path(shutil.which(argv[0]))
        if env is None:
            env = os.environ.copy()

        self._child_mods = []  # callables to modify children of this process

        super().__init__(cwd=cwd, executable=executable, argv=argv, env=env,
                         exit_code=exit_code)

    def fork_exec(self, argv, **kwargs):
        child = self.__class__(argv, **kwargs)
        for mod in self._child_mods:
            mod(child)
        self.children.append(child)
        return child

    def path_lookup(self, name, only_missing=False):
        for path in test_utils.do_sh_path_lookup(name, self.env['PATH']):
            if not only_missing or not path.exists():
                self.check(path, path.exists())
        return path

    def check_parents(self, path, exists, stop_at='/'):
        '''Check path, and path's parent directories.

        Call self.check(path, exists), then self.check(parent, True) for all
        of path's parent directories until 'stop_at' is encountered.
        '''
        self.check(path, exists)
        root = None if stop_at is None else Path(stop_at)
        for parent in Path(path).parents:
            if parent == root:
                break
            self.check(parent, True)

    def ld(self, *libs):
        self.read('/etc/ld.so.cache')
        self.check('/etc/ld.so.preload', False)
        self.read(self.Libs['c'])
        for lib in libs:
            self.read(self.Libs[lib])

        loc_vars = {'LANG', 'LC_ALL', 'LC_CTYPE', 'LC_MESSAGES', 'LC_NUMERIC'}
        if loc_vars & set(self.env.keys()):
            self.read('/usr/lib/locale/locale-archive')

    def sh(self):
        self.ld('dl', 'ncursesw', 'readline')
        self.write('/dev/tty')
        self.read('/proc/meminfo')
        if 'PWD' in self.env:
            self.check(self.env['PWD'], True)
            self.check('.', True)

        def sh_mod_child_env(child):
            child.env = test_utils.modified_env(child.env, {
                '_': child.executable,
                'OLDPWD': None,  # remove
                'PWD': child.cwd.as_posix(),
                'PS1': None,  # remove
                'SHLVL': str(int(self.env.get('SHLVL', 0)) + 1),
            })
        self._child_mods.append(sh_mod_child_env)


class TestProcessTrace(unittest.TestCase):

    maxDiff = 40960

    @classmethod
    def _init_gcc(cls, p):
        p.ld('m')

        def pairify(iterable):
            prev = None
            for cur in iterable:
                if prev is not None:
                    yield prev, cur
                prev = cur

        for opt, arg in pairify(p.argv):
            if opt == '-c':
                c_file = Path(arg)
            elif opt == '-o':
                o_file = Path(arg)
        assert c_file and o_file

        gcc_executable = p.path_lookup('gcc')
        p.check_parents(gcc_executable, True)
        p.check_parents(c_file, True)
        p.check_parents(o_file, False)

        # TODO: Research and refactor these:
        p.check('/lib/.', True),
        p.check('/lib/../lib/.', True),
        p.check('/lib/x86_64-unknown-linux-gnu/5.1.0/.', False),
        p.check('/usr/lib/.', True),
        p.check('/usr/lib/../lib/.', True),
        p.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/.', True),
        p.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/', True),
        p.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/.', True),
        p.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../.', True),
        p.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../lib/.', True),
        p.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/bin/.', False),
        p.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/bin/as', False),
        p.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/bin/x86_64-unknown-linux-gnu/5.1.0/.', False),
        p.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/bin/x86_64-unknown-linux-gnu/5.1.0/as', False),
        p.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/lib/.', False),
        p.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/lib/../lib/.', False),
        p.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/lib/specs', False),
        p.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/lib/x86_64-unknown-linux-gnu/5.1.0/.', False),
        p.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/lib/x86_64-unknown-linux-gnu/5.1.0/specs', False),
        p.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../x86_64-unknown-linux-gnu/5.1.0/.', False),
        p.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/as', False),
        p.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/cc1', True),
        p.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/specs', False),
        p.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/as', False),
        p.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/specs', False),
        p.check('/usr/lib/x86_64-unknown-linux-gnu/5.1.0/.', False),

        cc1_p = ExpectedProcessTrace([
            '/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/cc1',
            '-quiet',
            c_file.as_posix(),
            '-quiet',
            '-dumpbase',
            c_file.name,
            '-mtune=generic',
            '-march=x86-64',
            '-auxbase-strip',
            o_file.as_posix(),
            '-o',
            '-'
        ])
        cls._launched_from_gcc(cc1_p, p.argv)
        cc1_p.ld('dl', 'gmp', 'm', 'mpc', 'mpfr', 'z')
        cc1_p.read(c_file.as_posix())
        cc1_p.read('/dev/urandom')
        cc1_p.read('/proc/meminfo')
        cc1_p.read('/usr/include/stdc-predef.h')
        cc1_p.check(c_file.as_posix() + '.gch', False)
        cc1_p.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/', True),
        cc1_p.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/include', False),
        cc1_p.check_parents('/usr/include/stdc-predef.h.gch', False)
        cc1_p.check_parents('/usr/include/stdc-predef.h', True)
        cc1_p.check_parents('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/include-fixed/stdc-predef.h', False)
        cc1_p.check_parents('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/include-fixed/stdc-predef.h.gch', False)
        cc1_p.check_parents('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/include/stdc-predef.h', False)
        cc1_p.check_parents('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/include/stdc-predef.h.gch', False)
        cc1_p.check_parents('/usr/local/include/stdc-predef.h', False)
        cc1_p.check_parents('/usr/local/include/stdc-predef.h.gch', False)
        p.children.append(cc1_p)

        as_p = ExpectedProcessTrace(['as', '--64', '-o', o_file.as_posix()])
        as_p.path_lookup('as', only_missing=True)
        cls._launched_from_gcc(as_p, p.argv)
        as_p.ld('bfd-2', 'dl', 'opcodes-2', 'z')
        as_p.write(o_file)
        as_p.check(o_file, False)
        p.children.append(as_p)

    @classmethod
    def _init_make(cls, p):
        p.ld('atomic_ops', 'crypt', 'dl', 'ffi', 'gc', 'gmp', 'guile-2',
             'ltdl', 'm', 'pthread', 'unistring')

        p.check('.', True)
        p.read('.')
        p.check('RCS', False)
        p.check('SCCS', False)
        p.check('/usr/gnu/include', False)
        p.check('/usr/local/include', True)
        p.check('/usr/include', True)

    @classmethod
    def _launched_from_gcc(cls, p, gcc_args):
        collect_options = []
        skip_next = False
        for arg in gcc_args[1:]:
            if skip_next:
                skip_next = False
            else:
                collect_options.append(arg)
                if arg == '-c':
                    skip_next = True
        collect_options.extend(['-mtune=generic', '-march=x86-64'])
        p.env = test_utils.modified_env(p.env, {
            'COLLECT_GCC': gcc_args[0],
            'COLLECT_GCC_OPTIONS': ' '.join(
                "'{}'".format(opt) for opt in collect_options),
        })

    @classmethod
    def _launched_from_make(cls, p):
        '''Adjust expected process details for a process launched from make.'''
        p.env = test_utils.modified_env(p.env, {
            'MAKEFLAGS': '',
            'MAKELEVEL': str(int(p.env.get('MAKELEVEL', 0)) + 1),
            'MFLAGS': '',
        })

    def run_trace(self, cmd_args, debug=False, cwd=None, **popen_args):
        strace_helper.logger.setLevel(
            logging.DEBUG if debug else logging.WARNING)
        popen_args.setdefault('stdout', DEVNULL)
        popen_args.setdefault('stderr', DEVNULL)
        p = ProcessTrace.from_events(cwd=cwd, events=strace_helper.run_trace(
            cmd_args, cwd=cwd, log_events=debug, **popen_args))
        return p

    def check_trace(self, expect, actual):
        # We cannot know the PIDs beforehand, so traverse through the actual
        # process tree, and copy .pid and .ppid over to the expected instances.
        def copy_pids(actual, expect):
            assert expect.pid is None
            expect.pid = actual.pid
            expect.ppid = actual.ppid
            for a, e in zip(actual.children, expect.children):
                copy_pids(a, e)
        copy_pids(actual, expect)

        self.assertEqual(expect.json(), actual.json())

    def run_test(self, expect, cmd_args, debug=False, **popen_args):
        actual = self.run_trace(cmd_args, debug, **popen_args)
        self.check_trace(expect, actual)

    def test_simple_echo(self):
        argv = ['echo', 'Hello World']
        expect = ExpectedProcessTrace(argv)
        expect.ld()

        self.run_test(expect, argv)

    def test_cp_one_file(self):
        with TemporaryDirectory() as tmpdir:
            p1, p2 = Path(tmpdir, 'foo'), Path(tmpdir, 'bar')
            p1.open('w').close()

            argv = ['cp', p1.as_posix(), p2.as_posix()]
            expect = ExpectedProcessTrace(argv)
            expect.ld('acl', 'attr')
            expect.check(p1, True)
            expect.check(p2, False)
            expect.read(p1)
            expect.write(p2)

            self.run_test(expect, argv)
            self.assertTrue(p1.exists())
            self.assertTrue(p2.exists())

    def test_simple_shell_scipt_with_cwd(self):
        with TemporaryDirectory() as tmpdir:
            script = './hello.sh'
            script_abs = Path(tmpdir, script)
            with script_abs.open('w') as f:
                f.write('#!/bin/sh\n\necho "Hello World"\n')
            script_abs.chmod(0o755)

            argv = [script]
            expect = ExpectedProcessTrace(argv, cwd=tmpdir)
            expect.sh()
            expect.read(script)

            self.run_test(expect, argv, cwd=tmpdir)

    def test_shell_scipt_with_fork(self):
        with TemporaryDirectory() as tmpdir:
            script = Path(tmpdir, 'fork.sh')
            with script.open('w') as f:
                f.write('#!/bin/sh\n\ndmesg\n')
            script.chmod(0o755)

            argv = [script.as_posix()]
            expect_sh = ExpectedProcessTrace(argv)
            expect_sh.sh()
            expect_sh.read(script)
            expect_sh.path_lookup('dmesg')

            expect_dmesg = expect_sh.fork_exec(['dmesg'])
            expect_dmesg.ld()
            expect_dmesg.read('/dev/kmsg')

            self.run_test(expect_sh, argv)

    def test_simple_gcc(self):
        with TemporaryDirectory() as tmpdir:
            c_file = Path(tmpdir, 'hello.c')
            o_file = Path(tmpdir, 'hello.o')
            with c_file.open('w') as f:
                f.write('int main() { return 0; }')

            argv = [
                'gcc', '-pipe',
                '-c', c_file.as_posix(),
                '-o', o_file.as_posix(),
            ]
            expect_gcc = ExpectedProcessTrace(argv)
            self._init_gcc(expect_gcc)

            self.assertFalse(o_file.exists())
            self.run_test(expect_gcc, argv, stdout=None, stderr=None)
            self.assertTrue(o_file.exists())

    def test_simple_makefile(self):
        with TemporaryDirectory() as tmpdir:
            makefile = Path(tmpdir, 'Makefile')
            target = Path(tmpdir, 'output_file')
            with makefile.open('w') as f:
                f.write('output_file:\n\techo "Hello, World!" > $@\n')

            argv = ['make']
            expect_make = ExpectedProcessTrace(argv, cwd=tmpdir)
            self._init_make(expect_make)
            expect_make.check(makefile.name, True)
            expect_make.read(makefile.name)
            expect_make.check(target.name, False)
            expect_make.check(target.name, True)

            argv_rule = ['/bin/sh', '-c', 'echo "Hello, World!" > {}'.format(
                target.name)]
            expect_rule = ExpectedProcessTrace(argv_rule, cwd=tmpdir)
            self._launched_from_make(expect_rule)
            expect_rule.sh()
            expect_rule.write(target.name)
            expect_make.children.append(expect_rule)

            self.assertFalse(target.exists())
            self.run_test(expect_make, argv, cwd=tmpdir)
            self.assertTrue(target.exists())


if __name__ == '__main__':
    unittest.main()
