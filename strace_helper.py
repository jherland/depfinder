from contextlib import contextmanager
import logging
import os
import re
import subprocess
import sys
from tempfile import TemporaryDirectory


@contextmanager
def temp_fifo(mode=0o666, suffix='', prefix='tmp', dir=None):
    """Return path to temporary FIFO that will be deleted at end of context."""
    with TemporaryDirectory(suffix, prefix, dir) as tempdir:
        fifo_path = os.path.join(tempdir, 'temp_fifo')
        os.mkfifo(fifo_path, mode)
        assert os.path.exists(fifo_path)
        yield fifo_path


def start_trace(cmd_args, trace_output, **popen_args):
    assert len(cmd_args) > 0

    args = [
        'strace', '-f', '-q', '-v', '-s', '4096',
        '-e', 'trace=file', '-e', 'verbose=!stat,lstat',
        '-o', trace_output,
    ]
    logging.debug('Running', repr(args), 'followed by', repr(cmd_args))
    return subprocess.Popen(args + cmd_args, **popen_args)


class StraceParseError(NotImplementedError):
    pass


_Const = {
    'F_OK': 0x0001,
    'R_OK': 0x0002,
    'O_RDONLY': 0x0010,
    'AT_FDCWD': 0x0100,

    # don't care about these flags:
    'O_CLOEXEC': 0,
    'O_NONBLOCK': 0,
    'O_DIRECTORY': 0,
}


def _parse_args(args):
    # The following hack is the most compelling reason to rewrite this with
    # our own preloaded library mixin, instead of using strace
    return eval(args, {}, _Const) # Hmm, it sorta looks like valid python...


def _handle_exec(func, args, ret, rest):
    executable, argv, env_s = _parse_args(args)
    assert func == 'execve' and ret == 0 and not rest
    return 'exec', (executable, argv, dict(s.split('=', 1) for s in env_s))


def _handle_access(func, args, ret, rest):
    path, mode = _parse_args(args)
    assert mode in (_Const['F_OK'], _Const['R_OK'])
    assert ret == -1 and rest.startswith('ENOENT ')
    return 'check', (path, False)


def _handle_open(func, args, ret, rest):
    if func == 'openat':
        base, path, mode = _parse_args(args)
        assert base == _Const['AT_FDCWD']
    else:
        path, mode = _parse_args(args)
    if ret == -1:
        assert mode & _Const['O_RDONLY']
        assert rest.startswith('ENOENT ')
        return 'check', (path, False)
    elif mode & _Const['O_RDONLY']:
        assert ret > 0 and not rest
        return 'read', (path,)
    else:
        raise NotImplementedError


def _handle_stat(func, args, ret, rest):
    path, struct = _parse_args(args)
    if ret == 0:
        assert not rest
    else:
        assert ret == -1 and rest.startswith('ENOENT ')
    return 'check', (path, ret == 0)


def _handle_readlink(func, args, ret, rest):
    path, target, bufsize = _parse_args(args)
    if ret > 0:
        assert not rest
        return 'read', (path,)
    else:
        assert ret == -1
        if rest.startswith('ENOENT '):
            return 'check', (path, False)
        elif rest.startswith('EINVAL '):
            raise NotImplementedError
        else:
            raise NotImplementedError


_func_handlers = {
    'execve': _handle_exec,
    'access': _handle_access,
    'open': _handle_open,
    'openat': _handle_open,
    'stat': _handle_stat,
    'lstat': _handle_stat,
    'readlink': _handle_readlink,
}


def strace_output_events(f):
    """Parse strace output from f into (pid, event, (args...)) tuples.

    Possible events are (args in parentheses):
        - 'exec' (executable, argv_list, env_dict)
        - 'exit' (exit_code)
        - 'read' (path)
        - 'write' (path)
        - 'check' (path, exists)
    """

    syscall_pattern = re.compile(r'^(\d+) +(\w+)\((.*)\) += (-?\d+)(.*)$')
    exit_pattern = re.compile(r'^(\d+) +\+\+\+ exited with (\d+) \+\+\+$')

    for line in f:
        m = syscall_pattern.match(line)
        if m:
            try:
                pid, func, args, ret, rest = m.groups()
                event, details = _func_handlers[func](
                    func, args, int(ret), rest.strip())
                yield int(pid), event, details
            except:
                raise StraceParseError(line)
        else:
            m = exit_pattern.match(line)
            if m:
                pid, exit_code = m.groups()
                yield int(pid), 'exit', (int(exit_code),)
            else:
                raise StraceParseError(line)


def run_trace(cmd_args, **popen_args):
    """Execute the given command line and generate trace events."""
    with temp_fifo() as fifo:
        with start_trace(cmd_args, fifo, **popen_args) as trace:
            with open(fifo) as f:
                yield from strace_output_events(f)


if __name__ == '__main__':
    from pprint import pprint
    import sys

    for e in strace_output_events(sys.stdin):
        pprint(e, width=160)
