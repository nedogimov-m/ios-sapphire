"""Real manager/caller: enumeration policy, retained route and quiesce authority."""
import ctypes as C
import errno
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from ports.redfin.test_usb_owned_route import added_file
from ports.redfin import test_usb_bypass_context as bypass

HERE = Path(__file__).resolve().parent
GADGET = r'''
#include "redfin_usb_gadget.h"
static unsigned enum_calls,enum_fail,enum_phases[3];
static struct redfin_usb_gadget_policy enum_policy;
static const void *enum_caller;
int redfin_usb_gadget_start(const void *caller,const struct redfin_usb_gadget_policy *policy){
 enum_calls++;enum_policy=*policy;enum_caller=caller;
 if(!policy->authorize)return EINVAL;
 enum_phases[0]=policy->authorize(caller,policy->context,RF_USB_WARM);
 if(enum_phases[0])return (int)enum_phases[0];
 if(enum_fail)return EIO;
 /* Changes the real gadget owns: RUN_STOP/event ring, never SMMU state. */
 pages[1][0x704/4]=0x80000000u;pages[1][0x400/4]+=0x4000;pages[1][0x40c/4]=4;
 enum_phases[1]=policy->authorize(caller,policy->context,RF_USB_ACTIVE);
 enum_phases[2]=policy->authorize(caller,policy->context,RF_USB_QUIESCE);
 return enum_phases[1]?(int)enum_phases[1]:(int)enum_phases[2];
}
'''
WRAPPERS = r'''
void enum_reset(void){
 enum_calls=enum_fail=0;memset(enum_phases,0,sizeof(enum_phases));
 memset(&enum_policy,0,sizeof(enum_policy));enum_caller=NULL;
 __atomic_store_n(&redfin_initial_usb_gadget_owned,0,__ATOMIC_RELEASE);
}
void enum_fault(unsigned fault){enum_fail=fault;}
unsigned enum_stat(unsigned key){return key==0?enum_calls:key<4?enum_phases[key-1]:0;}
int enum_authorize(unsigned phase,unsigned variant){
 if(!enum_policy.authorize)return ENXIO;
 return enum_policy.authorize(variant==1?&other_token:enum_caller,
   variant==2?&other_token:enum_policy.context,(enum redfin_usb_gadget_phase)phase);
}
void enum_power(unsigned field,uint32_t value){
 const unsigned offsets[]={0x3004,0x3000,0x3010,0x307c,0x3080,0x3018,0x301c};
 if(field>=7){bad++;return;}pages[0][offsets[field]/4]=value;
}
void enum_bad_route(void){pages[2][(0xc00+4*rf_usb_owner.slot)/4]^=1;}
'''


class USBEnumerationStartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('cc')
        if not cc:
            raise unittest.SkipTest('host compiler unavailable')
        class Fixture(bypass.USBBypassContextTests):
            pass
        Fixture.setUpClass()
        cls.addClassCleanup(Fixture.doClassCleanups)
        template = (Path(Fixture.temp.name)/'True/model.c').read_text()
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        dev = root/'bsd/dev'
        dev.mkdir(parents=True)
        for name in ('redfin_usb_owned.c', 'redfin_usb_owned.h'):
            (dev/name).write_text(added_file((HERE/'usb-owned-route.patch').read_text(), 'bsd/dev/'+name))
        (dev/'redfin_usb_start.c').write_text(added_file((HERE/'usb-start.patch').read_text(), 'bsd/dev/redfin_usb_start.c'))
        gadget_header = added_file((HERE/'usb-gadget.patch').read_text(), 'bsd/dev/redfin_usb_gadget.h')
        (root/'redfin_usb_gadget.h').write_text(gadget_header)
        for patch in ('usb-owned-diag.patch', 'usb-context-probe.patch', 'usb-bypass-context.patch'):
            subprocess.run(['git','apply',str(HERE/patch)],cwd=root,check=True)
        old_c = (dev/'redfin_usb_owned.c').read_text()
        old_start = (dev/'redfin_usb_start.c').read_text()
        subprocess.run(['git','apply',str(HERE/'usb-enumeration-start.patch')],cwd=root,check=True)
        new_c = (dev/'redfin_usb_owned.c').read_text()
        new_start = (dev/'redfin_usb_start.c').read_text()
        assert template.count(bypass.host_owned(old_c)) == 1
        source = template.replace(bypass.host_owned(old_c), bypass.host_owned(new_c))
        old_start, new_start = [re.sub(r'^#include.*\n','',s,flags=re.M) for s in (old_start,new_start)]
        assert source.count(old_start) == 1
        source = source.replace(old_start, GADGET+'\n'+new_start)
        source = source.replace('{"redfinusbbypass",0,false}',
            '{"redfinusbbypass",0,false},{"redfinusbgadget",0,false},{"redfinusbsecs",0,false}')
        (root/'redfin_usb_owned.h').write_text((dev/'redfin_usb_owned.h').read_text())
        (root/'model.c').write_text(source+WRAPPERS)
        library = root/'model.so'
        subprocess.run([cc,'-std=c11','-shared','-fPIC','-Wall','-Wextra','-Werror',
                        str(root/'model.c'),'-o',str(library)],check=True)
        cls.lib = C.CDLL(str(library))
        cls.baseline = Fixture.fixed
        for lib in (cls.lib, cls.baseline):
            lib.host_arg.argtypes = [C.c_char_p,C.c_uint32,C.c_int]
            lib.host_page.restype = lib.host_context_page.restype = C.c_void_p
            lib.host_hash.restype = C.c_uint

    def reset(self, lib=None, gadget=1):
        lib = lib or self.lib
        lib.host_reset();lib.bypass_reset();lib.bypass_fixture()
        lib.host_arg(b'redfinusbcontexts',0,1);lib.host_arg(b'redfinusbbypass',1,1)
        if lib is self.lib:
            lib.enum_reset();lib.host_arg(b'redfinusbgadget',gadget,1)
        lib.bypass_seal()
        return lib

    def assert_no_gadget(self):
        self.assertEqual(self.lib.enum_stat(0),0)

    def test_explicit_start_warm_active_quiet_and_persistent_owner(self):
        lib = self.reset()
        self.assertEqual(lib.host_start(),0)
        self.assertEqual(lib.enum_stat(0),1)
        self.assertEqual([lib.enum_stat(i) for i in range(1,4)],[0,0,0])
        self.assertEqual(lib.bypass_stat(1),4)
        self.assertEqual(lib.host_start(),errno.EBUSY)
        self.assertEqual(lib.enum_stat(0),1)
        self.assertEqual(lib.enum_authorize(0,0),errno.EBUSY)   # Controller is now running.
        self.assertEqual(lib.enum_authorize(1,0),errno.EBUSY)   # Sticky quarantine.
        self.assertEqual(lib.enum_authorize(2,0),0)            # Still authorized to halt.

    def test_route_loss_revokes_active_but_preserves_halt_authority(self):
        lib = self.reset();self.assertEqual(lib.host_start(),0)
        lib.enum_bad_route()
        self.assertEqual(lib.enum_authorize(1,0),errno.EAGAIN)
        self.assertEqual(lib.enum_authorize(1,0),errno.EBUSY)
        self.assertEqual(lib.enum_authorize(2,0),0)
        self.assertEqual(lib.bypass_stat(1),4)

    def test_bank_loss_is_not_hidden_by_valid_stream(self):
        lib = self.reset();self.assertEqual(lib.host_start(),0)
        lib.host_context(4,0,1)
        self.assertEqual(lib.enum_authorize(1,0),errno.EAGAIN)
        self.assertEqual(lib.enum_authorize(2,0),0)
        self.assertEqual(lib.bypass_stat(1),4)

    def test_live_power_or_clock_loss_blocks_active_and_quiesce(self):
        for field,value in ((0,0),(0,0xffffffff),(1,1),(2,0),(3,0x80000001),(4,0),(5,0),(6,0)):
            with self.subTest(field=field,value=value):
                lib=self.reset();self.assertEqual(lib.host_start(),0)
                lib.enum_power(field,value)
                self.assertEqual(lib.enum_authorize(1,0),errno.EBUSY)
                self.assertEqual(lib.enum_authorize(2,0),errno.EBUSY)
                self.assertEqual(lib.bypass_stat(1),4)

    def test_phase_identity_and_software_ownership_loss_refuse_every_phase(self):
        lib=self.reset();self.assertEqual(lib.host_start(),0)
        for phase in range(3):
            for variant in (1,2):
                self.assertEqual(lib.enum_authorize(phase,variant),errno.EPERM)
        self.assertEqual(lib.enum_authorize(9,0),errno.EPERM)
        lib.host_arg(b'modem',1,1)
        for phase in range(3):
            self.assertEqual(lib.enum_authorize(phase,0),errno.EPERM)

    def test_selector_network_logging_and_duration_fail_before_manager(self):
        for key,value in (('redfinusbgadget',2),('redfinusbbypass',0),('redfinusbcontexts',1),
                          ('redfinusbnet',1),('redfinusblog',1),('redfinusbsecs',0),('redfinusbsecs',31)):
            with self.subTest(key=key,value=value):
                lib=self.reset();lib.host_arg(key.encode(),value,1)
                self.assertEqual(lib.host_start(),errno.ENOTSUP)
                self.assert_no_gadget();self.assertEqual(lib.bypass_stat(1),0)
        lib=self.reset();lib.host_arg(b'redfinusbsecs',30,1)
        self.assertEqual(lib.host_start(),0)

    def test_gadget_failure_retains_lease_and_cannot_retry(self):
        lib=self.reset();lib.enum_fault(1)
        self.assertEqual(lib.host_start(),errno.EIO)
        self.assertEqual(lib.host_start(),errno.EBUSY)
        self.assertEqual(lib.enum_stat(0),1);self.assertEqual(lib.bypass_stat(1),4)

    def test_route_faults_never_invoke_gadget(self):
        for step in range(1,5):
            for fault in (1,2,3):
                with self.subTest(step=step,fault=fault):
                    lib=self.reset();lib.bypass_inject(fault,step)
                    self.assertNotEqual(lib.host_start(),0)
                    self.assert_no_gadget()
        lib=self.reset();lib.bypass_drift(4)
        self.assertNotEqual(lib.host_start(),0);self.assert_no_gadget()

    def test_absent_or_zero_selector_preserves_existing_bypass_io(self):
        baseline=self.reset(self.baseline);self.assertEqual(baseline.host_start(),0)
        expected=[baseline.host_stat(i) for i in range(9)]
        hashes=[baseline.host_hash(i) for i in range(2)]
        for present in (0,1):
            lib=self.reset(gadget=0);lib.host_arg(b'redfinusbgadget',0,present)
            self.assertEqual(lib.host_start(),0)
            self.assertEqual([lib.host_stat(i) for i in range(9)],expected)
            self.assertEqual([lib.host_hash(i) for i in range(2)],hashes)
            self.assert_no_gadget()


if __name__=='__main__':
    unittest.main()
