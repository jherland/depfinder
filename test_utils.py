import os
from pathlib import Path


def adjust_env(env, adjustments=None, keep=None):
    '''Perform adjustments on an (environment) dictionary.

    The 'env' dictionary is mutated as follows:
     - 'keep', if given, is a collection of 'env' keys that will be kept. All
       other keys in 'env' are removed. Keys in 'keep' that are not in 'env'
       are not added (unless they also appear in 'adjustments'). If 'keep' is
       None (or not given), nothing is removed from 'env' (at this point).

     - for 'adjustments' keys whose value is not None, store that key/value
       pair into 'env' (replacing any previous value that may have been there).

     - for 'adjustments' keys whose value is None, remove that key from 'env'.

    >>> env = { 'foo': 1, 'bar': 2, 'baz': 3, 'xyzzy': 4 }
    >>> adjustments = { 'bar': 0, 'baz': None }
    >>> keep = {'foo', 'bar', 'baz'}
    >>> adjust_env(env, adjustments, keep)
    >>> env == { 'foo': 1, 'bar': 0 }
    True
    '''
    if keep is not None:
        # Remove anything not in keep
        for k in list(env.keys()):
            if k not in keep:
                del env[k]

    if adjustments is not None:
        # Apply adjustments
        for k, v in adjustments.items():
            if v is None:
                if k in env:
                    del env[k]
            else:
                env[k] = v


def prepare_trace_environment():
    '''Prepare this process' environment for running a trace.

    Clean up and minimize the environment to ensure the commands executed by
    the trace behave as deterministically as possible.
    '''
    adjust_env(os.environ, keep={'PATH', 'PWD', 'SHELL'})


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
