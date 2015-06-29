import logging
import os
from pathlib import Path
import shutil
from subprocess import DEVNULL
from tempfile import TemporaryDirectory
import unittest

from process_trace import ProcessTrace
import strace_helper


logging.basicConfig(level=logging.DEBUG)


def _init_c(p):
    p.read('/etc/ld.so.cache')
    p.check('/etc/ld.so.preload', False)
    p.read('/usr/lib/libc.so.6')
    p.read('/usr/lib/locale/locale-archive')




class TestProcessTrace(unittest.TestCase):

    maxDiff = 4096

    def run_trace(self, cmd_args, debug=False, **popen_args):
        strace_helper.logger.setLevel(
            logging.DEBUG if debug else logging.WARNING)
        p = ProcessTrace.from_events(strace_helper.run_trace(
            cmd_args, log_events=debug,
            stdout=DEVNULL, stderr=DEVNULL, **popen_args))
        return p

    def check_trace(self, expect, actual):
        if expect.pid is None:
            expect.pid = actual.pid
        self.assertEqual(expect.json(), actual.json())

    def run_test(self, expect, cmd_args, debug=False, **popen_args):
        actual = self.run_trace(cmd_args, debug, **popen_args)
        self.check_trace(expect, actual)

    def expect_trace(self, argv, cwd=None, adjust_env=None, read=None,
                     write=None, check=None, exit_code=0):
        '''Helper method for setting up an expected ProcessTrace object.'''
        cwd = cwd if cwd else Path.cwd()
        env = os.environ.copy()
        if adjust_env is not None:
            for k, v in adjust_env.items():
                if v is None:
                    if k in env:
                        del env[k]
                else:
                    env[k] = v

        p = ProcessTrace(
            cwd=cwd, executable=shutil.which(argv[0]), argv=argv, env=env,
            paths_read=read, paths_written=write, paths_checked=check,
            exit_code=exit_code)
        return p

    def test_simple_echo(self):
        argv = ['echo', 'Hello World']
        expect = self.expect_trace(argv)
        _init_c(expect)
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
                    "/usr/lib/libacl.so.1",
                    "/usr/lib/libattr.so.1",
                    p1.as_posix(),
                ],
                write=[
                    p2.as_posix(),
                ],
                check=[
                    (p1.as_posix(), True),
                    (p2.as_posix(), False),
                ])
            _init_c(expect)
            self.run_test(expect, argv)
            self.assertTrue(p1.exists())
            self.assertTrue(p2.exists())


if __name__ == '__main__':
    unittest.main()
