"""Fault injection at the actual native reset-held firmware-copy boundary."""
from pathlib import Path
import subprocess
import tempfile
import unittest


class NativeCopyWindowTests(unittest.TestCase):
    def test_native_guard_keeps_mutable_ownership_and_rechecks_static_contract_before_auth(self):
        # Compile the actual native guard with controlled mappings/clock/owner.
        # This verifies the important distinction: unrelated immutable tuples
        # can be checked outside the RAM-copy loop, but live ownership, mapping,
        # reset and timeout changes must still retire it immediately.
        code=(Path(__file__).parent/'wifi_fw_start.inc').read_text()
        first=code.index('static int fw_start_check(void *opaque)\n{')
        last=code.index('\n}\n',first)+3
        guard=code[first:last]
        source=r'''
#include <stdint.h>
#include <errno.h>
#include <assert.h>
#include <string.h>
enum {FW_START_COPY=9,FW_START_AUTH=10,FW_START_TCSR=1,FW_START_MAPS=2};
#define RF_WIFI_SMP2P_LOCK_OFFSET 0
struct object {uintptr_t base;uint64_t length;
 uintptr_t getVirtualAddress() const{return base;}
 uint64_t getLength() const{return length;}
};
struct fw_start_map {object *map;void *memory;uintptr_t base;};
struct health {bool poisoned;};
struct fw_start_context {
 bool active,poisoned,copy_window,power,initialized,setup,reset,auth_attempted,authenticated,locked;
 uint64_t copy_window_started_ns;unsigned phase;
 unsigned transport_mode,host_mode,rmtfs_mode,wlfw_mode,wlan_observe_mode,snoc_mode,mission_mode,packets_mode;
 health rmtfs,wlfw_setup,mission,packet_lease;fw_start_map mapping[FW_START_MAPS];
};
static fw_start_context fw_start;
static struct {uint64_t nonce;} fw_probe={1};
static bool owner_ok=true,contract_ok=true,interrupts=true;
static unsigned static_checks,owner_checks;
static uint64_t now_ns=1;
static uint64_t region[2]={0x1000,64};
static bool ml_get_interrupts_enabled(){return interrupts;}
static int fw_probe_check(void *,uint64_t){++owner_checks;return owner_ok?0:1;}
static uint64_t fw_start_ns(void *){return now_ns;}
static int redfin_wifi_power_held(){return contract_ok?0:1;}
static bool tuple(){++static_checks;return contract_ok;}
static bool fw_start_metadata_contract(void *,bool){return tuple();}
static bool fw_start_glink_contract(){return tuple();}
static bool fw_start_assets_contract(void *,bool){return tuple();}
static bool fw_start_rmtfs_contract(void *,bool){return tuple();}
static bool fw_start_wlfw_contract(){return tuple();}
static bool fw_start_wlan_contract(){return tuple();}
static bool fw_start_snoc_contract(){return tuple();}
static bool fw_start_packet_contract(void *,bool){return tuple();}
static const uint64_t *fw_start_region(void *,unsigned){return region;}
'''+guard+r'''
static uint32_t ram[16];static object mapping={(uintptr_t)ram,64};
static void fresh() {
 memset(&fw_start,0,sizeof(fw_start));
 fw_start.active=fw_start.power=fw_start.initialized=fw_start.setup=fw_start.reset=true;
 fw_start.phase=FW_START_COPY;fw_start.copy_window_started_ns=1;
 fw_start.mapping[0]={&mapping,&mapping,(uintptr_t)ram};
 owner_ok=contract_ok=interrupts=true;now_ns=1;static_checks=owner_checks=0;
 mapping.base=(uintptr_t)ram;mapping.length=64;
}
int main() {
 fresh();assert(!fw_start_check(&fw_start));assert(static_checks);
 fw_start.copy_window=true;unsigned full=static_checks;
 for(unsigned i=0;i<512;++i)assert(!fw_start_check(&fw_start));
 assert(static_checks==full && owner_checks>=513);
 contract_ok=false;
 assert(!fw_start_check(&fw_start)); /* still only our reset-held reserved RAM */
 fw_start.copy_window=false;
 assert(fw_start_check(&fw_start)==ECANCELED && fw_start.poisoned);
 fw_start.phase=FW_START_AUTH;
 assert(fw_start_check(&fw_start)==ECANCELED); /* no AUTH with changed DT tuple */
 for(unsigned fault=0;fault<9;++fault) {
  fresh();fw_start.copy_window=true;
  switch(fault) {
   case 0:owner_ok=false;break;
   case 1:fw_start.reset=false;break;
   case 2:fw_start.auth_attempted=true;break;
   case 3:fw_start.phase=FW_START_AUTH;break;
   case 4:mapping.length=63;break;
   case 5:mapping.base++;break;
   case 6:now_ns=UINT64_C(30000000002);break;
   case 7:fw_start.locked=true;break;
   case 8:interrupts=false;break;
  }
  assert(fw_start_check(&fw_start)==ECANCELED && fw_start.poisoned);
 }
 assert(fw_start_check(nullptr)==ECANCELED);return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'guard.cpp').write_text(source)
            compiled=subprocess.run(['c++','-std=c++17','-O2','-Wall','-Wextra','-Werror',
                root/'guard.cpp','-o',root/'guard'],capture_output=True)
            self.assertEqual(compiled.returncode,0,compiled.stderr.decode(errors='replace'))
            subprocess.run([root/'guard'],check=True,capture_output=True,timeout=10)


if __name__=='__main__':
    unittest.main()
