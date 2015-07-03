from contextlib import contextmanager
import logging
import os
import re
import subprocess
from tempfile import TemporaryDirectory


logger = logging.getLogger(__name__)


@contextmanager
def temp_fifo(mode=0o666, suffix='', prefix='tmp', dir=None):
    '''Return path to temporary FIFO that will be deleted at end of context.'''
    with TemporaryDirectory(suffix, prefix, dir) as tempdir:
        fifo_path = os.path.join(tempdir, 'temp_fifo')
        os.mkfifo(fifo_path, mode)
        assert os.path.exists(fifo_path)
        yield fifo_path


def start_trace(cmd_args, trace_output, **popen_args):
    assert len(cmd_args) > 0

    args = [
        'strace', '-f', '-q', '-v', '-s', '4096', '-y',
        '-e', 'trace=file,process', '-e', 'verbose=!stat,lstat',
        '-o', trace_output,
    ]
    logger.debug('Running {!r} followed by {!r}'.format(args, cmd_args))
    return subprocess.Popen(args + cmd_args, **popen_args)


class StraceParseError(NotImplementedError):
    pass


class StraceOutputParser:
    '''Parse strace output into (pid, event, (args...)) tuples.

    Possible events are (args in parentheses):
        - 'exec' (executable, argv_list, env_dict)
        - 'exit' (exit_code)
        - 'read' (path)
        - 'write' (path)
        - 'check' (path, exists)
        - 'fork' (child_pid)
        - 'chdir' (path)
    '''

    def __init__(self):
        self.pending = {}  # pid -> unfinished syscall name

    # Syscall argument parsers: Parse the tokens that make up a syscall
    # argument list (as presented by strace)

    @staticmethod
    def _parse_number(s):
        try:
            sub = s[:s.index(',')]
            s = s[len(sub):]
        except ValueError:
            sub, s = s, ''
        if sub == 'NULL' or sub == '0':
            ret = 0
        elif sub.startswith('0x'):
            ret = int(sub[2:], 16)
        elif sub.startswith('0'):
            ret = int(sub[1:], 8)
        else:
            ret = int(sub, 10)
        return ret, s

    @staticmethod
    def _parse_string(s):
        if s.startswith('NULL'):
            return None, s[4:]
        if not s.startswith('"'):
            raise ValueError('Invalid string: {!r}'.format(s))
        ret = []
        escape = False
        for i, c in enumerate(s[1:]):
            if escape:
                ret.append(c)
                escape = False
            elif c == '\\':
                escape = True
            elif c == '"':
                break
            else:
                ret.append(c)
        return ''.join(ret), s[i + 2:]

    @staticmethod
    def _parse_bitwise_or(s):
        try:
            sub = s[:s.index(',')]
            s = s[len(sub):]
        except ValueError:
            sub, s = s, ''
        return sub.split('|'), s

    def _parse_array(self, s):
        assert s.startswith('[')
        ret = []
        s = s[1:]
        while s[0] != ']':
            item, s = self._parse_string(s)
            ret.append(item)
            if s.startswith(', '):
                s = s[2:]
        return ret, s[1:]

    def _parse_args(self, spec, args):
        '''Parse the given args according to the given spec, yield parse items.

        Spec legend:
            - , - read a comma followed by a space, yield nothing
            - n - read an integer and yield it
            - f - read a file descriptor and yield it as an integer
            - s - read a "c-style string" and yield a string
            - | - read a |-separated list of tokens, yield a list of strings
            - a - read an ["array", "of", "strings"], yield a list of strings
            - * - the rest of the args are optional. yield None unless present
        '''
        optional = False
        for token in spec:
            if token == '*':
                optional = True
            elif optional and not args:
                if token != ',':
                    yield None
            elif token == ',':
                assert args.startswith(', '), args
                args = args[2:]
            elif token == 'n':
                n, args = self._parse_number(args)
                yield n
            elif token == 'f':
                if args.startswith('AT_FDCWD'):
                    args = args[8:]
                    yield '.'
                else:
                    f, args = args.split('>', 1)
                    n, f = f.split('<', 1)
                    n, _ = self._parse_number(n)
                    yield f
            elif token == 's':
                s, args = self._parse_string(args)
                yield s
            elif token == '|':
                a, args = self._parse_bitwise_or(args)
                yield a
            elif token == 'a':
                a, args = self._parse_array(args)
                yield a
            else:
                assert False, 'Unknown spec token {}'.format(token)
        assert args == ''

    # Syscall handlers: Generate zero or more trace events from a syscall

    def _handle_syscall_access(self, pid, func, args, ret, rest):
        path, mode = self._parse_args('s,|', args)
        assert set(mode) - {'F_OK', 'R_OK', 'W_OK', 'X_OK'} == set()
        if ret == 0:
            yield pid, 'check', (path, True)
        elif ret == -1 and rest.startswith('ENOENT '):
            yield pid, 'check', (path, False)
        else:
            raise NotImplementedError(rest)

    def _handle_syscall_chdir(self, pid, func, args, ret, rest):
        path, = self._parse_args('s', args)
        assert ret == 0 and not rest
        yield pid, 'chdir', (path,)

    def _handle_syscall_clone(self, pid, func, args, ret, rest):
        _, _, flags = args.partition('flags=')  # not interested in other args?
        flags = set(self._parse_bitwise_or(flags)[0])
        assert flags == {
            'CLONE_CHILD_CLEARTID', 'CLONE_CHILD_SETTID', 'SIGCHLD'}
        assert ret > 0 and not rest
        yield pid, 'fork', (ret,)

    def _handle_syscall_execve(self, pid, func, args, ret, rest):
        executable, argv, env_s = self._parse_args('s,a,a', args)
        env = dict(s.split('=', 1) for s in env_s)
        assert func == 'execve'
        if ret == 0:
            assert not rest
            yield pid, 'exec', (executable, argv, env)
        else:
            assert ret == -1
            if rest.startswith('ENOENT '):
                yield pid, 'check', (executable, False)
            elif rest.startswith('EACCES '):
                yield pid, 'check', (executable, True)
            else:
                raise NotImplementedError

    def _handle_syscall_getxattr(self, pid, func, args, ret, rest):
        path, name, value, size = self._parse_args('s,s,n,n', args)
        assert ret == -1 and rest.startswith('ENODATA ')
        yield pid, 'check', (path, True)

    def _handle_syscall_open(self, pid, func, args, ret, rest):
        if func == 'openat':
            base, path, oflag, mode = self._parse_args('f,s,|*,n', args)
            assert base == '.', base
        else:
            path, oflag, mode = self._parse_args('s,|*,n', args)
        oflag = set(oflag)
        if ret == -1:
            assert 'O_RDONLY' in oflag
            assert rest.startswith('ENOENT ')
            yield pid, 'check', (path, False)
        elif 'O_RDONLY' in oflag:
            assert ret > 0 and not rest
            yield pid, 'read', (path,)
        elif {'O_WRONLY', 'O_RDWR'} & oflag:
            assert ret > 0 and not rest
            yield pid, 'write', (path,)
        else:
            raise NotImplementedError

    _handle_syscall_openat = _handle_syscall_open

    def _handle_syscall_readlink(self, pid, func, args, ret, rest):
        try:
            path, target, bufsize = self._parse_args('s,s,n', args)
            assert ret > 0 and not rest
            yield pid, 'read', (path,)
        except ValueError:
            path, unknown, bufsize = self._parse_args('s,n,n', args)
            assert ret == -1
            if rest.startswith('ENOENT '):
                yield pid, 'check', (path, False)
            elif rest.startswith('EINVAL '):
                yield pid, 'check', (path, True)
            else:
                raise NotImplementedError

    def _handle_syscall_rename(self, pid, func, args, ret, rest):
        path_from, path_to = self._parse_args('s,s', args)
        assert ret == 0 and not rest
        yield pid, 'write', (path_from,)
        yield pid, 'write', (path_to,)

    def _handle_syscall_stat(self, pid, func, args, ret, rest):
        path, struct = self._parse_args('s,n', args)
        if ret == 0:
            assert not rest
        else:
            assert ret == -1 and rest.startswith('ENOENT ')
        yield pid, 'check', (path, ret == 0)

    _handle_syscall_lstat = _handle_syscall_stat

    def _handle_syscall_unlink(self, pid, func, args, ret, rest):
        path, = self._parse_args('s', args)
        assert ret == 0 and not rest
        yield pid, 'write', (path,)

    def _handle_syscall_utimensat(self, pid, func, args, ret, rest):
        base, path, times, flag = self._parse_args('f,s,n,n', args)
        assert path is None and times == 0 and flag == 0
        yield pid, 'write', (base,)

    def _handle_syscall_vfork(self, pid, func, args, ret, rest):
        assert args == ''
        assert ret > 0 and not rest
        yield pid, 'fork', (ret,)

    def _ignore_syscall(self, pid, func, args, ret, rest):
        logger.debug('IGNORING: {} {}({}) = {} {}'.format(
            pid, func, args, ret, rest))
        return
        yield  # empty generator

    # The following syscalls are intentionally ignored:
    _handle_syscall_arch_prctl = _ignore_syscall
    _handle_syscall_exit_group = _ignore_syscall
    _handle_syscall_getcwd = _ignore_syscall
    _handle_syscall_wait4 = _ignore_syscall

    # Line parsers: Parse a line of strace output that matches the
    # corresponding regex in _LineParsers

    def _parse_syscall_full(self, pid, func, args, ret, rest):
        ret = None if ret == '?' else int(ret)
        handler = getattr(self, '_handle_syscall_' + func)
        yield from handler(int(pid), func, args, ret, rest.strip())

    def _parse_syscall_unfinished(self, pid, func, partial_args):
        pid = int(pid)
        assert pid not in self.pending
        self.pending[pid] = (func, partial_args)
        return
        yield  # empty generator

    def _parse_syscall_resumed(self, pid, func, rest):
        pid = int(pid)
        stored_func, partial_args = self.pending[pid]
        assert func == stored_func
        del self.pending[pid]

        # Reconstruct full syscall and parse it
        line = '{} {}({}{}'.format(pid, func, partial_args, rest)
        logger.debug('RESUMED {!r}'.format(line))
        syscall_parser, syscall_pattern = self._LineParsers[0]
        m = syscall_pattern.match(line)
        assert m
        yield from syscall_parser(self, *m.groups())

    def _parse_signal(self, pid, signal, args):
        assert signal == 'SIGCHLD'
        return
        yield  # empty generator

    def _parse_exit(self, pid, exit_code):
        yield int(pid), 'exit', (int(exit_code),)

    def _parse_error(self, line):
        logger.error('Unrecognized line: {!r}'.format(line))
        return
        yield  # empty generator

    _LineParsers = [
        (_parse_syscall_full, re.compile(
            r'^(\d+) +(\w+)\((.*)\) += (-?\d+|\?)(?:<.*?>)?(.*)$')),
        (_parse_syscall_unfinished, re.compile(
            r'^(\d+) +(\w+)\((.*) <unfinished \.\.\.>$')),
        (_parse_syscall_resumed, re.compile(
            r'^(\d+) +<\.\.\. (\w+) resumed> (.*)$')),
        (_parse_signal, re.compile(r'^(\d+) +--- (\w+) {(.*)} ---$')),
        (_parse_exit, re.compile(r'^(\d+) +\+\+\+ exited with (\d+) \+\+\+$')),
        (_parse_error, re.compile(r'(.*)')),
    ]

    def __call__(self, f):
        '''Generate trace events as documented in the class header.'''
        for line in f:
            logger.debug(line.rstrip())
            for parser, pattern in self._LineParsers:
                m = pattern.match(line)
                if m:
                    try:
                        yield from parser(self, *m.groups())
                    except:
                        raise StraceParseError(line)
                    break


def run_trace(cmd_args, log_events=False, **popen_args):
    '''Execute the given command line and generate trace events.'''
    with temp_fifo() as fifo:
        with start_trace(cmd_args, fifo, **popen_args):
            with open(fifo) as f:
                if log_events:
                    for event_tuple in StraceOutputParser()(f):
                        logger.debug('TRACE EVENT {!r}'.format(event_tuple))
                        yield event_tuple
                else:
                    yield from StraceOutputParser()(f)


if __name__ == '__main__':
    from pprint import pprint
    import sys

    for e in StraceOutputParser()(sys.stdin):
        pprint(e, width=160)
