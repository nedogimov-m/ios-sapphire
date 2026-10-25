"""Run the actual command binding cache with an ownership-counting receiver."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent

class MetalBindingTests(unittest.TestCase):
    def test_real_binding_cache_clears_stale_slots_and_preserves_native_ownership(self):
        mesa=ROOT/'research/redfin-metal-ordering-v1/mesa-25.0.7'
        build=mesa.parent/'build-freedreno'
        self.assertTrue((mesa/'src/gallium/include/pipe/p_state.h').is_file(),'verified Mesa headers required')
        with tempfile.TemporaryDirectory() as directory:
            binary=Path(directory)/'bindings'
            command=['cc','-std=gnu11','-O2','-Wall','-Wextra','-Werror',
                '-I'+str(HERE),'-I'+str(mesa/'include'),'-I'+str(mesa/'src'),
                '-I'+str(mesa/'src/gallium/include'),'-I'+str(build),'-I'+str(build/'src'),
                str(HERE/'metal-bindings-host.c'),'-o',str(binary)]
            compiled=subprocess.run(command,capture_output=True)
            self.assertEqual(compiled.returncode,0,compiled.stderr.decode(errors='replace'))
            ran=subprocess.run([str(binary)],capture_output=True,timeout=10)
            self.assertEqual(ran.returncode,0,ran.stderr.decode(errors='replace'))
            self.assertIn(b'error lifetime PASS',ran.stdout)

if __name__=='__main__':unittest.main()
