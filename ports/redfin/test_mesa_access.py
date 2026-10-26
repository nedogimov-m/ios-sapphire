"""Execute actual Mesa resource intent and view/whole-backing merge contracts."""
import ctypes as C
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_gpu_scope import compile_host
from test_display_geometry import function

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


class MesaAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();root=Path(cls.temp.name)
        name='src/freedreno/drm/freedreno_ringbuffer_sp.c'
        base=ROOT/'research/redfin-metal-merge-v2/mesa-25.0.7'/name
        if not base.is_file():
            cls.temp.cleanup();raise unittest.SkipTest('actual native Mesa source preimage absent')
        path=root/name;path.parent.mkdir(parents=True);path.write_bytes(base.read_bytes())
        subprocess.run(['git','apply','--include='+name,str(HERE/'mesa-resource-access.patch')],
                       cwd=root,check=True,capture_output=True)
        text=path.read_text()
        methods=''.join(function(text,signature) for signature in (
            'static inline bool\ncheck_append_suballoc_bo(',
            'static inline uint32_t\ncheck_append_bo(',
            'uint32_t\nfd_submit_append_bo(',
            'uint32_t fd_submit_append_bo_backing(',
            'void fd_submit_redfin_resource_use('))
        source=(HERE/'mesa-access-host.cpp').read_text().replace('/* ACTUAL_APPEND_AND_RESOURCE_INTENT */',methods)
        cls.library=compile_host(root,'intent',source,True)
        cls.library.intent_contract.argtypes=[C.c_uint]

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_distinct_view_access_is_not_a_property_of_the_shared_heap(self):self.assertEqual(self.library.intent_contract(0),0)
    def test_repeated_view_reads_and_writes_are_unioned(self):self.assertEqual(self.library.intent_contract(1),0)
    def test_unknown_deferred_use_dominates_a_known_read(self):self.assertEqual(self.library.intent_contract(2),0)
    def test_unknown_target_use_dominates_a_known_deferred_read(self):self.assertEqual(self.library.intent_contract(3),0)
    def test_whole_backing_read_must_include_a_subview_write(self):self.assertEqual(self.library.intent_contract(4),0)
    def test_unknown_subview_dominates_a_known_whole_backing_read(self):self.assertEqual(self.library.intent_contract(5),0)
    def test_unknown_whole_backing_is_not_narrowed_by_a_known_view(self):self.assertEqual(self.library.intent_contract(6),0)
    def test_invalid_view_refuses_before_native_publication(self):self.assertEqual(self.library.intent_contract(7),0)


if __name__=='__main__':unittest.main()
