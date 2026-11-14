"""Typed analysis transport; preserve original records and caller authority.

Owner: NativeMemoryAnalysis. Allowed: stdlib/NativeProbe. Forbidden: matching,
normalization, freshness checks, store writes/providers. Tests: native analysis.
"""
import unicodedata

from support.native_probe_transport import NativeProbe


class NativeMemoryAnalysis:
    @staticmethod
    def binding(question, context):
        if type(question) is not str or type(context) is not str:
            return None
        if not question and not context:
            return {"binding": None}
        result = NativeMemoryAnalysis._request("analysis-binding", {"question":question,"context":context})
        if type(result) is not dict:
            return None
        if set(result) == {"invalid"} and result["invalid"] is True:
            return result
        if set(result) != {"binding"}:
            return None
        binding = result["binding"]
        if binding is None:
            return None
        if (type(binding) is not dict or set(binding) != {"question","context"}
                or any(type(v) is not str or not v for v in binding.values())):
            return None
        return {"binding": {key:binding[key] for key in ("question","context")}}

    @staticmethod
    def candidates(scope, binding, records):
        if (type(scope) is not str or type(binding) is not dict
                or any(type(key) is not str for key in binding)
                or set(binding) != {"question","context"} or type(records) is not list
                or any(type(v) is not str for v in binding.values())):
            return None
        if not records:
            return []
        rows = []
        for record in records:
            if (type(record) is not dict or any(type(key) is not str for key in record)
                    or type(record.get("scope")) is not str):
                return None
            analysis = None
            if "analysis" in record:
                value = record["analysis"]
                if (type(value) is not dict or any(type(key) is not str for key in value)
                        or any(value.get(key) is not None and type(value[key]) is not str
                               for key in ("question","context"))):
                    return None
                analysis = {key:value.get(key) for key in ("question","context")}
            rows.append({"scope":record["scope"],"analysis":analysis})
        result = NativeMemoryAnalysis._request("analysis-candidates", {"scope":scope,"binding":binding,"records":rows})
        if type(result) is not dict or set(result) != {"indices"}:
            return None
        indices = result["indices"]
        if (type(indices) is not list or any(type(i) is not int or not 0 <= i < len(records) for i in indices)
                or any(left >= right for left, right in zip(indices, indices[1:]))):
            return None
        return [records[i] for i in indices]

    @staticmethod
    def _request(operation, payload):
        try:
            return NativeProbe.request("--memory-probe", operation, {"unicode":unicodedata.unidata_version, **payload})
        except (OSError, ValueError, RuntimeError):
            return None
