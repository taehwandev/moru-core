"""Owner: NativeMemoryCapture typed scalar-admission transport.
Allowed: stdlib/NativeProbe. Forbidden: validation algorithms, store IO/writes,
providers or authority. Caller: project-memory capture; tests: native capture.
"""
from datetime import date
import unicodedata

from support.native_probe_transport import NativeProbe


class NativeMemoryCapture:
    @staticmethod
    def inputs(body, source, scope, review_on, applies_when, not_when, *, digest=False):
        values = dict(zip(("body","source","scope","review_on","applies_when","not_when"),
                          (body,source,scope,review_on,applies_when,not_when)))
        if type(digest) is not bool or any(type(value) is not str for value in values.values()):
            return None
        try:
            if not NativeProbe.available():
                return None
            packet = {"unicode":unicodedata.unidata_version,"today":date.today().isoformat(),**values}
            if digest:packet["digest"] = True
            result = NativeProbe.request("--memory-probe","capture-inputs",packet)
        except (OSError, ValueError, RuntimeError, OverflowError):
            return None
        if type(result) is not dict:
            return None
        if set(result) == {"invalid"}:
            return result if type(result["invalid"]) is str and result["invalid"] in (
                "body","source","scope","review","conditions") else None
        if (set(result) != {"body","source","conditions"} | ({"digest"} if digest else set())
                or any(type(result[key]) is not str or not result[key] for key in ("body","source"))
                or type(result["conditions"]) is not dict
                or any(type(key) is not str or key not in ("applies_when","not_when")
                       or type(value) is not str or not value for key,value in result["conditions"].items())):
            return None
        if digest and (type(result["digest"]) is not str or len(result["digest"]) != 64
                       or any(c not in "0123456789abcdef" for c in result["digest"])):
            return None
        return {"body":result["body"],"source":result["source"],
                "conditions":{key:result["conditions"][key] for key in ("applies_when","not_when")
                              if key in result["conditions"]},
                **({"digest":result["digest"]} if digest else {})}


_INPUTS_BINDING = (NativeMemoryCapture.inputs, NativeMemoryCapture.inputs.__code__,
    NativeMemoryCapture.inputs.__defaults__, dict(NativeMemoryCapture.inputs.__kwdefaults__ or {}))
