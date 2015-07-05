import json
from pathlib import Path, PurePath


class ProcessTrace:
    '''Summarize trace events from a process.'''

    @classmethod
    def from_events(cls, events, cwd=None):
        '''Build a tree of ProcessTrace objecs from the given trace events.

        Return the first/root ProcessTrace instance; the others can be found by
        traversing root.children.
        '''
        # Establish root process. Every other process hangs off this one.
        pid, event, args = next(events)
        root = ProcessTrace(pid=pid, cwd=cwd)
        getattr(root, event)(*args)  # handle first trace event

        running = {pid: root}  # pid -> ProcessTrace for running processes
        pending = {}  # pid -> [events...] for "not-yet-running" processes

        for pid, event, args in events:
            if pid not in running:
                # A child may start generating trace events before its parent's
                # 'fork' has fully completed.
                pending.setdefault(pid, []).append((event, args))
                continue
            assert pid in running
            p = running[pid]
            getattr(p, event)(*args)  # handle trace event

            if event == 'fork':
                cpid = args[0]
                c = ProcessTrace(pid=cpid, ppid=pid, cwd=p.cwd)
                assert cpid not in running
                running[cpid] = c
                p.children.append(c)

                # Finally, handle any pending events that the child may posted
                # in the meantime
                if cpid in pending:
                    for event, args in pending[cpid]:
                        getattr(c, event)(*args)  # handle trace event
                    del pending[cpid]
            if event == 'exit':
                del running[pid]

        assert not running  # all processes have exited
        assert not pending  # no pending events
        return root

    def __init__(self, pid=None, ppid=None, cwd=None, executable=None,
                 argv=None, env=None, paths_read=None, paths_written=None,
                 paths_checked=None, exit_code=None):
        self.pid = pid
        self.ppid = ppid
        self.cwd = Path.cwd() if cwd is None else Path(cwd)
        self.executable = None if executable is None else self.cwd / executable
        self.argv = argv
        self.env = env
        self.paths_read = set()  # Paths read by this process
        self.paths_written = set()  # Paths written by this process
        self.paths_checked = set()  # Paths whose (non-)existence was checked
        self.exit_code = exit_code
        self.children = []  # List of child processes forked from this one

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
        def default(o):
            if isinstance(o, ProcessTrace):
                d = o.__dict__.copy()
                for k in list(d.keys()):
                    if k.startswith('_'):
                        del d[k]
                return d
            elif isinstance(o, PurePath):
                return str(o)
            elif isinstance(o, set):
                return list(sorted(o))
            raise TypeError(o)

        return json.dumps(self, indent=4, sort_keys=True, default=default)

    def collapsed(self):
        '''Return a copy of self with all children's file activities collapsed.

        Create a copy of self with all its children's file reads/writes/checks
        collapsed into the copy, and with its .children emptied.
        '''
        ret = self.__class__(
            pid=self.pid,
            ppid=self.ppid,
            cwd=self.cwd,
            executable=self.executable,
            argv=self.argv,
            env=self.env,
            exit_code=self.exit_code)

        def copy_activities(p):
            ret.paths_read |= p.paths_read
            ret.paths_written |= p.paths_written
            ret.paths_checked |= p.paths_checked
            # Add child executable to read set, to not lose track of it
            ret.read(p.executable)
            for c in p.children:
                copy_activities(c)

        copy_activities(self)
        return ret

    # Trace event handlers

    def exec(self, executable, argv, env):
        assert self.executable is None
        assert self.argv is None
        assert self.env is None
        self.executable = self.cwd / executable
        self.argv = argv
        self.env = env

    def read(self, path):
        self.paths_read.add((str(path), self.cwd / path))

    def write(self, path):
        self.paths_written.add((str(path), self.cwd / path))

    def check(self, path, exists):
        self.paths_checked.add((str(path), self.cwd / path, exists))

    def exit(self, exit_code):
        assert self.exit_code is None
        self.exit_code = exit_code

    def fork(self, child_pid):
        pass  # forks are tracked by from_events()

    def chdir(self, path):
        self.cwd = Path(path)
