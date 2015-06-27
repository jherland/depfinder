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


def _parse_number(s):
    try:
        sub = s.index(',')
        s = s[sub:]
    except ValueError:
        sub, s = s, ''
    if sub.startswith('0x'):
        ret = int(sub[2:], 16)
    elif sub.startswith('0'):
        ret = int(sub[1:], 8)
    else:
        ret = int(sub, 10)
    return ret, s


def _parse_string(s):
    assert s.startswith('"')
    ret = []
    escape = False
    for i, c in enumerate(s[1:]):
        if escape:
            ret.append(c)
            escape = False
        elif c =='\\':
            escape = True
        elif c == '"':
            break
        else:
            ret.append(c)
    return ''.join(ret), s[i + 2:]


def _parse_array(s):
    assert s.startswith('[')
    ret = []
    s = s[1:]
    while s[0] != ']':
        item, s = _parse_string(s)
        ret.append(item)
        if s.startswith(', '):
            s = s[2:]
    return ret, s[1:]


AT_FDCWD = -100


def _parse_args(spec, args):
    """Parse the given args according to the given spec, yield parse items.

    Spec legend:
        - , - read a comma followed by a space, yield nothing
        - n - read an integer and yield it
        - f - read a file descriptor and yield it as an integer
        - s - read a "c-style string" and yield a string
        - | - read a |-separated list of tokens, yield a list of strings
        - a - read an ["array", "of", "strings"], yield a list of strings
    """
    ret = []
    for token in spec:
        if token == ',':
            assert args.startswith(', ')
            args = args[2:]
        elif token == 'n':
            n, args = _parse_number(args)
            yield n
        elif token == 'f':
            if args.startswith('AT_FDCWD'):
                yield AT_FDCWD, args[8:]
            else:
                n, args = _parse_number(args)
                yield n
        elif token == 's':
            s, args = _parse_string(args)
            yield s
        elif token == '|':
            try:
                sub = args.index(',')
                args = args[sub:]
            except ValueError:
                sub, args = args, ''
            yield list(sub.split('|'))
        elif token == 'a':
            a, args = _parse_array(args)
            yield a
    assert args == ''
    return ret


def _handle_exec(func, args, ret, rest):
    executable, argv, env_s = _parse_args('s,a,a', args)
    assert func == 'execve' and ret == 0 and not rest
    return 'exec', (executable, argv, dict(s.split('=', 1) for s in env_s))


def _handle_access(func, args, ret, rest):
    path, mode = _parse_args('s,|', args)
    assert mode in (['F_OK'], ['R_OK'])
    assert ret == -1 and rest.startswith('ENOENT ')
    return 'check', (path, False)


def _handle_open(func, args, ret, rest):
    if func == 'openat':
        base, path, mode = _parse_args('f,s,|', args)
        assert base == AT_FDCWD
    else:
        path, mode = _parse_args('s,|', args)
    if ret == -1:
        assert 'O_RDONLY' in mode
        assert rest.startswith('ENOENT ')
        return 'check', (path, False)
    elif 'O_RDONLY' in mode:
        assert ret > 0 and not rest
        return 'read', (path,)
    else:
        raise NotImplementedError


def _handle_stat(func, args, ret, rest):
    path, struct = _parse_args('s,n', args)
    if ret == 0:
        assert not rest
    else:
        assert ret == -1 and rest.startswith('ENOENT ')
    return 'check', (path, ret == 0)


def _handle_readlink(func, args, ret, rest):
    path, target, bufsize = _parse_args('s,s,n', args)
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
