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

    def __init__(self, pid=None, ppid=None, cwd=None):
        self.pid = pid
        self.ppid = ppid
        self.cwd = cwd or Path.cwd()
        self.executable = None
        self.argv = None
        self.env = None
        self.paths_read = set()  # Paths read by this process
        self.paths_written = set()  # Paths written by this process
        self.paths_checked = set()  # Paths whose (non-)existence was checked
        self.exit_code = None

    def exec(self, executable, argv, env):
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
        self.exit_code = exit_code
