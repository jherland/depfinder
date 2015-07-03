import os
from pathlib import Path


def modified_env(env, mods=None, keep=None):
    '''Return a copy of the given environment (dictionary) with modifications.

    - If 'keep' is given, then only the items in 'env' whose key is also in
      'keep' are copied. Otherwise all items in 'env' are copied.

    - All items in 'mods' whose value is not None are copied, overwriting any
      existing overlapping items that were copied from 'env'.

    - All items in 'mode' whose value is None are deleted from the resulting
      dictionary.

    >>> env = { 'foo': 1, 'bar': 2, 'baz': 3, 'xyzzy': 4 }
    >>> adjustments = { 'bar': 0, 'baz': None }
    >>> keep = {'foo', 'bar', 'baz'}
    >>> modified_env(env, adjustments, keep) == { 'foo': 1, 'bar': 0 }
    True
    '''
    if keep is None:
        keep = set(env.keys())
    if mods is None:
        changes, drop = {}, set()
    else:
        changes = dict((k, v) for k, v in mods.items() if v is not None)
        drop = set(k for k, v in mods.items() if v is None)

    ret = dict((k, v) for k, v in env.items() if k in keep and k not in drop)
    ret.update(changes)
    return ret


def prepare_trace_environment():
    '''Prepare this process' environment for running a trace.

    Clean up and minimize the environment to ensure the commands executed by
    the trace behave as deterministically as possible.
    '''
    new_env = modified_env(os.environ, keep={'PATH', 'PWD', 'SHELL'})
    os.environ.clear()
    os.environ.update(new_env)


def do_sh_path_lookup(cmd, env_path=None):
    '''Generate the paths queried when sh looks for 'cmd' in $PATH.

    >>> it = do_sh_path_lookup('blarg', '/bin:/usr/bin:/usr/local/bin')
    >>> next(it) == Path('/bin/blarg')
    True
    >>> next(it) == Path('/usr/bin/blarg')
    True
    >>> next(it) == Path('/usr/local/bin/blarg')
    True
    '''
    if env_path is None:
        env_path = os.environ.get('PATH', '')
    for path in env_path.split(':'):
        candidate = Path(path, cmd)
        yield candidate
        if candidate.exists():
            break


if __name__ == "__main__":
    import doctest
    doctest.testmod()
