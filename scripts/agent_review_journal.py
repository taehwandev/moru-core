"""Durable review operation record; stdlib only, no provider or workflow imports.

Owner: atomic local record and process-scoped exclusion for one review output.
Caller: agent_review_acp CLI. Verification: test_agent_review_journal.py.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time


class ReviewJournal:
    def __init__(self, output, project, prompt, executable):
        self.path = Path(output)
        runtime = Path(executable).resolve(strict=True)
        digest = hashlib.sha256()
        with runtime.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        self.binding = {'project': str(Path(project).resolve()),
                        'request_digest': hashlib.sha256(prompt.encode()).hexdigest(),
                        'runtime_path': str(runtime), 'runtime_digest': digest.hexdigest()}
        self.state = {}

    def __enter__(self):
        self.lock = self.path.with_suffix(self.path.suffix + '.lock').open('a')
        try:
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError('review_already_running') from error
            if self.path.exists():
                self.state = json.loads(self.path.read_text())
                if not isinstance(self.state, dict):
                    raise ValueError('invalid_review_record')
                if any(self.state.get(k) != self.binding[k] for k in ('runtime_path', 'runtime_digest')):
                    raise ValueError('review_runtime_changed')
                if any(self.state.get(k) != v for k, v in self.binding.items()):
                    raise ValueError('review_inputs_changed')
            else:
                self.update({'phase': 'initializing', 'status': 'running',
                             '_event': 'review.record_initialized'})
            return self
        except BaseException:
            self.lock.close()
            raise

    def update(self, state):
        state = dict(state)
        event_type = state.pop('_event', None)
        if event_type:
            events = self.state.setdefault('events', [])
            if not isinstance(events, list) or len(events) >= 2048:
                raise ValueError('review_trace_full_or_invalid')
            event = {'event_type': event_type}
            if event_type == 'review.finished':
                event['status'] = state['status']
            events.append(event)
        self.state.update(state)
        self.state.update(self.binding, updated_at=time.time())
        fd, name = tempfile.mkstemp(prefix=self.path.name + '.', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(self.state, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def __exit__(self, *exc):
        self.lock.close()  # Kernel releases flock even after SIGKILL; no stale-lock deletion.
