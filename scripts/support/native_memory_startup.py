"""Owner: NativeMemoryStartup; allowed: stdlib, NativeProbe, upkeep profile guards.
Forbidden: normalization/count algorithms, store IO, writes, providers/authority.
Callers/tests: canonical startup_summary_line and native startup-text parity tests.
"""
from datetime import date

from support.native_memory_upkeep import NativeMemoryUpkeep, _COUNTS
from support.native_probe_transport import NativeProbe


class NativeMemoryStartup:
    @staticmethod
    def hints(records, today, statuses):
        if (not NativeMemoryUpkeep._profile(records, ("status",))
                or type(statuses) is not frozenset or any(type(s) is not str for s in statuses)):
            return None
        live_count = 0
        for row in records:
            if row["status"] in statuses:
                if not NativeMemoryUpkeep._profile([row], ("id", "body", "scope", "source", "review_on"), links=True):
                    return None
                live_count += 1
        if type(today) is not date:
            return None
        if not live_count:
            return dict.fromkeys(_COUNTS, 0)
        try:
            if not NativeProbe.available():
                return None
        except (OSError, ValueError, RuntimeError):
            return None
        rows = []
        for record in records:
            row = dict.fromkeys(("id", "body", "scope", "source", "review", "replaces"))
            row["status"] = record["status"]
            if record["status"] in statuses:
                row.update({key:record[key] for key in ("id", "body", "scope", "source")},
                           review=record["review_on"],replaces=record.get("replaces"))
            rows.append(row)
        result = NativeMemoryUpkeep._request("upkeep-startup-text", rows, today=today.isoformat(),
                                            statuses=sorted(statuses))
        counts = result.get("counts") if type(result) is dict and set(result) == {"counts"} else None
        if (type(counts) is dict and set(counts) == set(_COUNTS)
                and all(type(n) is int and 0 <= n <= live_count for n in counts.values())):
            return {key:counts[key] for key in _COUNTS}
        return None
