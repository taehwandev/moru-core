"""Typed grouping transport; original normalization and report values stay local.

Owner: NativeMemoryConsolidation. Allowed: stdlib/NativeProbe, supplied original
normalizer. Forbidden: pair comparison, union-find, grouping, store IO/writes.
Callers/tests: consolidation group helpers and native consolidation tests.
"""
import unicodedata

from support.native_probe_transport import NativeProbe


class NativeMemoryConsolidation:
    @staticmethod
    def groups(operation, records, normalizer, threshold=0.8):
        if (operation not in ("duplicate-groups", "shared-source-groups")
                or type(records) is not list or type(threshold) is not float or threshold != 0.8):
            return None
        required = ("id", "scope", "body") if operation == "duplicate-groups" else ("id", "source")
        if any(type(record) is not dict or any(type(key) is not str for key in record)
               or any(type(record.get(key)) is not str for key in required) for record in records):
            return None
        if not records:
            return []
        rows = []
        for record in records:
            row = {"id": record["id"]}
            if operation == "duplicate-groups":
                row.update(scope=record["scope"], tokens=sorted(normalizer(record["body"])))
            else:
                row["source"] = normalizer(record["source"])
            rows.append(row)
        try:
            result = NativeProbe.request("--memory-probe", operation,
                {"unicode": unicodedata.unidata_version, "records": rows})
        except (OSError, ValueError, RuntimeError):
            return None
        if type(result) is not dict or set(result) != {"groups"} or type(result["groups"]) is not list:
            return None
        seen = set()
        previous = None
        for group in result["groups"]:
            if (type(group) is not list or len(group) < 2
                    or any(type(i) is not int or not 0 <= i < len(records) for i in group)
                    or len(group) != len(set(group)) or seen.intersection(group)):
                return None
            seen.update(group)
            if any((records[a]["id"], a) > (records[b]["id"], b) for a, b in zip(group, group[1:])):
                return None
            key = (tuple(records[i]["id"] for i in group), min(group))
            if previous is not None and key < previous:
                return None
            previous = key
        return [[records[i] for i in group] for group in result["groups"]]
