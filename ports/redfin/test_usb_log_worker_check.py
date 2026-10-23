"""Inject log-worker creation failure into the real guarded gadget startup."""
import errno
from pathlib import Path
import subprocess
import unittest
from unittest import mock

from ports.redfin import test_usb_gadget as gadget

HERE = Path(__file__).resolve().parent


class USBLogWorkerCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base_source = gadget.patched_source

        def patched_source(directory):
            base_source(directory)
            for name in ('usb-network-worker.patch', 'usb-log-worker-check.patch'):
                subprocess.run(['git', 'apply', '--include=bsd/dev/sweet_usb.c', str(HERE / name)],
                               cwd=directory, check=True, capture_output=True)
            return (directory / 'bsd/dev/sweet_usb.c').read_text()

        stub = gadget.STUB.replace('unsigned events;bool configured;',
                                   'unsigned events;bool configured,network_stopped;')
        stub = stub.replace('if(issue==12)return 1;',
                            'if(issue==12 || ((issue==27 || issue==28) && body==ud_log_thread))return 1;')
        stub = stub.replace('quiesce_calls++;return issue==3 ? EPERM : 0;',
                            'quiesce_calls++;return issue==3 || issue==28 ? EPERM : 0;')
        # Existing runtime queue cleanup has its own actual-handler tests. Here
        # model its sticky stop while executing the real new startup/outer halt.
        stub += r'''
static unsigned retained_dma_frees;
static __attribute__((unused)) void kmem_free(void *map,uintptr_t address,size_t size){
 (void)map;(void)address;(void)size;retained_dma_frees++;
}
static void ud_redfin_network_stop(void){ud.network_stopped=true;ud.configured=false;}
unsigned retained_state(unsigned key){
 const unsigned values[]={ud.dma!=0,ud.dma_pa==physical,ud.guard.active,
  ud.guard.caller==&token,ud.guard.policy.context==&context_token,
  attempted,retained_dma_frees,ud.network_stopped,ud.guard.error};
 return key<sizeof(values)/sizeof(values[0]) ? values[key] : 0;
}
int retry_start(void){
 const struct redfin_usb_gadget_policy policy={authorize,&context_token};
 return redfin_usb_gadget_start(&token,&policy);
}
'''
        # The inherited fixture compiles real proof, DMA setup, startup and
        # redfin_usb_gadget_start; replace only fake kernel/MMIO services.
        harness = gadget.HARNESS + r'''
unsigned legacy_log_failure(void){
 (void)run(4,2,30,1,1);ud.guard.redfin=false;issue=27;
 ud.dwc=(uintptr_t)core_regs-0xc000;
 sweet_usb_gadget_start(ud.dwc);return (unsigned)ud.guard.error;
}
'''
        with mock.patch.object(gadget, 'patched_source', patched_source), \
                mock.patch.object(gadget, 'STUB', stub), mock.patch.object(gadget, 'HARNESS', harness):
            gadget.USBGadgetTests.setUpClass.__func__(cls)

    def test_log_thread_failure_is_reported_and_owned_core_is_quiesced(self):
        self.assertEqual(self.lib.run(27,3,30,1,1),errno.EIO)
        self.assertEqual(self.lib.stat(5),2)  # event worker started before failed logger
        self.assertEqual(self.lib.stat(7),0)
        self.assertGreater(self.lib.stat(12),0)
        self.assertEqual(self.lib.stat(20),1)  # existing owned halt succeeded
        self.assertEqual([self.lib.retained_state(i) for i in range(8)], [1,1,1,1,1,1,0,1])
        maps=self.lib.stat(0)
        self.assertEqual(self.lib.retry_start(),errno.EBUSY)
        self.assertEqual(self.lib.stat(0),maps)
        self.assertEqual(self.lib.stat(9),0)

    def test_failed_quiesce_keeps_active_dma_and_owner_until_reset(self):
        self.assertEqual(self.lib.run(28,3,30,1,1),errno.EIO)
        self.assertEqual(self.lib.stat(20),0)  # no halt claim after denied proof
        self.assertEqual([self.lib.retained_state(i) for i in range(8)], [1,1,1,1,1,1,0,1])
        self.assertEqual(self.lib.retained_state(8),errno.EIO)
        self.assertEqual(self.lib.stat(9),0)

    def test_success_or_no_logger_keeps_existing_bounded_worker_behavior(self):
        for network,log,threads,logs in ((1,1,2,1),(1,0,1,0),(0,1,1,0)):
            with self.subTest(network=network,log=log):
                self.assertEqual(self.lib.run(0,3,1,network,log),errno.ETIMEDOUT)
                self.assertEqual(self.lib.stat(5),threads)
                self.assertEqual(self.lib.stat(7),logs)
                self.assertEqual(self.lib.retained_state(6),0)
                self.assertEqual(self.lib.stat(9),0)

    def test_legacy_logger_failure_remains_optional(self):
        self.assertEqual(self.lib.legacy_log_failure(),0)
        self.assertEqual(self.lib.stat(5),2)
        self.assertEqual(self.lib.stat(7),0)
        self.assertEqual(self.lib.stat(12),0)
        self.assertEqual(self.lib.retained_state(6),0)
        self.assertEqual(self.lib.stat(9),0)


if __name__ == '__main__':
    unittest.main()
