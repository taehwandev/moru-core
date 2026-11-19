"""Typed grouping transport; custom normalization and report values stay local.

Owner: NativeMemoryConsolidation. Allowed: stdlib/NativeProbe/typed upkeep and
review decoders, supplied normalizer. Forbidden: grouping algorithms, store IO/writes.
Callers/tests: consolidation group helpers and native consolidation tests.
"""
import unicodedata

from support.native_probe_transport import NativeProbe
from support import native_memory_upkeep as upkeep
from support import native_memory_review as review


def _bindings_match(owner, bindings):
    return all(getattr(owner,name,None) is original and original.__code__ is code
               and original.__defaults__ is defaults
               for name,(original,code,defaults) in bindings.items())


def _report_packet(records, threshold, *, relations=False):
    if (type(records) is not list or type(threshold) is not float or threshold != 0.8
            or any(current is not binding[0] or current.__code__ is not binding[1]
                   or current.__defaults__ is not binding[2] for current,binding in
                   ((NativeMemoryConsolidation.groups,_GROUPS_BINDING),
                    (NativeMemoryConsolidation.raw_groups,_RAW_GROUPS_BINDING)))):
        return None, False
    if not records:
        return {"duplicates":[],"shared_sources":[],**({"findings":[]} if relations else {})}, False
    try:
        if not NativeProbe.available():
            return None, False
    except (OSError, ValueError, RuntimeError):
        return None, False
    required = ("id", "scope", "body", "source")
    if any(type(record) is not dict or any(type(key) is not str for key in record)
           or any(type(record.get(key)) is not str for key in required)
           or (relations and record.get("replaces") is not None and type(record["replaces"]) is not str)
           for record in records):
        return None, False
    rows = [{key:record[key] for key in required} for record in records]
    if relations:
        for row,record in zip(rows,records): row["replaces"] = record.get("replaces")
    try:
        result = NativeProbe.request("--memory-probe", "report-text-groups",
            {"unicode":unicodedata.unidata_version,"records":rows,**({"relations":True} if relations else {})})
    except (OSError, ValueError, RuntimeError):
        return None, True
    return result, True


def _relation_profile():
    return (_bindings_match(NativeMemoryConsolidation,_REPORT_BINDINGS)
            and _bindings_match(upkeep.NativeMemoryUpkeep,upkeep._REPLACEMENT_BINDINGS))


def _relation_result(records, result):
    if type(result) is not dict or set(result) != {"duplicates","shared_sources","findings"}:
        return None
    groups = NativeMemoryConsolidation._report_result(records,
        {key:result[key] for key in ("duplicates","shared_sources")})
    replacements = upkeep.NativeMemoryUpkeep._replacement_result(records,{"findings":result["findings"]})
    return None if groups is None or replacements is None else (groups,replacements)


def _plan_packet(records, today, within_days, statuses, threshold, *, render_dates=False):
    if (not _relation_profile() or not _bindings_match(NativeMemoryConsolidation,_PLAN_BINDINGS)
            or not _bindings_match(review.NativeMemoryReview,review._REVIEW_BINDINGS)
            or not _bindings_match(review.NativeMemoryUpkeep,review._UPKEEP_REVIEW_BINDINGS)
            or review.date is not review._NATIVE_DATE or review.timedelta is not review._NATIVE_DELTA
            or type(today) is not review._NATIVE_DATE or type(within_days) is not int
            or type(statuses) is not frozenset or any(type(status) is not str for status in statuses)
            or type(threshold) is not float or threshold != 0.8):
        return None, False
    if not upkeep.NativeMemoryUpkeep._profile(records,("id","status")):
        return None, False
    horizon = today + review.timedelta(days=within_days)
    if not upkeep.NativeMemoryUpkeep._profile(records,("id","status","scope","body","source","review_on"),links=True):
        return None, False
    if not records:
        return {"review":{"live":[],"expired":[],"expiring":[]},
                "relations":{"duplicates":[],"shared_sources":[],"findings":[]}}, False
    try:
        if not NativeProbe.available():
            return None, False
    except (OSError, ValueError, RuntimeError):
        return None, False
    rows = [{key:row[key] for key in ("id","status","scope","body","source")} for row in records]
    for row,record in zip(rows,records):
        row.update(review=record["review_on"],replaces=record.get("replaces"))
    try:
        review_fields = {"today":today.isoformat(), "horizon":horizon.isoformat(),
                         "statuses":sorted(statuses)}
        if render_dates:
            review_fields["render_days"] = within_days
        result = NativeProbe.request("--memory-probe","report-text-groups",{
            "unicode":unicodedata.unidata_version,"records":rows,
            "review":review_fields})
    except (OSError, ValueError, RuntimeError):
        return None, True
    return result, True


