import logging
import os
from pathlib import Path
import shutil
import unittest

from process_trace import ProcessTrace
import strace_helper


logging.basicConfig(level=logging.DEBUG)


class TestProcessTrace(unittest.TestCase):

    maxDiff = 4096

    def run_trace(self, cmd_args, debug=False, **popen_args):
        strace_helper.logger.setLevel(
            logging.DEBUG if debug else logging.WARNING)
        p = ProcessTrace.from_events(
            strace_helper.run_trace(cmd_args, log_events=debug, **popen_args))
        return p

    def check_trace(self, expect, actual):
        if expect.pid is None:
            expect.pid = actual.pid
        self.assertEqual(expect.json(), actual.json())

    def run_test(self, expect, cmd_args, debug=False, **popen_args):
        actual = self.run_trace(cmd_args, debug, **popen_args)
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
