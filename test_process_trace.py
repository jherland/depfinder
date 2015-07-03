import logging
import os
from pathlib import Path
import shutil
from subprocess import DEVNULL
from tempfile import TemporaryDirectory
import unittest

from process_trace import ProcessTrace
import strace_helper
import test_utils


logging.basicConfig(level=logging.DEBUG)
test_utils.prepare_trace_environment()


class TestProcessTrace(unittest.TestCase):

    maxDiff = 4096

    @classmethod
    def _init_c(cls, p):
        p.read('/etc/ld.so.cache')
        p.check('/etc/ld.so.preload', False)
        p.read('/usr/lib/libc.so.6')
        locale_vars = {
            'LANG', 'LC_ALL', 'LC_CTYPE', 'LC_MESSAGES', 'LC_NUMERIC'}
        if locale_vars & set(p.env.keys()):
            p.read('/usr/lib/locale/locale-archive')

    @classmethod
    def _init_sh(cls, p):
        cls._init_c(p)
        p.read('/usr/lib/libdl.so.2')
        p.read('/usr/lib/libncursesw.so.5')
        p.read('/usr/lib/libreadline.so.6')
        p.write('/dev/tty')
        p.read('/proc/meminfo')
        if 'PWD' in p.env:
            p.check(p.env['PWD'], True)
            p.check('.', True)

    @classmethod
    def _init_make(cls, p):
        cls._init_c(p)
        p.read('/usr/lib/libatomic_ops.so.1')
        p.read('/usr/lib/libc.so.6')
        p.read('/usr/lib/libcrypt.so.1')
        p.read('/usr/lib/libdl.so.2')
        p.read('/usr/lib/libffi.so.6')
        p.read('/usr/lib/libgc.so.1')
        p.read('/usr/lib/libgmp.so.10')
        p.read('/usr/lib/libguile-2.0.so.22')
        p.read('/usr/lib/libltdl.so.7')
        p.read('/usr/lib/libm.so.6')
        p.read('/usr/lib/libpthread.so.0')
        p.read('/usr/lib/libunistring.so.2')

        p.check('.', True)
        p.read('.')
        p.check('RCS', False)
        p.check('SCCS', False)
        p.check('/usr/gnu/include', False)
        p.check('/usr/local/include', True)
        p.check('/usr/include', True)

    @classmethod
    def _emulate_path_lookup(cls, p, cmd, only_missing=False):
        for path in test_utils.do_sh_path_lookup(cmd, p.env['PATH']):
            if not only_missing or not path.exists():
                p.check(path, path.exists())
        return path

    @classmethod
    def _launched_from_sh(cls, p):
        '''Adjust expected process details for a process launched from sh.'''
        p.env = test_utils.modified_env(p.env, {
            '_': p.executable,
            'OLDPWD': None,  # remove
            'PWD': p.cwd.as_posix(),
            'PS1': None,  # remove
            'SHLVL': str(int(p.env.get('SHLVL', 0)) + 1),
        })

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

    @classmethod
    def _check_with_parents(cls, p, path, exists, include_root=False):
        p.check(path, exists)
        for parent in Path(path).parents:
            if not include_root and parent == Path(parent.root):
                break
            p.check(parent, True)

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

    def expect_trace(self, argv, cwd=None, adjust_env=None, read=None,
                     write=None, check=None, exit_code=0):
        '''Helper method for setting up an expected ProcessTrace object.'''
        cwd = Path.cwd() if cwd is None else Path(cwd)
        if argv[0].startswith('./'):
            executable = Path(cwd, argv[0])
        else:
            executable = Path(shutil.which(argv[0]))
        env = os.environ.copy()
        if adjust_env is not None:
            for k, v in adjust_env.items():
                if v is None:
                    if k in env:
                        del env[k]
                else:
                    env[k] = v

        p = ProcessTrace(
            cwd=cwd, executable=executable, argv=argv, env=env,
            paths_read=read, paths_written=write, paths_checked=check,
            exit_code=exit_code)
        return p

    def test_simple_echo(self):
        argv = ['echo', 'Hello World']
        expect = self.expect_trace(argv)
        self._init_c(expect)

        self.run_test(expect, argv)

    def test_cp_one_file(self):
        with TemporaryDirectory() as tmpdir:
            p1, p2 = Path(tmpdir, 'foo'), Path(tmpdir, 'bar')
            with p1.open('w'):
                pass

            argv = ['cp', p1.as_posix(), p2.as_posix()]
            expect = self.expect_trace(
                argv,
                read=[
                    '/usr/lib/libacl.so.1',
                    '/usr/lib/libattr.so.1',
                    p1,
                ],
                write=[
                    p2,
                ],
                check=[
                    (p1, True),
                    (p2, False),
                ])
            self._init_c(expect)

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
            expect = self.expect_trace(argv, cwd=tmpdir, read=[script])
            self._init_sh(expect)

            self.run_test(expect, argv, cwd=tmpdir)

    def test_shell_scipt_with_fork(self):
        with TemporaryDirectory() as tmpdir:
            script = Path(tmpdir, 'fork.sh')
            with script.open('w') as f:
                f.write('#!/bin/sh\n\ndmesg\n')
            script.chmod(0o755)

            argv = [script.as_posix()]
            expect_sh = self.expect_trace(argv, read=[script])
            self._init_sh(expect_sh)
            self._emulate_path_lookup(expect_sh, 'dmesg')

            expect_dmesg = self.expect_trace(['dmesg'], read=['/dev/kmsg'])
            self._init_c(expect_dmesg)
            self._launched_from_sh(expect_dmesg)
            expect_sh.children.append(expect_dmesg)

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
            expect_gcc = self.expect_trace(
                argv,
                read=['/usr/lib/libm.so.6'],
                check=[
                    ('/lib/.', True),
                    ('/lib/../lib/.', True),
                    ('/lib/x86_64-unknown-linux-gnu/5.1.0/.', False),
                    ('/usr/lib/.', True),
                    ('/usr/lib/../lib/.', True),
                    ('/usr/lib/gcc/x86_64-unknown-linux-gnu/.', True),
                    ('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/', True),
                    ('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/.', True),
                    ('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../.', True),
                    ('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../lib/.', True),
                    ('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/bin/.', False),
                    ('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/bin/as', False),
                    ('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/bin/x86_64-unknown-linux-gnu/5.1.0/.', False),
                    ('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/bin/x86_64-unknown-linux-gnu/5.1.0/as', False),
                    ('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/lib/.', False),
                    ('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/lib/../lib/.', False),
                    ('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/lib/specs', False),
                    ('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/lib/x86_64-unknown-linux-gnu/5.1.0/.', False),
                    ('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/lib/x86_64-unknown-linux-gnu/5.1.0/specs', False),
                    ('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../x86_64-unknown-linux-gnu/5.1.0/.', False),
                    ('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/as', False),
                    ('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/cc1', True),
                    ('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/specs', False),
                    ('/usr/lib/gcc/x86_64-unknown-linux-gnu/as', False),
                    ('/usr/lib/gcc/x86_64-unknown-linux-gnu/specs', False),
                    ('/usr/lib/x86_64-unknown-linux-gnu/5.1.0/.', False),
                ])
            self._init_c(expect_gcc)
            gcc = self._emulate_path_lookup(expect_gcc, 'gcc')
            self._check_with_parents(expect_gcc, gcc, True)
            self._check_with_parents(expect_gcc, c_file, True)
            self._check_with_parents(expect_gcc, o_file, False)

            expect_cc1 = self.expect_trace(
                argv=[
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
                ],
                read=[
                    c_file.as_posix(),
                    '/dev/urandom',
                    '/proc/meminfo',
                    '/usr/include/stdc-predef.h',
                    '/usr/lib/libdl.so.2',
                    '/usr/lib/libgmp.so.10',
                    '/usr/lib/libm.so.6',
                    '/usr/lib/libmpc.so.3',
                    '/usr/lib/libmpfr.so.4',
                    '/usr/lib/libz.so.1',
                ],
                check=[
                    (c_file.as_posix() + '.gch', False),
                    ('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/', True),
                    ('/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/../../../../x86_64-unknown-linux-gnu/include', False),
                ])
            self._launched_from_gcc(expect_cc1, argv)
            self._init_c(expect_cc1)
            self._check_with_parents(expect_cc1, '/usr/include/stdc-predef.h.gch', False)
            self._check_with_parents(expect_cc1, '/usr/include/stdc-predef.h', True)
            self._check_with_parents(expect_cc1, '/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/include-fixed/stdc-predef.h', False)
            self._check_with_parents(expect_cc1, '/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/include-fixed/stdc-predef.h.gch', False)
            self._check_with_parents(expect_cc1, '/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/include/stdc-predef.h', False)
            self._check_with_parents(expect_cc1, '/usr/lib/gcc/x86_64-unknown-linux-gnu/5.1.0/include/stdc-predef.h.gch', False)
            self._check_with_parents(expect_cc1, '/usr/local/include/stdc-predef.h', False)
            self._check_with_parents(expect_cc1, '/usr/local/include/stdc-predef.h.gch', False)
            expect_gcc.children.append(expect_cc1)

            expect_as = self.expect_trace(
                argv=['as', '--64', '-o', o_file.as_posix()],
                read=[
                    '/usr/lib/libbfd-2.25.0.so',
                    '/usr/lib/libdl.so.2',
                    '/usr/lib/libopcodes-2.25.0.so',
                    '/usr/lib/libz.so.1',
                ],
                write=[o_file],
                check=[(o_file, False)])
            self._emulate_path_lookup(expect_as, 'as', only_missing=True)
            self._launched_from_gcc(expect_as, argv)
            self._init_c(expect_as)
            expect_gcc.children.append(expect_as)

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
            expect_make = self.expect_trace(
                argv,
                cwd=tmpdir,
                read=[makefile.name],
                check=[
                    (makefile.name, True),
                    (target.name, False),
                    (target.name, True),
                ])
            self._init_make(expect_make)

            expect_rule = self.expect_trace(
                argv=['/bin/sh', '-c', 'echo "Hello, World!" > {}'.format(
                    target.name)],
                cwd=tmpdir,
                write=[target.name])
            self._launched_from_make(expect_rule)
            self._init_sh(expect_rule)
            expect_make.children.append(expect_rule)

            self.assertFalse(target.exists())
            self.run_test(expect_make, argv, cwd=tmpdir)
            self.assertTrue(target.exists())


if __name__ == '__main__':
    unittest.main()