class NativeMemoryConsolidation:
    @staticmethod
    def report_groups(records, threshold=0.8):
        result, attempted = _report_packet(records,threshold)
        return NativeMemoryConsolidation._report_result(records,result), attempted

    @staticmethod
    def report_relations(records, threshold=0.8):
        if not _relation_profile():
            return None, False
        result, attempted = _report_packet(records,threshold,relations=True)
        return _relation_result(records,result), attempted

    @staticmethod
    def report_plan(records, today, within_days, statuses, threshold=0.8, *, render_dates=False):
        result, attempted = _plan_packet(records,today,within_days,statuses,threshold,render_dates=render_dates)
        fields = {"review", "relations"}
        optional = {"date_entries", "replacement_entries", "group_entries"} if render_dates else set()
        if type(result) is not dict or not fields <= set(result) <= fields | optional:
            return None, attempted
        selected = review.NativeMemoryReview._decode(result["review"],records,statuses)
        if selected is None:
            return None, attempted
        relations = _relation_result(selected[0],result["relations"])
        if relations is None:
            return None, attempted
        plan = (selected, relations)
        if render_dates:
            plan += (_rendered_entries(selected, relations, result),)
        return plan, attempted

    @staticmethod
    def _report_result(records, result):
        if type(result) is not dict or set(result) != {"duplicates","shared_sources"}:
            return None
        groups = [NativeMemoryConsolidation._result(records,{"groups":result[key]})
                  for key in ("duplicates","shared_sources")]
        return None if any(group is None for group in groups) else tuple(groups)

    @staticmethod
    def raw_groups(operation, records, threshold=0.8):
        if (operation not in ("duplicate-groups", "shared-source-groups")
                or type(records) is not list or type(threshold) is not float or threshold != 0.8
                or NativeMemoryConsolidation.groups is not _GROUPS_BINDING[0]
                or NativeMemoryConsolidation.groups.__code__ is not _GROUPS_BINDING[1]
                or NativeMemoryConsolidation.groups.__defaults__ is not _GROUPS_BINDING[2]):
            return None, False
        if not records:
            return [], False
        try:
            if not NativeProbe.available():
                return None, False
        except (OSError, ValueError, RuntimeError):
            return None, False
        duplicate = operation == "duplicate-groups"
        required = ("id", "scope", "body") if duplicate else ("id", "source")
        if any(type(record) is not dict or any(type(key) is not str for key in record)
               or any(type(record.get(key)) is not str for key in required) for record in records):
            return None, False
        rows = [{key:record[key] for key in required} for record in records]
        try:
            result = NativeProbe.request("--memory-probe", "duplicate-text-groups" if duplicate else "shared-source-text-groups",
                {"unicode":unicodedata.unidata_version,"records":rows})
        except (OSError, ValueError, RuntimeError):
            return None, True
        return NativeMemoryConsolidation._result(records, result), True

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
        return NativeMemoryConsolidation._result(records, result)

    @staticmethod
    def _result(records, result):
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


_GROUPS_BINDING = (NativeMemoryConsolidation.groups, NativeMemoryConsolidation.groups.__code__,
                   NativeMemoryConsolidation.groups.__defaults__)
_RAW_GROUPS_BINDING = (NativeMemoryConsolidation.raw_groups, NativeMemoryConsolidation.raw_groups.__code__,
                       NativeMemoryConsolidation.raw_groups.__defaults__)
_REPORT_BINDINGS = {name:(getattr(NativeMemoryConsolidation,name),
    getattr(NativeMemoryConsolidation,name).__code__,getattr(NativeMemoryConsolidation,name).__defaults__)
    for name in ("report_groups","_report_result","_result")}
_PLAN_BINDINGS = {"report_relations":(NativeMemoryConsolidation.report_relations,
    NativeMemoryConsolidation.report_relations.__code__,NativeMemoryConsolidation.report_relations.__defaults__)}
_REPORT_PLAN_BINDING = (NativeMemoryConsolidation.report_plan, NativeMemoryConsolidation.report_plan.__code__,
    NativeMemoryConsolidation.report_plan.__defaults__, dict(NativeMemoryConsolidation.report_plan.__kwdefaults__))


def _rendered_entries(selected, relations, result):
    entries = dict(_date_entries(selected, result.get("date_entries")) or {})
    replacements = result.get("replacement_entries")
    if _valid_entries([record for record, _ in relations[1]], replacements,
                      [links for _, links in relations[1]]):
        entries["unfinished_replacements"] = replacements
    groups = _group_entries(relations[0], result.get("group_entries"))
    if groups is not None:
        entries["groups"] = groups
    return entries


def _date_entries(selected, value):
    if type(value) is not dict or set(value) != {"expired", "expiring"}:
        return None
    for rows, bucket in zip(selected[1:], ("expired", "expiring")):
        if not _valid_entries(rows, value[bucket]):
            return None
    return value


def _group_entries(groups, value):
    if type(value) is not dict or set(value) != {"duplicate_groups", "shared_source_groups"}:
        return None
    buckets = (value["duplicate_groups"], value["shared_source_groups"])
    for members, rendered in zip(groups, buckets):
        if type(rendered) is not list or len(members) != len(rendered):
            return None
        for records, group in zip(members, rendered):
            if (type(group) is not dict or tuple(group) != ("ids", "reason", "records")
                    or type(group["ids"]) is not list
                    or any(type(value) is not str for value in group["ids"])
                    or group["ids"] != [record["id"] for record in records]
                    or type(group["reason"]) is not str or not group["reason"]
                    or not _valid_entries(records, group["records"], with_reason=False)):
                return None
    return buckets


def _valid_entries(rows, entries, replacements=None, *, with_reason=True):
    if type(entries) is not list or len(entries) != len(rows):
        return False
    keys = ("id", "scope", "body", "source", "review_on")
    order = (*keys, "reason") if with_reason else keys
    if replacements is not None:
        order = (*order, "replaced_by")
    for index, (row, entry) in enumerate(zip(rows, entries)):
        if (type(entry) is not dict or tuple(entry) != order
                or any(type(entry[key]) is not str or type(row.get(key)) is not str
                       or entry[key] != row[key] for key in keys)
                or with_reason and (type(entry["reason"]) is not str or not entry["reason"])):
            return False
        if replacements is not None:
            links = entry["replaced_by"]
            if (type(links) is not list or any(type(link) is not str for link in links)
                    or links != replacements[index]):
                return False
    return True
