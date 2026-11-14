"""Owner: NativeMemoryReview; allowed: stdlib/NativeProbe/typed upkeep guards.
Forbidden: date classification, sorting decisions, store IO/writes/providers.
Callers/tests: consolidation review inputs and native review parity tests.
"""
from datetime import date, timedelta
import unicodedata

from support.native_memory_upkeep import NativeMemoryUpkeep
from support.native_probe_transport import NativeProbe


class NativeMemoryReview:
    @staticmethod
    def _request(operation, records, today, horizon, **fields):
        try:
            return NativeProbe.request("--memory-probe", operation, {
                "unicode":unicodedata.unidata_version,"records":records,
                "today":today.isoformat(),"horizon":horizon.isoformat(),**fields})
        except (OSError, ValueError, RuntimeError):
            return None

    @staticmethod
    def _decode(result, records, statuses=None):
        if type(result) is not dict or set(result) != {"live","expired","expiring"}:
            return None
        live = result["live"]
        if (type(live) is not list or any(type(i) is not int or not 0 <= i < len(records) for i in live)
                or len(set(live)) != len(live)):
            return None
        if statuses is None:
            if live != list(range(len(records))):
                return None
        elif (not NativeMemoryUpkeep._ordered(live, records)
              or any(records[i]["status"] not in statuses for i in live)):
            return None
        positions = {index:slot for slot,index in enumerate(live)}
        selected = []
        for key in ("expired","expiring"):
            indices = result[key]
            if (type(indices) is not list or any(type(i) is not int or i not in positions for i in indices)
                    or any(positions[a] >= positions[b] for a,b in zip(indices,indices[1:]))):
                return None
            selected.append(indices)
        if set(selected[0]).intersection(selected[1]):
            return None
        return ([records[i] for i in live], *[[records[i] for i in indices] for indices in selected])

    @staticmethod
    def partition(records, today, horizon):
        if (not NativeMemoryUpkeep._profile(records,("id","review_on"))
                or type(today) is not date or type(horizon) is not date):
            return None
        if not records:
            return [], []
        result = NativeMemoryReview._request("review-partition",
            [{"id":row["id"],"review":row["review_on"]} for row in records],today,horizon)
        decoded = NativeMemoryReview._decode(result,records)
        return None if decoded is None else decoded[1:]

    @staticmethod
    def findings_inputs(records, today, within_days, statuses):
        if (not NativeMemoryUpkeep._profile(records,("id","status")) or type(today) is not date
                or type(within_days) is not int or type(statuses) is not frozenset
                or any(type(status) is not str for status in statuses)):
            return None
        # Ordinary IDs/statuses cannot fail the original preceding filter/sort.
        # Preserve horizon overflow before parsing dates, including empty stores.
        horizon = today + timedelta(days=within_days)
        if not records:
            return [], [], []
        rows = [{"id":row["id"],"status":row["status"],
                 "review":row.get("review_on") if type(row.get("review_on")) is str else None} for row in records]
        result = NativeMemoryReview._request("review-findings",rows,today,horizon,statuses=sorted(statuses))
        return NativeMemoryReview._decode(result,records,statuses)
