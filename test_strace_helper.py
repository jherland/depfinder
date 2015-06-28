import os
import shutil
from subprocess import DEVNULL
import sys
from tempfile import TemporaryDirectory
import unittest

from strace_helper import run_trace


# The following are common trace events seen at the start of many processes.
LOADER = [
    ('check', ('/etc/ld.so.preload', False)),
    ('read', ('/etc/ld.so.cache',)),
]

LIBC = [
    ('read', ('/usr/lib/libc.so.6',)),
]

INIT_C = LOADER + LIBC

INIT_FS = LOADER + [
    ('read', ('/usr/lib/libcap.so.2',)),
    ('read', ('/usr/lib/libacl.so.1',)),
] + LIBC + [
    ('read', ('/usr/lib/libattr.so.1',)),
]

LOCALE_AWARE = [
    ('read', ('/usr/lib/locale/locale-archive',)),
]

INIT_C_LOCALE = INIT_C + LOCALE_AWARE

INIT_FS_LOCALE = INIT_FS + LOCALE_AWARE

# Setting the following prevents a lot of extra crap being loaded when commands
# need to produced localized (error) messages.
os.environ['LANG'] = 'C'


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
            self.run_test(['ls', tmpdir], INIT_FS_LOCALE + [
                ('check', (tmpdir, True)),
                ('read', (tmpdir,)),
            ], 0)


if __name__ == '__main__':
    unittest.main()
