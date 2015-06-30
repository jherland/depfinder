import logging
import os
from pathlib import Path
import shutil
from subprocess import DEVNULL
from tempfile import TemporaryDirectory
import unittest

from process_trace import ProcessTrace
import strace_helper
from test_utils import adjust_env, prepare_trace_environment, do_sh_path_lookup


logging.basicConfig(level=logging.DEBUG)
prepare_trace_environment()


def _init_c(p):
    p.read('/etc/ld.so.cache')
    p.check('/etc/ld.so.preload', False)
    p.read('/usr/lib/libc.so.6')
    locale_vars = {'LANG', 'LC_ALL', 'LC_CTYPE', 'LC_MESSAGES', 'LC_NUMERIC'}
    if locale_vars & set(p.env.keys()):
        p.read('/usr/lib/locale/locale-archive')


def _init_sh(p):
    _init_c(p)
    p.read('/usr/lib/libdl.so.2')
    p.read('/usr/lib/libncursesw.so.5')
    p.read('/usr/lib/libreadline.so.6')
    p.write('/dev/tty')
    p.read('/proc/meminfo')
    if 'PWD' in p.env:
        p.check(p.env['PWD'], True)
        p.check('.', True)


def _emulate_sh_path_lookup(p, cmd):
    for path in do_sh_path_lookup(cmd, p.env['PATH']):
        p.check(path, path.exists())


def _launched_from_sh(p):
    '''Adjust expected process details for a process launched from sh.'''
    adjust_env(p.env, {
        '_': p.executable,
        'OLDPWD': None,  # remove
        'PWD': p.cwd.as_posix(),
        'PS1': None,  # remove
        'SHLVL': str(int(p.env.get('SHLVL', 0)) + 1),
    })


class TestProcessTrace(unittest.TestCase):

    maxDiff = 4096

    def run_trace(self, cmd_args, debug=False, cwd=None, **popen_args):
        strace_helper.logger.setLevel(
            logging.DEBUG if debug else logging.WARNING)
        p = ProcessTrace.from_events(cwd=cwd, events=strace_helper.run_trace(
            cmd_args, cwd=cwd, log_events=debug,
            stdout=DEVNULL, stderr=DEVNULL, **popen_args))
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
                    p1,
                ],
                write=[
                    p2,
                ],
                check=[
                    (p1, True),
                    (p2, False),
                ])
            _init_c(expect)

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
            _init_sh(expect)

            self.run_test(expect, argv, cwd=tmpdir)

    def test_shell_scipt_with_fork(self):
        with TemporaryDirectory() as tmpdir:
            script = Path(tmpdir, 'fork.sh')
            with script.open('w') as f:
                f.write('#!/bin/sh\n\ndmesg\n')
            script.chmod(0o755)

            argv = [script.as_posix()]
            expect_sh = self.expect_trace(argv, read=[script])
            _init_sh(expect_sh)
            _emulate_sh_path_lookup(expect_sh, 'dmesg')

            expect_dmesg = self.expect_trace(['dmesg'], read=['/dev/kmsg'])
            _init_c(expect_dmesg)
            _launched_from_sh(expect_dmesg)
            expect_sh.children.append(expect_dmesg)

            self.run_test(expect_sh, argv)


if __name__ == '__main__':
    unittest.main()
