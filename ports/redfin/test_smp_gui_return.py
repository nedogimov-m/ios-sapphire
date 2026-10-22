"""GUI8 reuses the actual read-only proof without changing the UP return latch."""
import ctypes as C
from pathlib import Path

import test_smp_return as base
import test_smp_eight_return as eight
from test_smp_gui import ARGS, patched_source

HERE = Path(__file__).resolve().parent


class GUIReturnTests(eight.EightReturnTests):
    @classmethod
    def setUpClass(cls):
        source = patched_source('bsd/dev/redfin_spmi.c')
        actual = source[source.index('/* REDFIN_SMP_RETURN_BEGIN'):source.index('/* Redfin physical-PMIC evidence')]
        actual = '#include "' + str(HERE / 'gui-profile.h') + '"\n' + actual
        actual += '''
void gui_reset(void){published=0;memset(&redfin_spmi_proof,0,sizeof(redfin_spmi_proof));}
int gui_publish(unsigned verified){published=verified;return redfin_gui_publish_return();}
uint64_t gui_proof(unsigned n){
 const uint64_t v[]={redfin_spmi_proof.ready,redfin_spmi_proof.core,redfin_spmi_proof.observer,
 redfin_spmi_proof.config,redfin_spmi_proof.version,redfin_spmi_proof.apid,
 redfin_spmi_proof.owner,redfin_spmi_proof.subtype};return n<8?v[n]:0;
}
'''
        old_backend, old_prefix = eight.backend, base.PREFIX
        try:
            eight.backend = lambda: actual
            base.PREFIX += '''
static unsigned published;
int redfin_smp_verified(void){return published;}
static struct {bool ready;uintptr_t core,observer,config;uint32_t version;unsigned apid,owner;uint8_t subtype;} redfin_spmi_proof;
'''
            eight.EightReturnTests.setUpClass.__func__(cls)
        finally:
            eight.backend, base.PREFIX = old_backend, old_prefix
        cls.lib.gui_publish.argtypes = cls.lib.gui_proof.argtypes = [C.c_uint]
        cls.lib.gui_proof.restype = C.c_uint64

    def setUp(self):
        self.lib.reset(ARGS.encode())
        self.lib.gui_reset()

    def test_gui_publication_requires_actual_proof_and_completed_smp(self):
        self.assertEqual(self.lib.gui_publish(1), 0)
        self.assertEqual(self.lib.gui_proof(0), 0)
        self.assertEqual(self.lib.redfin_smp_return_ready(), 1)
        self.assertEqual(self.lib.gui_publish(0), 0)
        self.assertEqual(self.lib.gui_proof(0), 0)
        counters = [self.lib.stat(i) for i in range(17)]
        self.assertEqual(self.lib.gui_publish(1), 1)
        self.assertEqual([self.lib.stat(i) for i in range(17)], counters)
        self.assertEqual([self.lib.gui_proof(i) for i in range(4)], [1, 0x1000, 0x2000, 0x3000])
        self.assertEqual(self.lib.gui_proof(6), 0)
        self.assertEqual(self.lib.gui_proof(7), 4)
        self.assertEqual(self.lib.stat(11), 0)
        self.assertEqual(self.lib.stat(12), 0)

    def test_secondary_and_changed_args_cannot_publish_or_poison_cpu0_cache(self):
        self.assertEqual(self.lib.redfin_smp_return_ready(), 1)
        self.lib.set(7, 0x600)
        self.assertEqual(self.lib.gui_publish(1), 0)
        self.assertEqual(self.lib.stat(13), 3)
        self.lib.set(7, 0)
        self.assertEqual(self.lib.gui_publish(1), 1)
        self.lib.change_args(ARGS.replace('redfinshutdown=180', 'redfinshutdown=120').encode())
        self.assertEqual(self.lib.gui_publish(1), 0)


if __name__ == '__main__':
    import unittest
    unittest.main()
