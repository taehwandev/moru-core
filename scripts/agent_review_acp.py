#!/usr/bin/env python3
"""Read-only ACP review; processing activity is distinct from a final answer.

Owner: one bounded review turn over an existing local ACP runtime.
Allowed imports: stdlib. Forbidden: workflow state, provider SDKs, credentials.
Caller: orchestration CLI below. Tests: test_agent_review_acp.py (real child).
Cleanup failures retain response/session evidence as needs_inspection. The CLI
reuses that record without launching again until the owned process is inspected.
An empty public-input provider cwd is not a writable Git task. The lead retains
the source acceptance boundary and owns the local review journal.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import threading
import time


class _TransportError(Exception):
    pass


def _update(client, message):
    params = message.get('params', {})
    if not isinstance(params, dict) or params.get('sessionId') != client.session:
        return False
    update = params.get('update', {})
    if not isinstance(update, dict):
        return False
    content = update.get('content', {})
    kind = update.get('sessionUpdate')
    if kind not in {'agent_message_chunk', 'agent_thought_chunk'}:
        return False
    if not isinstance(content, dict) or content.get('type') != 'text':
        return False
    text = content.get('text')
    if not isinstance(text, str) or not text:
        return False
    client.activity += 1
    if kind == 'agent_message_chunk':
        if len(client.response) + len(text) > 65536:
            raise ValueError('review_response_too_large')
        client.response += text
    return True


class _Client:
    def __init__(self, command, cwd):
        self.proc = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     text=True, start_new_session=True)
        self.messages = queue.Queue(maxsize=64)
        self.closed = threading.Event()
        self.session = ''
        self.prompt_sent = False
        self.response = ''
        self.activity = 0
        self.denied = 0
        self.error_code = None
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            while not self.closed.is_set():
                line = self.proc.stdout.readline(1024 * 1024 + 1)
                if not line:
                    break
                if len(line) > 1024 * 1024:
                    break
                try:
                    message = json.loads(line)
                except ValueError:
                    break
                if not isinstance(message, dict):
                    break
                while not self.closed.is_set():
                    try:
                        self.messages.put(message, timeout=.1)
                        break
                    except queue.Full:
                        continue
        finally:
            self.closed.set()

    def send(self, method, params, request_id=None):
        message = {'jsonrpc': '2.0', 'method': method, 'params': params}
        if request_id is not None:
            message['id'] = request_id
        self._write(message)

    def _write(self, message):
        try:
            self.proc.stdin.write(json.dumps(message) + '\n')
            self.proc.stdin.flush()
        except (OSError, ValueError) as error:
            raise _TransportError() from error

    def wait(self, request_id, idle_timeout, max_seconds):
        start = last_progress = time.monotonic()
        while True:
            now = time.monotonic()
            if now - start >= max_seconds:
                raise TimeoutError('total_timeout')
            if now - last_progress >= idle_timeout:
                raise TimeoutError('idle_timeout')
            try:
                message = self.messages.get(timeout=min(.05, idle_timeout, max_seconds))
            except queue.Empty:
                if self.closed.is_set():
                    raise _TransportError()
                continue
            if message.get('method') == 'session/update':
                if _update(self, message):
                    last_progress = time.monotonic()
            elif message.get('method') and 'id' in message:
                if message['method'] == 'session/request_permission':
                    self.denied += 1
                    self._write({'jsonrpc': '2.0', 'id': message['id'],
                                 'result': {'outcome': {'outcome': 'cancelled'}}})
                else:
                    self._write({'jsonrpc': '2.0', 'id': message['id'],
                                 'error': {'code': -32601, 'message': 'Review tools disabled'}})
            elif message.get('id') == request_id:
                if not isinstance(message.get('result'), dict):
                    error = message.get('error', {})
                    if isinstance(error, dict) and type(error.get('code')) is int:
                        self.error_code = error['code']
                    raise ValueError('protocol_error')
                return message['result']

    def cancel(self, seconds):
        try:
            self.send('session/cancel', {'sessionId': self.session})
            return self.wait(4, seconds, seconds)
        except (_TransportError, TimeoutError, ValueError):
            return {}

    def close(self):
        self.closed.set()
        try:
            self.proc.stdin.close()
        except OSError:
            pass  # A dead transport is already represented in the result.
        error = ''
        for action in (None, signal.SIGTERM, signal.SIGKILL):
            try:
                if action is not None:
                    _signal_owned(self.proc.pid, action)
                self.proc.wait(timeout=1)
                error = ''
                break
            except subprocess.TimeoutExpired:
                error = 'exit_timeout'
            except PermissionError:
                error = 'permission_denied'
                break
        self.reader.join(timeout=1)
        if not self.reader.is_alive():
            self.proc.stdout.close()
        elif not error:
            error = 'reader_timeout'
        return error


def _signal_owned(pid, sig):
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        pass  # The owned child exited between wait and signal.


def _setup(client, cwd, checkpoint, resume_session):
    client.send('initialize', {'protocolVersion': 1, 'clientCapabilities': {}}, 1)
    initial = client.wait(1, 30, 30)
    if initial.get('protocolVersion') != 1:
        raise ValueError('unsupported_protocol')
    if resume_session:
        client.session = resume_session
        if initial.get('agentCapabilities', {}).get('loadSession') is not True:
            raise ValueError('session_observation_unavailable')
        client.send('session/load', {'sessionId': resume_session, 'cwd': str(cwd), 'mcpServers': []}, 2)
        client.wait(2, 30, 30)
        return
    client.send('session/new', {'cwd': str(cwd), 'mcpServers': []}, 2)
    result = client.wait(2, 30, 30)
    client.session = result.get('sessionId')
    if not isinstance(client.session, str) or not client.session:
        raise ValueError('missing_session')
    if checkpoint:
        checkpoint({'session_id': client.session, 'phase': 'prepared', 'status': 'running'})
    modes = result.get('modes', {})
    available = modes.get('availableModes') if isinstance(modes, dict) else None
    if not isinstance(available, list) or not any(
        isinstance(m, dict) and m.get('id') == 'plan'
        for m in available
    ):
        raise ValueError('read_only_mode_unavailable')
    client.send('session/set_mode', {'sessionId': client.session, 'modeId': 'plan'}, 3)
    client.wait(3, 30, 30)


def run_review(command, cwd, prompt, *, idle_timeout=120, max_seconds=900, cancel_timeout=15,
               checkpoint=None, resume_session=''):
    """Retry startup once; never replay an accepted or ambiguously submitted turn."""
    for value in (idle_timeout, max_seconds, cancel_timeout):
        if not math.isfinite(value) or value <= 0:
            raise ValueError('time limits must be finite and positive')
    cwd = Path(cwd).resolve(strict=True)
    result = {'status': 'blocked', 'failure_code': '', 'response': '', 'session_id': '',
              'activity_events': 0, 'permissions_denied': 0, 'cancellation_confirmed': False,
              'next_action': 'correct_review_invocation', 'launch_attempts': 0}
    for attempt in range(2):
        client = None
        stopped = {}
        retry_startup = False
        result['launch_attempts'] = attempt + 1
        try:
            client = _Client(command, cwd)
            _setup(client, cwd, checkpoint, resume_session)
            if resume_session:
                if checkpoint:
                    checkpoint({'_event': 'review.session_observed'})
                result.update(status='needs_inspection', next_action='inspect_existing_session')
                return result  # History replay is observation, not a new end_turn receipt.
            if checkpoint:
                checkpoint({'session_id': client.session, 'phase': 'submitted', 'status': 'running',
                            '_event': 'review.prompt_submitted'})
            client.prompt_sent = True  # Set before write: partial delivery is ambiguous.
            client.send('session/prompt', {'sessionId': client.session,
                        'prompt': [{'type': 'text', 'text': prompt}]}, 4)
            stopped = client.wait(4, idle_timeout, max_seconds)
        except _TransportError:
            result['failure_code'] = 'transport_failure'
            if client is not None and not client.prompt_sent and not resume_session and attempt == 0:
                retry_startup = True
        except (TimeoutError, ValueError) as error:
            result['failure_code'] = str(error)
            if client is not None and client.prompt_sent:
                if checkpoint:
                    checkpoint({'_event': 'review.cancel_requested'})
                stopped = client.cancel(cancel_timeout)
        except KeyboardInterrupt:
            result['failure_code'] = 'interrupted'
            if client is not None and client.prompt_sent:
                if checkpoint:
                    checkpoint({'_event': 'review.cancel_requested'})
                stopped = client.cancel(cancel_timeout)
        except OSError:
            result['failure_code'] = 'runtime_unavailable'
        finally:
            if client is not None:
                result.update(session_id=client.session, response=client.response,
                              activity_events=client.activity, permissions_denied=client.denied,
                              protocol_error_code=client.error_code)
                try:
                    cleanup_error = client.close()
                except OSError as error:
                    cleanup_error = 'permission_denied' if isinstance(error, PermissionError) else 'io_error'
                if cleanup_error:
                    result.update(status='needs_inspection', next_action='inspect_owned_process',
                                  cleanup_error=cleanup_error, cleanup_process_id=client.proc.pid,
                                  end_turn_observed=stopped.get('stopReason') == 'end_turn')
                    result['failure_code'] = result['failure_code'] or 'cleanup_' + cleanup_error
        if result.get('cleanup_error'):
            return result  # Never retry while the previous owned process is unconfirmed.
        if retry_startup:
            if checkpoint:
                checkpoint({'_event': 'review.startup_retry'})
            continue
        reason = stopped.get('stopReason')
        result['cancellation_confirmed'] = reason == 'cancelled'
        if checkpoint:
            if reason == 'cancelled':
                checkpoint({'_event': 'review.cancel_confirmed'})
            elif client is not None and client.prompt_sent and reason != 'end_turn':
                checkpoint({'_event': 'review.submission_ambiguous'})
            elif reason == 'end_turn' and not result['response'].strip():
                checkpoint({'_event': 'review.empty_result'})
        if reason == 'end_turn' and result['response'].strip() and not result['permissions_denied']:
            result.update(status='ok', failure_code='', next_action='inspect_review_findings')
        elif result['permissions_denied']:
            result.update(status='blocked', failure_code='permission_denied',
                          next_action='review_supplied_source_without_tools')
        elif reason == 'end_turn':
            result.update(status='needs_inspection', failure_code='missing_final_response',
                          next_action='inspect_completed_session')
        elif client is not None and client.prompt_sent and reason != 'cancelled':
            result.update(status='needs_inspection', next_action='observe_existing_session')
        elif reason == 'cancelled':
            result.update(next_action='narrow_review_or_use_available_evidence')
        return result


def _main():
    from agent_review_journal import ReviewJournal
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--prompt-file', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--executable', default=shutil.which('agy-real'))
    parser.add_argument('--idle-timeout', type=float, default=120)
    parser.add_argument('--max-seconds', type=float, default=900)
    args = parser.parse_args()
    if not args.executable:
        parser.error('an existing ACP executable is required; no runtime is installed automatically')
    prompt = args.prompt_file.read_text()
    try:
        executable = str(Path(args.executable).resolve(strict=True))
        with ReviewJournal(args.output, args.project, prompt, executable) as journal:
            result = journal.state
            if not result.get('cleanup_error') and (
                    result.get('phase') != 'finished' or result.get('status') == 'needs_inspection'):
                result = run_review([executable, 'acp', '--sandbox'], args.project,
                                    prompt, idle_timeout=args.idle_timeout, max_seconds=args.max_seconds,
                                    checkpoint=journal.update, resume_session=journal.state.get('session_id', ''))
                if result['status'] == 'ok':
                    journal.update({'_event': 'review.completed'})
                journal.update({**result, 'phase': 'finished', '_event': 'review.finished'})
    except (ValueError, OSError) as error:
        code = str(error) if type(error) is ValueError else 'review_record_unavailable'
        result = {'status': 'blocked', 'failure_code': code, 'next_action': 'inspect_existing_record'}
    print(json.dumps({k: v for k, v in result.items() if k != 'response'}))
    return 0 if result['status'] == 'ok' else 1


if __name__ == '__main__':
    raise SystemExit(_main())
