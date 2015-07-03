import logging
import os
from pathlib import Path
import shutil
from subprocess import DEVNULL
from tempfile import TemporaryDirectory
import unittest

import strace_helper
import test_utils


logging.basicConfig(level=logging.DEBUG)
test_utils.prepare_trace_environment()

# The following are common trace events seen at the start of many processes.
LOADER = [
    ('check', ('/etc/ld.so.preload', False)),
    ('read', ('/etc/ld.so.cache',)),
]

LIBC = [('read', ('/usr/lib/libc.so.6',))]
LIBCAP = [('read', ('/usr/lib/libcap.so.2',))]
LIBACL = [('read', ('/usr/lib/libacl.so.1',))]
LIBATTR = [('read', ('/usr/lib/libattr.so.1',))]
LIBREADLINE = [('read', ('/usr/lib/libreadline.so.6',))]
LIBNCURSES = [('read', ('/usr/lib/libncursesw.so.5',))]
LIBDL = [('read', ('/usr/lib/libdl.so.2',))]
LIBGUILE = [('read', ('/usr/lib/libguile-2.0.so.22',))]
LIBPTHREAD = [('read', ('/usr/lib/libpthread.so.0',))]

INIT_C = LOADER + LIBC
INIT_C_LOCALE = INIT_C

INIT_LS = LOADER + LIBCAP + LIBACL + LIBC + LIBATTR
INIT_MV = LOADER + LIBACL + LIBATTR + LIBC
INIT_SH = (
    LOADER + LIBREADLINE + LIBNCURSES + LIBDL + LIBC + [
        ('write', ('/dev/tty',)),
        ('read', ('/proc/meminfo',)),
        ('check', (os.getcwd(), True)),
        ('check', ('.', True)),
    ])
INIT_MAKE = (
    LOADER + LIBGUILE + LIBDL + LIBPTHREAD + LIBC + [
        ('read', ('/usr/lib/libgc.so.1',)),
        ('read', ('/usr/lib/libffi.so.6',)),
        ('read', ('/usr/lib/libunistring.so.2',)),
        ('read', ('/usr/lib/libgmp.so.10',)),
        ('read', ('/usr/lib/libltdl.so.7',)),
        ('read', ('/usr/lib/libcrypt.so.1',)),
        ('read', ('/usr/lib/libm.so.6',)),
        ('read', ('/usr/lib/libatomic_ops.so.1',)),
    ])

# Sentinel for disabling the complete even trace checks in run_test()
WHATEVER = object()


