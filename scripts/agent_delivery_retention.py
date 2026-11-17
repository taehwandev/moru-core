"""Owner: read-only delivery retention across settled runs.
Allowed imports: canonical binding, publication, checkpoint and discovery readers.
Forbidden: settlement, Git/provider execution, deletion and lifecycle mutation.
Callers/tests: checkout removal; test_agent_delivery_retention.
Verification: actual debt, corrupt checkpoints, pruned history and settlement.
"""
import json
from pathlib import Path


def _retained(path):
    if path is None:
        return False
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False


class DeliveryRetention:
    @staticmethod
    def reason(project: Path) -> str:
        try:
            from agent_registry_read import active_run_bindings
            from agent_state_read import evidence_binding_key
            from agent_pending_publication import outstanding, kind
            from agent_work_completion import bound_work_packet
            from agent_continuation_store import continuation_path
            from support.global_state import project_state_dir_target
            state = project_state_dir_target(project.resolve())
            bindings = active_run_bindings(project, frozenset({'completed', 'cancelled'}))
            discovered, scan_complete = None, True
            for key, run in bindings.items():
                run_id, name = run.get('run_id', ''), run.get('evidence_name', 'preflight.json')
                if (not isinstance(run_id, str) or Path(run_id).name != run_id or run_id in ('', '.', '..')
                        or not isinstance(name, str) or Path(name).name != name or name in ('', '.', '..')):
                    return 'settled run binding is unreadable; inspect or restore its delivery records'
                candidates = (state / 'runs' / run_id / name, state / name)
                evidence = next((p for p in candidates if evidence_binding_key(project, p) == key), None)
                if evidence is None:
                    if discovered is None:
                        from agent_runtime_session import runtime_evidence_candidates
                        names = {r.get('evidence_name', 'preflight.json') for r in bindings.values()
                                 if isinstance(r.get('evidence_name', 'preflight.json'), str)}
                        normal, workers, scan_complete = runtime_evidence_candidates(project, names | {'pending-publication.json'})
                        discovered = {}
                        for path in (*normal, *workers):
                            paths = [path.with_name(n) for n in names] if path.name == 'pending-publication.json' else [path]
                            discovered.update({evidence_binding_key(project, p): p for p in paths})
                    evidence = discovered.get(key)
                checkpoint = continuation_path(project, run_id)
                receipt = evidence.with_name('pending-publication.json') if evidence is not None else None
                has_receipt = _retained(receipt)
                if evidence is None and not scan_complete:
                    return 'delivery inspection incomplete; restore access before cleanup'
                if run.get('state') == 'cancelled' and not has_receipt:
                    continue  # Cancellation without a prepared receipt does not create delivery debt.
                if not has_receipt and not _retained(checkpoint):
                    continue  # Pruned history without retained delivery declarations is not new debt.
                if (has_receipt and (receipt.is_symlink() or receipt.stat().st_size > 1024 * 1024)
                        or evidence is not None and evidence.exists() and evidence.stat().st_size > 1024 * 1024):
                    return 'retained delivery evidence exceeds its safe read budget; inspect or restore it before cleanup'
                declared = []
                if not has_receipt:
                    if checkpoint.is_symlink() or checkpoint.stat().st_size > 1024 * 1024:
                        return 'delivery checkpoint is unreadable; inspect or restore it before cleanup'
                    raw = json.loads(checkpoint.read_text(encoding='utf-8'))
                    if not isinstance(raw, dict) or not isinstance(raw.get('work'), dict):
                        return 'delivery checkpoint is malformed; inspect or restore it before cleanup'
                    packet = bound_work_packet(project, evidence) if evidence is not None and evidence.is_file() else raw
                    if not isinstance(packet, dict) or not isinstance(packet.get('work'), dict):
                        return 'delivery checkpoint binding is unavailable; inspect or restore it before cleanup'
                    remaining = packet['work'].get('remaining_work', [])
                    if not isinstance(remaining, list):
                        return 'delivery checkpoint scope is malformed; inspect or restore it before cleanup'
                    declared = [item for item in remaining if isinstance(item, dict) and kind(item.get('checkpoint'))]
                    if not declared:
                        continue
                if evidence is None or not evidence.is_file() or evidence.is_symlink():
                    return 'declared delivery evidence is unavailable; inspect or restore it before cleanup'
                owed = outstanding(project, evidence, declared)
                if owed:
                    return 'it retains unobserved delivery (' + ', '.join(owed) + '); settle authorized actions or retain records for inspection'
        except (OSError, ValueError, RuntimeError, TypeError, KeyError, AttributeError, ImportError):
            return 'delivery evidence could not be inspected; restore or inspect the retained records before cleanup'
        return ''
