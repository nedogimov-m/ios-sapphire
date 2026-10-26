import unittest
from ports.redfin.direct_output_evidence import analyze


class DirectOutputEvidenceTests(unittest.TestCase):
    def test_actual_pixel_check_and_monotonic_direct_presents_are_both_required(self):
        native='REDFIN GPU DIRECT CHECK: ABI=1 cases=4 pixels=10108800 mismatches=0 guard-errors=0 stage-writes=0 completed=1 tolerance=1'
        first='REDFIN GPU DIRECT PRESENT: n=1 direct=1 staged=0 ABI=1 full-image-only=1 CPU-pixel-copy=0'
        last='REDFIN GPU DIRECT PRESENT: n=120 direct=120 staged=0 ABI=1 full-image-only=1 CPU-pixel-copy=0'
        self.assertTrue(analyze([native,first,last])['actual_direct_GPU_output'])
        self.assertFalse(analyze([native])['actual_direct_GPU_output'])
        self.assertFalse(analyze([first,last])['actual_direct_GPU_output'])
        for bad in (native.replace('cases=4','cases=1'),native.replace('mismatches=0','mismatches=1'),
                    native.replace('stage-writes=0','stage-writes=1'),native.replace('tolerance=1','tolerance=255')):
            self.assertFalse(analyze([bad,first,last])['actual_direct_GPU_output'])
        for bad in (last.replace('direct=120','direct=0'),last.replace('n=120','n=1'),
                    last.replace('CPU-pixel-copy=0','CPU-pixel-copy=1'),last.replace('ABI=1','ABI=2')):
            self.assertFalse(analyze([native,first,bad])['actual_direct_GPU_output'])


if __name__=='__main__':unittest.main()
