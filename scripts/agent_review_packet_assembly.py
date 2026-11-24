"""Owner: deterministic review section packing and source deduplication.
Allowed imports: hashlib and the private native transport. Forbidden: source I/O, Git and provider execution.
Callers/tests: ReviewPacket; test_agent_review_packet_assembly.
Verification: whole sections, explicit omissions, added-source fallback.
"""
import hashlib
from support.native_probe_transport import NativeProbe


class ReviewAssembly:
    @staticmethod
    def build_native(packet, pending, fixed, *, render_output):
        result = NativeProbe.request("--review-packet-probe", "assemble", {
            "packet": packet, "pending": pending, "fixed": fixed, "render_output": render_output,
        })
        if result is None:
            return None
        if set(result) == {"error"} and type(result["error"]) is str:
            raise ValueError(result["error"])
        if render_output and set(result) == {"text"} and type(result["text"]) is str:
            text = result["text"]
            if text.startswith("{\n") and text.endswith("}\n") and len(text.encode("utf-8")) <= packet["max_bytes"]:
                return text
        if set(result) == {"packet"} and isinstance(result["packet"], dict):
            output = result["packet"]
            digest = output.get("packet_sha256")
            if (output.get("schema_version") == packet["schema_version"]
                    and output.get("context_only") is True and output.get("no_execution") is True
                    and type(digest) is str and len(digest) == 64
                    and all(char in "0123456789abcdef" for char in digest)):
                return output
        return None

    @staticmethod
    def build(packet, pending, fixed, render):
        kept = set()
        def size():
            packet['omissions'] = fixed + [item[2] for number, item in enumerate(pending) if number not in kept]
            return len(render(packet).encode('utf-8'))
        if size() > packet['max_bytes']:
            raise ValueError('max_bytes is too small for the packet metadata and omissions')
        added = {f['path'] for f in packet['files'] if f['status'] == 'added'}
        for number, (bucket, section, omission) in enumerate(pending):
            kept.add(number)
            covered = (bucket in ('definitions', 'contracts') and section['path'] in added
                       and any(d['path'] == section['path'] for d in packet['diffs']))
            if covered:
                fixed.append(dict(omission, reason='covered_by_diff'))
                continue
            packet[bucket].append(section)
            if size() > packet['max_bytes']:
                kept.discard(number)
                packet[bucket].pop()
        if size() > packet['max_bytes']:
            raise ValueError('review packet metadata exceeds its output budget')
        body = {key: value for key, value in packet.items() if key != 'packet_sha256'}
        packet['packet_sha256'] = hashlib.sha256(render(body).encode('utf-8')).hexdigest()
        return packet
