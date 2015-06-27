#!/usr/bin/env python3

import logging
from pprint import pprint
import re
import sys

CONSTS = {
    'F_OK': 0x0001,
    'R_OK': 0x0002,
    'O_RDONLY': 0x0010,
    'AT_FDCWD': 0x0100,

    # don't care about these flags:
    'O_CLOEXEC': 0,
    'O_NONBLOCK': 0,
    'O_DIRECTORY': 0,
}

def parse_args(args):
    # The following hack is the most compelling reason to rewrite this with
    # our own preloaded library mixin, instead of using strace
    return eval(args, {}, CONSTS)


def parse_strace_output(f):
    syscall_pattern = re.compile(r'^(\d+) +(\w+)\((.*)\) += (-?\d+)(.*)$')
    exit_pattern = re.compile(r'^(\d+) +\+\+\+ exited with (\d+) \+\+\+$')
    for line in f:
        m = syscall_pattern.match(line)
        if m:
            try:
                pid, func, args, ret, rest = m.groups()
                yield int(pid), func, parse_args(args), int(ret), rest.strip()
            except:
                logging.error('Failed to parse line: ' + line)
                raise
        else:
            m = exit_pattern.match(line)
            if m:
                pid, exit_code = m.groups()
                yield int(pid), 'exit', int(exit_code), int(exit_code), None
            else:
                logging.warning('Skipping unknown line: ' + line)


def events(parsed_strace_output):
    for pid, func, args, ret, rest in parsed_strace_output:
        if func == 'execve':
            prog, argv, env = args
            yield pid, 'start', prog, argv, env, ret
        elif func == 'exit':
             yield pid, 'exit', ret
        elif func == 'access':
            path, mode = args
            assert mode in (CONSTS['F_OK'], CONSTS['R_OK'])
            assert ret == -1 and rest.startswith('ENOENT ')
            yield pid, 'path', path, 'missing', func
        elif func in ('open', 'openat'):
            if func == 'openat':
                base, path, mode = args
                assert base == CONSTS['AT_FDCWD']
            else:
                path, mode = args
            verb = '???'
            if mode & CONSTS['O_RDONLY']:
                verb = 'read'
            if ret == -1:
                assert rest.startswith('ENOENT ')
                verb = 'missing'
            else:
                assert ret > 0 and not rest
            yield pid, 'path', path, verb, func
        elif func in ('stat', 'lstat'):
            path, struct = args
            if ret == 0:
                assert not rest
                verb = 'read'
            else:
                assert ret == -1 and rest.startswith('ENOENT ')
                verb = 'missing'
            yield pid, 'path', path, verb, func
        elif func == 'readlink':
            path, target, bufsize = args
            if ret > 0:
                assert not rest
                verb = 'read'
            else:
                assert ret == -1
                if rest.startswith('ENOENT '):
                    verb = 'missing'
                elif rest.startswith('EINVAL '):
                    verb = 'read?'
                else:
                    logging.error('Failed to parse readline() retval: ' + rest)
            yield pid, 'path', path, verb, func
        else:
            logging.error('Cannot create event for {!r}'.format(
                (pid, func, args, ret, rest)))


def main():
    for e in events(parse_strace_output(sys.stdin)):
        pprint(e, width=160)

if __name__ == '__main__':
    main()
