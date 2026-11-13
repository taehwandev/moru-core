"""Owner: NativeMemoryUpkeep; allowed: stdlib/NativeProbe and supplied callbacks.
Forbidden: aggregation, sorting decisions, store IO/writes/providers.
Callers/tests: consolidation helpers and native upkeep parity tests.
"""
from datetime import date
import unicodedata

from support.native_probe_transport import NativeProbe

_COUNTS = ("expired", "exact_duplicates", "shared_source", "unfinished")


class NativeMemoryUpkeep:
    @staticmethod
    def _profile(records, fields, links=False):
        return (type(records) is list and all(type(row) is dict
            and all(type(key) is str for key in row)
            and all(type(row.get(key)) is str for key in fields)
            and (not links or row.get("replaces") is None or type(row["replaces"]) is str) for row in records))

    @staticmethod
    def _request(operation, rows, **fields):
        try:
            return NativeProbe.request("--memory-probe", operation,
                {"unicode":unicodedata.unidata_version, "records":rows, **fields})
        except (OSError, ValueError, RuntimeError):
            return None

    @staticmethod
    def _ordered(indices, records):
        return (type(indices) is list and all(type(i) is int and 0 <= i < len(records) for i in indices)
            and all((records[a]["id"], a) < (records[b]["id"], b) for a,b in zip(indices, indices[1:])))

    @staticmethod
    def live(records, statuses):
        if (not NativeMemoryUpkeep._profile(records, ("id", "status"))
                or type(statuses) is not frozenset or any(type(s) is not str for s in statuses)):
            return None
        if not records:
            return []
        rows = [{key:row[key] for key in ("id", "status")} for row in records]
        result = NativeMemoryUpkeep._request("upkeep-live", rows, statuses=sorted(statuses))
        if (type(result) is not dict or set(result) != {"indices"}
                or not NativeMemoryUpkeep._ordered(result["indices"], records)
                or any(records[i]["status"] not in statuses for i in result["indices"])):
            return None
        return [records[i] for i in result["indices"]]

    @staticmethod
    def replacements(records):
        if not NativeMemoryUpkeep._profile(records, ("id",), links=True):
            return None
        if not records:
            return []
        result = NativeMemoryUpkeep._request("upkeep-replacements",
            [{"id":row["id"], "replaces":row.get("replaces")} for row in records])
        if type(result) is not dict or set(result) != {"findings"} or type(result["findings"]) is not list:
            return None
        findings = []
        previous = -1
        for item in result["findings"]:
            if type(item) is not dict or set(item) != {"index", "replacements"}:
                return None
            index, members = item["index"], item["replacements"]
            if (type(index) is not int or not previous < index < len(records)
                    or not NativeMemoryUpkeep._ordered(members, records) or not members):
                return None
            previous = index
            findings.append((records[index], [records[i]["id"] for i in members]))
        return findings

    @staticmethod
    def startup(records, normalizer, parse_date, today, statuses):
        if (not NativeMemoryUpkeep._profile(records, ("status",))
                or type(statuses) is not frozenset or any(type(s) is not str for s in statuses)):
            return None
        records = [row for row in records if row["status"] in statuses]
        if (not NativeMemoryUpkeep._profile(records, ("id","body","scope","source","review_on"), links=True)
                or type(today) is not date):
            return None
        if not records:
            return dict.fromkeys(_COUNTS, 0), []
        try:
            available = NativeProbe.available()
        except (OSError, ValueError, RuntimeError):
            return None
        if not available:
            return None
        rows = [{"id":row["id"],"body":normalizer(row["body"]),"scope":row["scope"],
                 "source":normalizer(row["source"]),"replaces":row.get("replaces")} for row in records]
        for row, original in zip(rows, records):
            row["review"] = parse_date(original["review_on"]).toordinal()
        result = NativeMemoryUpkeep._request("upkeep-startup", rows, today=today.toordinal())
        if type(result) is not dict or set(result) != {"counts"}:
            return None, rows
        counts = result["counts"]
        if (type(counts) is not dict or set(counts) != set(_COUNTS)
                or any(type(n) is not int or not 0 <= n <= len(records) for n in counts.values())):
            return None, rows
        return {key:counts[key] for key in _COUNTS}, rows
