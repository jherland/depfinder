import os
from pathlib import Path
import shutil
import unittest

from process_trace import ProcessTrace
from strace_helper import run_trace


class TestProcessTrace(unittest.TestCase):

    maxDiff = 4096

    def run_trace(self, cmd_args, **popen_args):
        p = ProcessTrace.from_events(run_trace(cmd_args, **popen_args))
        return p

    def check_trace(self, expect, actual):
        if expect.pid is None:
            expect.pid = actual.pid
        self.assertEqual(expect.json(), actual.json())

    def run_test(self, expect, cmd_args, **popen_args):
        actual = self.run_trace(cmd_args, **popen_args)
        self.check_trace(expect, actual)

    def test_simple_echo(self):
        argv = ['echo', 'Hello World']
        expect = ProcessTrace(
            cwd=Path.cwd(), executable=shutil.which('echo'),
            argv=argv, env=os.environ.copy(),
            paths_read=[
                "/etc/ld.so.cache",
                "/usr/lib/libc.so.6",
                "/usr/lib/locale/locale-archive",
            ],
            paths_written=[
            ],
            paths_checked=[
                ("/etc/ld.so.preload", False),
            ],
            exit_code=0)
        self.run_test(expect, argv)


if __name__ == '__main__':
    unittest.main()
