import json
from pathlib import Path, PosixPath


class ProcessTrace:
    '''Summarize trace events from a process.'''

    @classmethod
    def from_events(cls, events):
        pids = {}  # map pid -> ProcessTrace instance
        for pid, event, args in events:
            p = pids.setdefault(pid, cls(pid))
            getattr(p, event)(*args)
        return pids[min(pids.keys())]

    def __init__(self, pid=None, ppid=None, cwd=None, executable=None,
                 argv=None, env=None, paths_read=None, paths_written=None,
                 paths_checked=None, exit_code=None):
        self.pid = pid
        self.ppid = ppid
        self.cwd = cwd or Path.cwd()
        self.executable = None if executable is None else self.cwd / executable
        self.argv = argv
        self.env = env
        self.paths_read = set()  # Paths read by this process
        self.paths_written = set()  # Paths written by this process
        self.paths_checked = set()  # Paths whose (non-)existence was checked
        self.exit_code = exit_code

        if paths_read is not None:
            for path in paths_read:
                self.read(path)

        if paths_written is not None:
            for path in paths_written:
                self.write(path)

        if paths_checked is not None:
            for path, exists in paths_checked:
                self.check(path, exists)

    def json(self):
        def handle_extended_types(o):
            if isinstance(o, PosixPath):
                return o.as_posix()
            elif isinstance(o, set):
                return list(sorted(o))
            raise TypeError(o)

        return json.dumps(
            self.__dict__,
            sort_keys=True,
            indent=4,
            default=handle_extended_types)

    # Trace event handlers

    def exec(self, executable, argv, env):
        assert self.executable is None
        assert self.argv is None
        assert self.env is None
        self.executable = self.cwd / executable
        self.argv = argv
        self.env = env

    def read(self, path):
        self.paths_read.add((path, self.cwd / path))

    def write(self, path):
        self.paths_written.add((path, self.cwd / path))

    def check(self, path, exists):
        self.paths_checked.add((path, self.cwd / path, exists))

    def exit(self, exit_code):
        assert self.exit_code is None
        self.exit_code = exit_code

    def forked(self, child_pid):
        raise NotImplementedError

    def chdir(self, path):
        raise NotImplementedError
