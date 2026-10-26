"""Actual immutable-snapshot/row-copy code with deferred ownership receivers."""
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


class MetalConstantSnapshotTests(unittest.TestCase):
    def test_actual_snapshots_bounds_fallback_order_rollover_and_failed_scope_drain(self):
        mesa=ROOT/'research/redfin-metal-ubo-extent-v1/mesa-25.0.7'
        build=mesa.parent/'build-freedreno'
        self.assertTrue((mesa/'src/gallium/include/pipe/p_state.h').is_file())
        with tempfile.TemporaryDirectory(prefix='redfin-constant-snapshot-') as directory:
            directory=Path(directory)
            blit=(HERE/'metal-blit.inc').read_text()
            first=blit.index('static int\nrwa_blit_rows(')
            last=blit.index('\nint\nrwa_redfin_blit(',first)
            (directory/'actual-rows.inc').write_text(blit[first:last])
            profile=(HERE/'metal-frontend-profile.inc').read_text()
            first=profile.index('static int rwa_redfin_profile_constant_snapshot(')
            last=profile.index('\nstatic void rwa_redfin_profile_submit_clear(',first)
            (directory/'actual-snapshot.inc').write_text(profile[first:last])
            binary=directory/'contract'
            command=['cc','-std=gnu11','-O2','-Wall','-Wextra','-Werror',
                     '-I'+str(directory),'-I'+str(HERE),'-I'+str(mesa/'include'),
                     '-I'+str(mesa/'src'),'-I'+str(mesa/'src/gallium/include'),
                     '-I'+str(build),'-I'+str(build/'src'),
                     str(HERE/'metal-constant-snapshot-host.c'),'-o',str(binary)]
            compiled=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(compiled.returncode,0,compiled.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('actual immutable snapshots: bounds/fallback/order/rollover/error/lifetime PASS',result.stdout)


if __name__=='__main__':unittest.main()