class Test_run_trace(unittest.TestCase):

    maxDiff = 4096

    def run_trace(self, argv, debug=False, **popen_args):
        strace_helper.logger.setLevel(
            logging.DEBUG if debug else logging.WARNING)

        return strace_helper.run_trace(
            argv, log_events=debug,
            stdout=DEVNULL, stderr=DEVNULL, **popen_args)

    def check_events(self, actual, pid, argv, events, exit_code=0, env=None):
        executable = shutil.which(argv[0])

        # First event should always be exec
        a_pid, a_event, (a_executable, a_argv, a_env) = actual.pop(0)
        self.assertGreater(a_pid, 0)
        self.assertEqual(a_pid, pid)
        self.assertEqual(a_event, 'exec')
        self.assertEqual(a_executable, executable)
        self.assertListEqual(a_argv, argv)
        self.assertDictEqual(a_env, dict(os.environ) if env is None else env)

        # Last event should always be exit
        a_pid, a_event, a_exit_code = actual.pop()
        self.assertEqual(a_pid, pid)
        self.assertEqual(a_event, 'exit')
        self.assertEqual(a_exit_code, (exit_code,))

        if events is not WHATEVER:
            expect = [(pid, event, args) for (event, args) in events]
            self.assertListEqual(expect, actual)

    def run_test(self, argv, expect, exit_code=0, debug=False, **popen_args):
        actual = list(self.run_trace(argv, debug, **popen_args))
        pid = actual[0][0]  # peek at first event to deduce PID
        return self.check_events(actual, pid, argv, expect, exit_code)

    def test_simple_true(self):
        self.run_test(['true'], INIT_C)

    def test_simple_false(self):
        self.run_test(['false'], INIT_C, 1)

    def test_simple_echo(self):
        self.run_test(['echo', 'Hello World'], INIT_C_LOCALE)

    def test_echo_w_quotes(self):
        self.run_test(['echo', '"Hello World"'], INIT_C_LOCALE)

    def test_simple_cat(self):
        self.run_test(['cat', '/dev/null'], INIT_C_LOCALE + [
            ('read', ('/dev/null',)),
        ])

    def test_cat_missing_file(self):
        self.run_test(['cat', '/proc/missing_file'], INIT_C_LOCALE + [
            ('check', ('/proc/missing_file', False)),
        ], 1)

    def test_dmesg(self):
        self.run_test(['dmesg'], INIT_C_LOCALE + [
            ('read', ('/dev/kmsg',)),
        ], 0)

    def test_touch_new_file(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir, 'new_file')
            self.assertFalse(path.exists())
            self.run_test(['touch', path.as_posix()], INIT_C_LOCALE + [
                ('write', (path.as_posix(),)),  # open()
                ('write', (path.as_posix(),)),  # utimensat()
            ], 0)
            self.assertTrue(path.exists())

    def test_touch_existing_file(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir, 'existing_file')
            with path.open('w'):
                pass
            self.assertTrue(path.exists())
            self.run_test(['touch', path.as_posix()], INIT_C_LOCALE + [
                ('write', (path.as_posix(),)),  # open()
                ('write', (path.as_posix(),)),  # utimensat()
            ], 0)
            self.assertTrue(path.exists())

    def test_empty_ls(self):
        with TemporaryDirectory() as tmpdir:
            self.run_test(['ls', tmpdir], INIT_LS + [
                ('check', (tmpdir, True)),
                ('read', (tmpdir,)),
            ], 0)

    def test_nonempty_long_ls(self):
        with TemporaryDirectory() as tmpdir:
            for name in ['foo', 'bar', 'baz']:
                with Path(tmpdir, name).open('w'):
                    pass
            self.run_test(['ls', '-a', '-l', tmpdir], INIT_LS + [
                ('check', (tmpdir, True)),
                ('check', (tmpdir, True)),
                ('check', (tmpdir, True)),
                ('read', ('/etc/nsswitch.conf',)),
                ('read', ('/etc/ld.so.cache',)),
                ('read', ('/usr/lib/libnss_files.so.2',)),
                ('read', ('/etc/passwd',)),
                ('read', ('/etc/group',)),
                ('read', (tmpdir,)),
                ('check', (tmpdir + '/.', True)),
                ('check', (tmpdir + '/.', True)),
                ('check', (tmpdir + '/.', True)),
                ('check', (tmpdir + '/..', True)),
                ('check', (tmpdir + '/..', True)),
                ('check', (tmpdir + '/..', True)),
                ('read', ('/etc/passwd',)),
                ('read', ('/etc/group',)),
                ('check', (tmpdir + '/baz', True)),
                ('check', (tmpdir + '/baz', True)),
                ('check', (tmpdir + '/baz', True)),
                ('check', (tmpdir + '/bar', True)),
                ('check', (tmpdir + '/bar', True)),
                ('check', (tmpdir + '/bar', True)),
                ('check', (tmpdir + '/foo', True)),
                ('check', (tmpdir + '/foo', True)),
                ('check', (tmpdir + '/foo', True)),
                ('read', ('/etc/localtime',)),
                ('check', ('/etc/localtime', True)),
                ('check', ('/etc/localtime', True)),
                ('check', ('/etc/localtime', True)),
                ('check', ('/etc/localtime', True)),
            ], 0)

    def test_mv_one_file(self):
        with TemporaryDirectory() as tmpdir:
            p1, p2 = Path(tmpdir, 'foo'), Path(tmpdir, 'bar')
            with p1.open('w'):
                pass
            self.run_test(['mv', p1.as_posix(), p2.as_posix()], INIT_MV + [
                ('check', (tmpdir + '/bar', False)),
                ('check', (tmpdir + '/foo', True)),
                ('check', (tmpdir + '/bar', False)),
                ('write', (tmpdir + '/foo',)),
                ('write', (tmpdir + '/bar',)),
            ], 0)
            self.assertFalse(p1.exists())
            self.assertTrue(p2.exists())

    def test_cp_one_file(self):
        with TemporaryDirectory() as tmpdir:
            p1, p2 = Path(tmpdir, 'foo'), Path(tmpdir, 'bar')
            with p1.open('w'):
                pass
            self.run_test(['cp', p1.as_posix(), p2.as_posix()], INIT_MV + [
                ('check', (tmpdir + '/bar', False)),
                ('check', (tmpdir + '/foo', True)),
                ('check', (tmpdir + '/bar', False)),
                ('read', (tmpdir + '/foo',)),
                ('write', (tmpdir + '/bar',)),
            ], 0)
            self.assertTrue(p1.exists())
            self.assertTrue(p2.exists())

    def test_simple_python(self):
        self.run_test(['python', '-c', 'print("Hello, World!")'], WHATEVER)

    c_program = '''\
#include <stdio.h>

int main() {
    puts("Hello, World!");
}
'''

    def test_simple_gcc(self):
        with TemporaryDirectory() as tmpdir:
            c_file = Path(tmpdir, 'hello.c')
            o_file = Path(tmpdir, 'hello.o')
            with c_file.open('w') as f:
                f.write(self.c_program)
            self.assertFalse(o_file.exists())
            self.run_test(
                ['gcc', '-c', c_file.as_posix(), '-o', o_file.as_posix()],
                WHATEVER)
            self.assertTrue(o_file.exists())

    def test_gcc_with_cwd(self):
        with TemporaryDirectory() as tmpdir:
            c_file = 'hello.c'
            x_file = 'hello'
            with Path(tmpdir, c_file).open('w') as f:
                f.write(self.c_program)
            self.assertFalse(Path(tmpdir, x_file).exists())
            self.run_test(
                ['gcc', '-c', c_file, '-o', x_file],
                WHATEVER, cwd=tmpdir)
            self.assertTrue(Path(tmpdir, x_file).exists())

    simple_shell_script = '''\
#!/bin/sh

echo "Hello World"
'''

    def test_simple_shell_scipt_without_x_bit(self):
        with TemporaryDirectory() as tmpdir:
            script = Path(tmpdir, 'hello.sh')
            with script.open('w') as f:
                f.write(self.simple_shell_script)
            # Cannot use run_test, as execve() will return EACCES, which yields
            # a 'check' event instead of the usual 'exec'...
            actual = list(self.run_trace([script.as_posix()]))
            pid = actual[0][0]
            self.assertListEqual(actual, [
                (pid, 'check', (script.as_posix(), True)),
                (pid, 'exit', (1,)),
            ])

    def test_simple_shell_scipt(self):
        with TemporaryDirectory() as tmpdir:
            script = Path(tmpdir, 'hello.sh')
            with script.open('w') as f:
                f.write(self.simple_shell_script)
            script.chmod(0o755)
            self.run_test([script.as_posix()], INIT_SH + [
                ('read', (script.as_posix(),)),
            ])

    shell_script_with_fork = '''\
#!/bin/sh

dmesg
'''

    def test_shell_scipt_with_fork(self):
        with TemporaryDirectory() as tmpdir:
            script = Path(tmpdir, 'hello.sh')
            with script.open('w') as f:
                f.write(self.shell_script_with_fork)
            script.chmod(0o755)
            argv = [script.as_posix()]
            actual = self.run_trace(argv)
            # split into two lists, one for each PID
            pids = {}
            for pid, event, args in actual:
                pids.setdefault(pid, []).append((pid, event, args))
            self.assertEqual(len(pids), 2)
            ppid, cpid = sorted(pids.keys())  # parent PID < child PID

            dmesg_checks = []
            for p in test_utils.do_sh_path_lookup('dmesg'):
                dmesg_checks.append(('check', (p.as_posix(), p.exists())))
            last = dmesg_checks.pop()
            assert last[1][1] is True
            dmesg_checks.extend([last] * 10)

            # Check events generated by sh process
            self.check_events(pids[ppid], ppid, argv, INIT_SH + [
                ('read', (script.as_posix(),)),
                ('check', ('.', True)),
            ] + dmesg_checks + [
                ('fork', (cpid,)),
            ])

            # Check events generated by dmesg process
            # sh applies the following env changes to its subprocesses
            env = test_utils.modified_env(os.environ, {
                '_': p.as_posix(),
                'SHLVL': str(int(os.environ.get('SHLVL', 0)) + 1),
                'OLDPWD': None,  # delete
                'PS1': None,  # delete
            })
            self.check_events(
                pids[cpid], cpid, ['dmesg'], INIT_C_LOCALE + [
                    ('read', ('/dev/kmsg',)),
                ], env=env)

    makefile = '''\
output_file:
\techo "Hello, World!" > $@
'''

    def test_simple_makefile(self):
        with TemporaryDirectory() as tmpdir:
            makefile_path = Path(tmpdir, 'Makefile')
            with makefile_path.open('w') as f:
                f.write(self.makefile)
            argv = ['make', '-C', tmpdir]
            actual = self.run_trace(argv)
            # split into two lists, one for each PID
            pids = {}
            for pid, event, args in actual:
                pids.setdefault(pid, []).append((pid, event, args))
            self.assertEqual(len(pids), 2)
            ppid, cpid = sorted(pids.keys())  # parent PID < child PID

            # Check events generated by make process
            self.check_events(pids[ppid], ppid, argv, INIT_MAKE + [
                ('chdir', (tmpdir,)),
                ('check', ('/usr/include', True)),
                ('check', ('/usr/gnu/include', False)),
                ('check', ('/usr/local/include', True)),
                ('check', ('/usr/include', True)),
                ('check', ('.', True)),
                ('read', ('.',)),
                ('read', ('Makefile',)),
                ('check', ('RCS', False)),
                ('check', ('SCCS', False)),
                ('check', ('Makefile', True)),
                ('check', ('output_file', False)),
                ('fork', (cpid,)),
                ('check', ('output_file', True)),
                ('chdir', (os.getcwd(),)),
            ])

            # Check events generated by make subprocess
            # make applies the following env changes to its subprocesses
            env = test_utils.modified_env(os.environ, {
                'MAKEFLAGS': 'w',
                'MAKELEVEL': '1',
                'MFLAGS': '-w',
            })
            argv = ['/bin/sh', '-c', 'echo "Hello, World!" > output_file']
            self.check_events(pids[cpid], cpid, argv, INIT_SH + [
                ('write', ('output_file',)),
            ], env=env)

            self.assertTrue(Path(tmpdir, 'output_file').exists())


if __name__ == '__main__':
    unittest.main()
