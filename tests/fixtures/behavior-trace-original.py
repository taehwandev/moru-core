"""Owner: observed-review trace ingress; allowed imports: stdlib only.
Forbidden: normalization rules, providers, workflow writes and model execution.
Caller: explicit offline CLI; tests: test_agent_behavior_trace.
Verification: real ACP journal -> Rust normalizer -> behavior evaluator.
"""
import argparse
import json
from pathlib import Path
import subprocess

MAX_BYTES = 4 * 1024 * 1024


def export_review(record, *, provider, case_id, native_executable):
    with Path(record).open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('review_record_too_large')
    journal = json.loads(raw)
    if (not isinstance(journal, dict) or journal.get('phase') != 'finished'
            or not journal.get('runtime_path') or not journal.get('runtime_digest')
            or not isinstance(journal.get('events'), list)):
        raise ValueError('review_evidence_incomplete')
    events = journal['events']
    if (not events or not isinstance(events[-1], dict)
            or events[-1].get('event_type') != 'review.finished'
            or events[-1].get('status') != journal.get('status')):
        raise ValueError('review_receipt_mismatch')
    # Pass only the explicit content-free event schema, never response/session text.
    if any(not isinstance(e, dict) or not set(e) <= {'event_type', 'status'} for e in events):
        raise ValueError('review_event_schema_invalid')
    payload = {'schema_version': 1, 'provider': provider, 'case_id': case_id, 'events': events}
    request = json.dumps(payload, allow_nan=False).encode()
    if len(request) > MAX_BYTES:
        raise ValueError('review_trace_too_large')
    done = subprocess.run([str(Path(native_executable).resolve(strict=True)),
                           'offline-trace', '--behavior-trace-probe'],
                          input=request, capture_output=True, timeout=10)
    if done.returncode or done.stderr or len(done.stdout) > MAX_BYTES:
        raise ValueError('native_trace_rejected')
    return json.loads(done.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review-record', required=True, type=Path)
    parser.add_argument('--provider', required=True, choices=('codex', 'claude', 'agy'))
    parser.add_argument('--case-id', required=True)
    parser.add_argument('--native-executable', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = export_review(args.review_record, provider=args.provider, case_id=args.case_id,
                               native_executable=args.native_executable)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        parser.exit(1, 'Observed trace export failed; inspect the local record and native candidate.\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
