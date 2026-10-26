import unittest
from ports.redfin.direct_output_evidence import analyze


class DirectOutputEvidenceTests(unittest.TestCase):
    def test_actual_pixel_check_and_monotonic_direct_presents_are_both_required(self):
        native='REDFIN GPU DIRECT CHECK: ABI=2 cases=4 pixels=10108800 mismatches=0 guard-errors=0 stage-writes=0 completed=1 tolerance=2 exact-pixels=2527200 alpha-exact=1 max-error=2'
        cases=[f'REDFIN GPU DIRECT CASE: ABI=2 c={c} w={w} h={h} pixels=2527200 max={2 if c else 0} over1={100 if c else 0} bad=0 guards=0 stage=0 limit={2 if c else 0} done=1'
               for c,(w,h) in enumerate(((1080,2340),(1125,2436),(1125,2435),(80,61)))]
        first='REDFIN GPU DIRECT PRESENT: n=1 direct=1 staged=0 ABI=2 full-image-only=1 CPU-pixel-copy=0'
        last='REDFIN GPU DIRECT PRESENT: n=120 direct=120 staged=0 ABI=2 full-image-only=1 CPU-pixel-copy=0'
        self.assertTrue(analyze([native,*cases,first,last])['actual_direct_GPU_output'])
        self.assertFalse(analyze([native,*cases])['actual_direct_GPU_output'])
        self.assertFalse(analyze([first,last])['actual_direct_GPU_output'])
        for bad in (native.replace('cases=4','cases=1'),native.replace('mismatches=0','mismatches=1'),
                    native.replace('stage-writes=0','stage-writes=1'),native.replace('tolerance=2','tolerance=255'),
                    native.replace('exact-pixels=2527200','exact-pixels=0'),native.replace('alpha-exact=1','alpha-exact=0')):
            self.assertFalse(analyze([bad,*cases,first,last])['actual_direct_GPU_output'])
        for bad in (last.replace('direct=120','direct=0'),last.replace('n=120','n=1'),
                    last.replace('CPU-pixel-copy=0','CPU-pixel-copy=1'),last.replace('ABI=2','ABI=1')):
            self.assertFalse(analyze([native,*cases,first,bad])['actual_direct_GPU_output'])
        for bad in (cases[:3],cases+[cases[0]],[cases[0].replace('max=0','max=1'),*cases[1:]],
                    [cases[0],cases[1].replace('max=2','max=3'),*cases[2:]],
                    [cases[0],cases[1].replace('limit=2','limit=3'),*cases[2:]]):
            self.assertFalse(analyze([native,*bad,first,last])['actual_direct_GPU_output'])


if __name__=='__main__':unittest.main()
