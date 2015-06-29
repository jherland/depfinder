from pathlib import Path


class ProcessTrace:
    '''Summarize trace events from a process.'''

    @classmethod
    def from_events(cls, events):
        p = None
        for pid, event, args in events:
            if p is None:
                p = cls(pid)
                assert event == 'exec'
            getattr(p, event)(*args)
        return p

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
