import pathlib, random, sys, unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from glassradio_v44_portable import MASK64, make_packet, independent_decode, make_records, replay_trace
class ProtocolTests(unittest.TestCase):
    def test_all_modes_random(self):
        r=random.Random(42)
        for _ in range(1000):
            ref=r.getrandbits(64);target=ref ^ r.getrandbits(64)
            for w in (65535,0):
                p,m=make_packet(target,0,ref,w)
                cache={0:ref};out=independent_decode(p,cache)
                self.assertEqual(out,target)
                if w!=65535:self.assertEqual(cache[w],target)
    def test_copy_byte_run_bit_raw(self):
        ref=0xAA00BB0000000000
        targets=[ref,ref^1,ref^0xff00,ref^0xffff,0x1000200030004000]
        cache={0:ref}
        for x in targets:
            p,m=make_packet(x,0,ref)
            self.assertEqual(independent_decode(p,cache),x)
    def test_simulation_cross_policy(self):
        r=random.Random(4)
        vals=[r.getrandbits(64) for _ in range(50)]
        changes=[(vals[i%10],{'frame':i,'row':0,'col':0}) for i in range(100)]
        records=make_records(changes,'random',4)
        for m in ('full_lru','recent16_lru','recent256_lru','exact_lru','bs1_lru','bs2_lru','cascade_lru','full_sieve','full_gds'):
            summary,log=replay_trace(records,m,16)
            self.assertEqual(summary['lossless_errors'],0,m)
            self.assertEqual(summary['receiver_budget_violations'],0,m)
            self.assertEqual(summary['updates'],100)
            self.assertTrue(all(x['lossless']==1 for x in log))
if __name__=='__main__': unittest.main()
