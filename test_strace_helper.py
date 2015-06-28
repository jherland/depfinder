import os
import shutil
from subprocess import DEVNULL
import sys
from tempfile import TemporaryDirectory
import unittest

from strace_helper import run_trace


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
LOCALE_ARCHIVE = [('read', ('/usr/lib/locale/locale-archive',))]

INIT_C = LOADER + LIBC
INIT_C_LOCALE = INIT_C + LOCALE_ARCHIVE

INIT_LS = LOADER + LIBCAP + LIBACL + LIBC + LIBATTR + LOCALE_ARCHIVE
INIT_MV = LOADER + LIBACL + LIBATTR + LIBC + LOCALE_ARCHIVE


class Test_run_trace(unittest.TestCase):

    maxDiff = 4096

    def run_test(self, argv, expect, exit_code=0):
        executable = shutil.which(argv[0])

        actual = list(run_trace(argv, stdout=DEVNULL, stderr=DEVNULL))

        # First event should always be exec
        pid, event, (actual_executable, actual_argv, env) = actual.pop(0)
        self.assertGreater(pid, 0)
        self.assertEqual(event, 'exec')
        self.assertEqual(actual_executable, executable)
        self.assertListEqual(actual_argv, argv)
        self.assertDictEqual(env, dict(os.environ))

        # Last event should always be exit
        actual_pid, event, actual_exit_code = actual.pop()
        self.assertEqual(actual_pid, pid)
        self.assertEqual(event, 'exit')
        self.assertEqual(actual_exit_code, (exit_code,))

        expect = [(pid, event, args) for (event, args) in expect]
        self.assertListEqual(expect, actual)

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
            path = os.path.join(tmpdir, 'new_file')
            self.assertFalse(os.path.exists(path))
            self.run_test(['touch', path], INIT_C_LOCALE + [
                ('write', (path,)), # open()
                ('write', (path,)), # utimensat()
            ], 0)
            self.assertTrue(os.path.exists(path))

    def test_touch_existing_file(self):
        with TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, 'existing_file')
            with open(path, 'w') as f:
                pass
            self.assertTrue(os.path.exists(path))
            self.run_test(['touch', path], INIT_C_LOCALE + [
                ('write', (path,)), # open()
                ('write', (path,)), # utimensat()
            ], 0)
            self.assertTrue(os.path.exists(path))

    def test_empty_ls(self):
        with TemporaryDirectory() as tmpdir:
            self.run_test(['ls', tmpdir], INIT_LS + [
                ('check', (tmpdir, True)),
                ('read', (tmpdir,)),
            ], 0)

    def test_nonempty_long_ls(self):
        with TemporaryDirectory() as tmpdir:
            for name in ['foo', 'bar', 'baz']:
                with open(os.path.join(tmpdir, name), 'w') as f:
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
            p1, p2 = os.path.join(tmpdir, 'foo'), os.path.join(tmpdir, 'bar')
            with open(p1, 'w') as f:
                pass
            self.run_test(['mv', p1, p2], INIT_MV + [
                ('check', (tmpdir + '/bar', False)),
                ('check', (tmpdir + '/foo', True)),
                ('check', (tmpdir + '/bar', False)),
                ('write', (tmpdir + '/foo',)),
                ('write', (tmpdir + '/bar',)),
            ], 0)
            self.assertFalse(os.path.exists(p1))
            self.assertTrue(os.path.exists(p2))

    def test_cp_one_file(self):
        with TemporaryDirectory() as tmpdir:
            p1, p2 = os.path.join(tmpdir, 'foo'), os.path.join(tmpdir, 'bar')
            with open(p1, 'w') as f:
                pass
            self.run_test(['cp', p1, p2], INIT_MV + [
                ('check', (tmpdir + '/bar', False)),
                ('check', (tmpdir + '/foo', True)),
                ('check', (tmpdir + '/bar', False)),
                ('read', (tmpdir + '/foo',)),
                ('write', (tmpdir + '/bar',)),
            ], 0)
            self.assertTrue(os.path.exists(p1))
            self.assertTrue(os.path.exists(p2))


if __name__ == '__main__':
    unittest.main()
