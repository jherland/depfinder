import logging
import os
from pathlib import Path
import shutil
from subprocess import DEVNULL
from tempfile import TemporaryDirectory
import unittest

import strace_helper


logging.basicConfig(level=logging.DEBUG)

# Prevent extra libs/files from being loaded/read when commands need to
# produced localized (error) messages.
os.environ['LANG'] = 'C'

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

LOCALE_ARCHIVE = [('read', ('/usr/lib/locale/locale-archive',))]

INIT_C = LOADER + LIBC
INIT_C_LOCALE = INIT_C + LOCALE_ARCHIVE

INIT_LS = LOADER + LIBCAP + LIBACL + LIBC + LIBATTR + LOCALE_ARCHIVE
INIT_MV = LOADER + LIBACL + LIBATTR + LIBC + LOCALE_ARCHIVE
INIT_SH = (
    LOADER + LIBREADLINE + LIBNCURSES + LIBDL + LIBC + [
        ('write', ('/dev/tty',)),
    ] + LOCALE_ARCHIVE + [
        ('read', ('/proc/meminfo',)),
        ('check', (os.getcwd(), True)),
        ('check', ('.', True)),
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
        expect_env = os.environ.copy()
        if env is not None:
            for k, v in env.items():
                if v is None:
                    del expect_env[k]
                else:
                    expect_env[k] = v

        # First event should always be exec
        a_pid, a_event, (a_executable, a_argv, a_env) = actual.pop(0)
        self.assertGreater(a_pid, 0)
        self.assertEqual(a_pid, pid)
        self.assertEqual(a_event, 'exec')
        self.assertEqual(a_executable, executable)
        self.assertListEqual(a_argv, argv)
        self.assertDictEqual(a_env, expect_env)

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
                ('write', (path.as_posix(),)), # open()
                ('write', (path.as_posix(),)), # utimensat()
            ], 0)
            self.assertTrue(path.exists())

    def test_touch_existing_file(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir, 'existing_file')
            with path.open('w') as f:
                pass
            self.assertTrue(path.exists())
            self.run_test(['touch', path.as_posix()], INIT_C_LOCALE + [
                ('write', (path.as_posix(),)), # open()
                ('write', (path.as_posix(),)), # utimensat()
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
                with Path(tmpdir, name).open('w') as f:
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
            with p1.open('w') as f:
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
            with p1.open('w') as f:
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
            actual = list(self.run_trace([script.as_posix()]))
            pid = actual[0][0]
            self.assertListEqual(actual, [
                (pid, 'check', (script.as_posix(), True)),  # execve() -> EACCES
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


if __name__ == '__main__':
    unittest.main()
