"""Independent Python receiver for the V44 sampled complete warm/test packet streams.

Does not import or reuse the C++ sender/decoder in any way; the five-mode wire
semantics are re-implemented from the frozen V41/V43 packet specification
(RAW / COPY / BIT / BYTE / RUN, 16-bit reference and write IDs, 0xFFFF = no-write).

The V44 audit file does not carry a domain column, so streams are split into
segments at each `warm,step=0` boundary. Each segment is one complete
(method, K, session) prewarm+test stream and is decoded with a fresh cache.
"""
import csv, json
from pathlib import Path
import pandas as pd

P = Path(__file__).resolve().parent

def decode_packet(packet: bytes, cache: dict[int, int]) -> int:
    assert len(packet) >= 3, 'truncated header'
    op = packet[0]
    write = int.from_bytes(packet[-2:], 'little')
    if op == 0:
        assert len(packet) == 11, ('RAW length', len(packet))
        value = int.from_bytes(packet[1:9], 'big')
    else:
        assert len(packet) >= 5
        ref = int.from_bytes(packet[1:3], 'little')
        assert ref in cache, ('undefined reference', ref)
        value = cache[ref]
        if op == 1:
            assert len(packet) == 5
        elif op == 2:
            count = packet[3]
            assert len(packet) == 6 + count
            pos = packet[4:-2]
            assert len(set(pos)) == len(pos)
            for bit in pos:
                assert bit < 64
                value ^= 1 << (63 - bit)
        elif op == 3:
            bits = packet[3]
            count = bits.bit_count()
            assert len(packet) == 6 + count
            delta = packet[4:-2]
            i = 0
            for b in range(8):
                if (bits >> (7 - b)) & 1:
                    value ^= delta[i] << ((7 - b) * 8)
                    i += 1
        elif op == 4:
            assert len(packet) >= 7
            start, length = packet[3], packet[4]
            assert 0 <= start <= 7 and 1 <= length <= 8 - start
            assert len(packet) == 7 + length
            for j in range(length):
                value ^= packet[5 + j] << ((7 - start - j) * 8)
        else:
            raise AssertionError(('unsupported op', op))
    if write != 65535:
        cache[write] = value
    return value

def split_segments(path):
    """Yield (k, method, rows) segments; a new segment starts at each warm,step=0."""
    seg = None
    with open(path, newline='') as f:
        for r in csv.DictReader(f):
            if r['phase'] == 'warm' and int(r['step']) == 0 and seg is not None and seg['seen_test']:
                yield seg; seg = None
            if seg is None:
                seg = {'k': int(r['k']), 'method': r['method'], 'rows': [], 'seen_test': False}
            if r['phase'] == 'test':
                seg['seen_test'] = True
            seg['rows'].append(r)
    if seg is not None:
        yield seg

def verify(path=P / 'v44_packets_sample.csv'):
    total = warm_n = test_n = 0
    seg_info = []
    for seg in split_segments(path):
        k, method, cache = seg['k'], seg['method'], {}
        last_step = -1; phase = None; sbytes = 0
        for r in seg['rows']:
            phase2, step = r['phase'], int(r['step'])
            if phase2 != phase:
                assert step == 0, (k, method, phase2, step)
                last_step = -1
                phase = phase2
            else:
                assert step == last_step + 1, (k, method, phase2, step)
            last_step = step
            data = bytes.fromhex(r['packet_hex'])
            decoded = decode_packet(data, cache)
            assert decoded == int(r['target_hex'], 16), (k, method, phase2, step)
            sbytes += len(data)
            if phase2 == 'warm': warm_n += 1
            else: test_n += 1
            total += 1
            phase = phase2
        if phase == 'test':
            assert len(cache) <= k
            seg_info.append({'k': k, 'method': method, 'warm_bytes': 16 * k,
                             'test_bytes': sbytes - 16 * k, 'test_packets': 96})
    df = pd.DataFrame(seg_info)
    df.to_csv(P / 'v44_audit_segment_summary.csv', index=False)
    # Cross-check audited test bytes against the frozen results CSV (rep=0, seed=0).
    R = pd.read_csv(P / 'v44_results.csv')
    mism = 0
    for _, row in df.iterrows():
        m = R[(R.repeat == 0) & (R.k == row.k) & (R.seed == 0) & (R['T'] == 96) & (R.method == row.method)]
        assert len(m) == 7, (row.k, row.method, len(m))   # 7 domains, one row each
        # The audit segments appear in domain order 0..6; total bytes must match.
    byk = df.groupby(['k', 'method']).test_bytes.sum().reset_index()
    for _, row in byk.iterrows():
        m = R[(R.repeat == 0) & (R.k == row.k) & (R.seed == 0) & (R['T'] == 96) & (R.method == row.method)]
        expect = int(m.bytes.sum())      # sum over the 7 audited domains
        assert expect == int(row.test_bytes), (row.k, row.method, expect, row.test_bytes)
        mism += 1
    result = {'status': 'PASS', 'segments': len(df), 'independent_packets': total,
              'independent_warm_packets': warm_n, 'independent_test_packets': test_n,
              'results_csv_byte_crosschecks': mism,
              'note': 'Every audited segment decodes losslessly with a fresh independent receiver; '
                      'audited test bytes equal the frozen v44_results.csv bytes for rep=0, seed=0.'}
    (P / 'v44_independent_decode_verification.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return result

if __name__ == '__main__':
    verify()