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
            if not s.startswith('lib') or 'x86-64' not in s:
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

    def copy_pids_from_actual(self, actual):
        '''Copy .pid and .ppid recursively from the given ProcessTrace.'''
        assert self.pid is None and self.ppid is None
        self.pid = actual.pid
        self.ppid = actual.ppid
        for exp_child, act_child in zip(self.children, actual.children):
            exp_child.copy_pids_from_actual(act_child)

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

    def check_gch(self, path):
        self.check(str(path) + '.gch', False)
        return path

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

    def gcc(self):
        self.ld('m')

        def pairify(iterable):
            prev = None
            for cur in iterable:
                if prev is not None:
                    yield prev, cur
                prev = cur

        for opt, arg in pairify(self.argv):
            if opt == '-c':
                c_file = Path(arg)
            elif opt == '-o':
                o_file = Path(arg)
        assert c_file and o_file

        gcc_executable = self.path_lookup('gcc')
        self.check_parents(gcc_executable, True)
        self.check_parents(c_file, True)
        self.check_parents(o_file, False)

        # TODO: Research and refactor these:
        self.check('/lib/.', True),
        self.check('/lib/../lib/.', True),
        self.check('/lib/x86_64-unknown-linux-gnu/5.1.0/.', False),
        self.check('/usr/lib/.', True),
        self.check('/usr/lib/../lib/.', True),
        self.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/.', True),
        self.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/', True),
        self.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/.', True),
        self.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../.', True),
        self.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../lib/.', True),
        self.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/bin/.', False),
        self.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/bin/as', False),
        self.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/bin/x86_64-unknown-linux-gnu/5.1.0/.', False),
        self.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/bin/x86_64-unknown-linux-gnu/5.1.0/as', False),
        self.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/lib/.', False),
        self.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/lib/../lib/.', False),
        self.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/lib/specs', False),
        self.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/lib/x86_64-unknown-linux-gnu/5.1.0/.', False),
        self.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/lib/x86_64-unknown-linux-gnu/5.1.0/specs', False),
        self.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../x86_64-unknown-linux-gnu/5.1.0/.', False),
        self.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/as', False),
        self.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/cc1', True),
        self.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/specs', False),
        self.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/as', False),
        self.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/specs', False),
        self.check('/usr/lib/x86_64-unknown-linux-gnu/5.1.0/.', False),

        def gcc_mod_child_env(child):
            collect_options = []
            skip_next = False
            for arg in self.argv[1:]:
                if skip_next:
                    skip_next = False
                else:
                    collect_options.append(arg)
                    if arg == '-c':
                        skip_next = True
            collect_options.extend(['-mtune=generic', '-march=x86-64'])
            child.env = test_utils.modified_env(child.env, {
                'COLLECT_GCC': self.argv[0],
                'COLLECT_GCC_OPTIONS': ' '.join(
                    "'{}'".format(opt) for opt in collect_options),
            })
        self._child_mods.append(gcc_mod_child_env)

        expect_cc1 = self.fork_exec([
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
        expect_cc1.ld('dl', 'gmp', 'm', 'mpc', 'mpfr', 'z')
        expect_cc1.read(c_file.as_posix())
        expect_cc1.read('/dev/urandom')
        expect_cc1.read('/proc/meminfo')
        expect_cc1.read('/usr/include/stdc-predef.h')
        expect_cc1.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/', True),
        expect_cc1.check('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/include', False),
        expect_cc1.check_parents(expect_cc1.check_gch('/usr/include/stdc-predef.h'), True)
        expect_cc1.check_parents(expect_cc1.check_gch('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/include-fixed/stdc-predef.h'), False)
        expect_cc1.check_parents(expect_cc1.check_gch('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/include/stdc-predef.h'), False)
        expect_cc1.check_parents(expect_cc1.check_gch('/usr/local/include/stdc-predef.h'), False)
        expect_cc1.check_gch(c_file)

        expect_as = self.fork_exec(['as', '--64', '-o', o_file.as_posix()])
        expect_as.path_lookup('as', only_missing=True)
        expect_as.ld('bfd-2', 'dl', 'opcodes-2', 'z')
        expect_as.write(o_file)
        expect_as.check(o_file, False)

    def make(self):
        self.ld('atomic_ops', 'crypt', 'dl', 'ffi', 'gc', 'gmp', 'guile-2',
                'ltdl', 'm', 'pthread', 'unistring')

        self.check('.', True)
        self.read('.')
        self.check('RCS', False)
        self.check('SCCS', False)
        self.check('/usr/gnu/include', False)
        self.check('/usr/local/include', True)
        self.check('/usr/include', True)

        def make_mod_child_env(child):
            child.env = test_utils.modified_env(child.env, {
                'MAKEFLAGS': '',
                'MAKELEVEL': str(int(child.env.get('MAKELEVEL', 0)) + 1),
                'MFLAGS': '',
            })
        self._child_mods.append(make_mod_child_env)


class TestProcessTrace(unittest.TestCase):

    maxDiff = 40960

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
        # process tree, and copy PIDs and PPIDs over to the expected instances.
        expect.copy_pids_from_actual(actual)

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

    def test_shell_cmd_with_exec(self):
        argv = ['/bin/sh', '-c', 'cat /dev/null']
        expect_sh = ExpectedProcessTrace(argv)
        expect_sh.sh()
        cat_path = expect_sh.path_lookup('cat')
        expect_sh.read(cat_path)  # really exec()
        expect_sh.read('/dev/null')

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
            expect_gcc.gcc()

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
            expect_make.make()
            expect_make.check(makefile.name, True)
            expect_make.read(makefile.name)
            expect_make.check(target.name, False)
            expect_make.check(target.name, True)

            argv_rule = ['/bin/sh', '-c', 'echo "Hello, World!" > {}'.format(
                target.name)]
            expect_rule = expect_make.fork_exec(argv_rule, cwd=tmpdir)
            expect_rule.sh()
            expect_rule.write(target.name)

            self.assertFalse(target.exists())
            self.run_test(expect_make, argv, cwd=tmpdir)
            self.assertTrue(target.exists())

    def test_collapsed_shell_scipt_with_fork(self):
        with TemporaryDirectory() as tmpdir:
            script = Path(tmpdir, 'fork.sh')
            with script.open('w') as f:
                f.write('#!/bin/sh\n\ndmesg\n')
            script.chmod(0o755)

            argv = [script.as_posix()]
            expect = ExpectedProcessTrace(argv)
            expect.sh()
            expect.read(script)
            expect.path_lookup('dmesg')
            expect.read('/usr/bin/dmesg')  # exec(dmesg) => read(dmesg)
            expect.read('/dev/kmsg')  # from dmesg subprocess

            actual = self.run_trace(argv)
            collapsed = actual.collapsed()
            self.check_trace(expect, collapsed)


if __name__ == '__main__':
    unittest.main()
