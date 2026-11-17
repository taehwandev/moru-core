"""Owner: deterministic review section packing and source deduplication.
Allowed imports: hashlib only; rendering is injected. Forbidden: I/O/execution.
Callers/tests: ReviewPacket; test_agent_review_packet_assembly.
Verification: whole sections, explicit omissions, added-source fallback.
"""
import hashlib


class ReviewAssembly:
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
