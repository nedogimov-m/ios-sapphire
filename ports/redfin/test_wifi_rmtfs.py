"""Actual RMTFS bytes, volatile writes, low RAM ownership and SCM arguments."""
import ctypes as C
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import warnings

import wifi_rmtfs as R
import wifi_fw_blob as B
from test_wifi_firmware import SHA, sha256, fdt, bundle
from test_loader import mock_kernel, mkadt
from test_fdt import Hardware
from tools import mkpayload

HERE = Path(__file__).resolve().parent
PHYSICAL = 0xff000000
ARGS = ('debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 '
        'sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 redfinwifi=2 redfinwifinative=1 '
        'redfinwififw=4 redfinspmi=1 redfinreturn=1 redfinbootid=0x0000000000000001')


def live_fdt(changes=None):
    native = {'compatible': b'qcom,sharedmem-uio\0', 'reg': struct.pack('>II', 0, 0x280000),
              'reg-names': b'rmtfs\0', 'qcom,client-id': struct.pack('>I', 1)}
    return fdt(changes=changes, extra=[('/soc/qcom,rmtfs_sharedmem@0', native),
        ('/psci', {'compatible': b'arm,psci-1.0\0', 'method': b'smc\0'})])


def inventory(directory):
    files = []
    for index, (path, label) in enumerate(R.FILES):
        data = bytes((i * 17 + index) % 256 for i in range(4096 * (index + 1)))
        (directory / (label + '.img')).write_bytes(data)
        files.append({'path': path, 'partition': label, 'private_file': label + '.img', 'bytes': len(data),
                      'sha256': hashlib.sha256(data).hexdigest(), 'independent_reads_match': True,
                      'gpt': {'block_size': 4096}})
    report = {'schema': 1, 'status': 'verified-read-only-rmtfs-snapshot', 'device': 'redfin',
              'source': 'verified-offline-recovery', 'disk_writes': False, 'left_in_bootloader': True, 'files': files}
    path = directory / 'inventory.json'; path.write_text(json.dumps(report))
    return path


HARNESS = r'''
#include <stdbool.h>
#include "wifi_firmware.h"
#include "wifi_rmtfs.h"
#include "redfin_scm_query.h"
#include "wifi_hyp.h"
static struct rf_rmtfs state;
static uint8_t shadow[40960], pool[RF_RM_SHARED+32], output[32], scratch[16384];
static unsigned alive,sends,output_bytes,barriers,fail_send,fail_barrier;
static int check(void *p){return p==&state && alive ? 0 : -1;}
static int barrier(void *p){++barriers;return check(p)||fail_barrier ? -1 : 0;}
static int send(void *p,uint32_t node,uint32_t port,const uint8_t *data,uint32_t bytes){
 (void)node;(void)port;if(check(p)||bytes>sizeof(output)||fail_send)return -1;
 ++sends;output_bytes=bytes;memcpy(output,data,bytes);return 0;
}
static void event(void *p,unsigned m,unsigned c,unsigned b,unsigned e){(void)p;(void)m;(void)c;(void)b;(void)e;}
static const struct rf_rm_ops ops={&state,check,barrier,send,event};
int reset(const uint8_t *data,size_t bytes,const uint8_t *digest,redfin_mpss_sha256_fn hash){
 memset(&state,0,sizeof(state));memset(pool,0xa7,sizeof(pool));memset(shadow,0x33,sizeof(shadow));
 alive=1;sends=output_bytes=barriers=fail_send=fail_barrier=0;
 if(rf_rm_image_open(&state,data,bytes,digest,hash,NULL))return -1;
 if(rf_rm_shadow_open(&state,shadow,sizeof(shadow)))return -2;
 return rf_rm_bind(&state,pool+16,0xff000000,RF_RM_SHARED);
}
int request(uint32_t node,uint32_t port,const uint8_t *data,uint32_t bytes){
 return rf_rm_request(&state,&ops,node,port,data,bytes);
}
uint8_t *buffer(unsigned which){return which==0 ? output : which==1 ? pool+16 : shadow;}
uint64_t metric(unsigned which){
 uint64_t values[]={sends,output_bytes,barriers,state.requests,state.opens,state.allocations,state.reads,state.writes,
 state.failures,state.poisoned};return which<10 ? values[which] : 0;
}
int guards(void){for(unsigned i=0;i<16;++i)if(pool[i]!=0xa7||pool[RF_RM_SHARED+16+i]!=0xa7)return -1;return 0;}
void fail(unsigned which){if(which==0)alive=0;if(which==1)fail_send=1;if(which==2)fail_barrier=1;}
static struct rf_sq_report report;
static struct rf_sq_regs first;
static unsigned mode,calls,unsafe;
static uint64_t clock_ns;
static bool valid(void *p){return p==&report && alive;}
static uint64_t now(void *p){(void)p;return clock_ns;}
static void delay(void *p,unsigned us){(void)p;clock_ns+=(uint64_t)us*1000;}
static int invoke(void *p,struct rf_sq_regs *r){
 if(p!=&report||!alive)return -91;++calls;
 if(calls==1)first=*r;
 else if(mode==3){if(r->x[0]!=1||r->x[6]!=66||r->x[1]!=61)++unsafe;}
 else if(memcmp(r,&first,sizeof(first)))++unsafe;
 if(mode==4|| (mode==5&&calls==1)){r->x[0]=(uint64_t)-12;return 0;}
 if(mode==3&&calls==1){r->x[0]=1;for(unsigned i=1;i<7;++i)r->x[i]=60+i;return 0;}
 if(mode==6)alive=0;if(mode==7)clock_ns+=3000000000ULL;
 r->x[0]=mode==1 ? (uint64_t)-5 : 0;r->x[1]=mode==2 ? 9 : 0;return 0;
}
int hyp(unsigned choice,uint64_t physical){
 mode=choice;calls=unsafe=0;alive=1;clock_ns=0;
 const struct rf_sq_ops ops={&report,valid,invoke,delay,now};
 return rf_rm_hyp_run(&ops,physical,&report);
}
int prepare(uint64_t physical,uint64_t shared){return rf_rm_hyp_prepare(scratch,physical,shared);}
uint8_t *arguments(void){return scratch;}
uint64_t hyp_metric(unsigned which){
 if(which==0)return calls;if(which==1)return unsafe;if(which==2)return report.completed;
 if(which==3)return report.resumes;return which>=8&&which<16 ? first.x[which-8] : 0;
}
'''


class RmtfsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('cc'):
            raise unittest.SkipTest('host C compiler unavailable')
        cls.temporary = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        cls.manifest = inventory(cls.directory)
        cls.blob, cls.proof = R.pack(cls.manifest, live_fdt(), 0x180000000, 0x80000000)
        (cls.directory / 'test.c').write_text(HARNESS)
        library = cls.directory / 'test.so'
        result = subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
            '-I', str(HERE), '-I', str(HERE / 'include'), str(cls.directory / 'test.c'), '-o', str(library)],
            capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        cls.lib = C.CDLL(str(library)); cls.lib.reset.argtypes = [C.c_void_p, C.c_size_t, C.c_void_p, SHA]
        cls.lib.request.argtypes = [C.c_uint32, C.c_uint32, C.c_void_p, C.c_uint32]
        cls.lib.buffer.restype = cls.lib.arguments.restype = C.c_void_p
        cls.lib.metric.restype = cls.lib.hyp_metric.restype = C.c_uint64
        cls.lib.hyp.argtypes = [C.c_uint, C.c_uint64]
        cls.lib.prepare.argtypes = [C.c_uint64, C.c_uint64]

    def setUp(self):
        self.storage = C.create_string_buffer(self.blob)
        self.assertEqual(self.lib.reset(self.storage, len(self.blob), hashlib.sha256(self.blob).digest(), sha256), 0)

    def qmi(self, message, fields, node=0, port=7):
        body = b''.join(bytes([kind]) + struct.pack('<H', len(data)) + data for kind, data in fields)
        packet = struct.pack('<BHHH', 0, 37, message, len(body)) + body
        self.assertEqual(self.lib.request(node, port, packet, len(packet)), 0)
        output = C.string_at(self.lib.buffer(0), self.lib.metric(1))
        self.assertEqual(struct.unpack_from('<BHHH', output), (2, 37, message, len(output) - 7))
        return output

    def opened(self, size=0x280000):
        response = self.qmi(1, [(1, b'/boot/modem_fs1')]); self.assertEqual(response[10:14], bytes(4))
        caller, = struct.unpack_from('<I', response, 17); self.assertEqual(caller, 1)
        response = self.qmi(4, [(1, struct.pack('<I', caller)), (2, struct.pack('<I', size))])
        self.assertEqual(struct.unpack_from('<Q', response, 17)[0], PHYSICAL)
        return caller

    def io(self, direction, entries, caller=1, node=0, port=7):
        return self.qmi(3, [(1, struct.pack('<I', caller)), (2, bytes([direction])),
            (3, bytes([len(entries)]) + b''.join(struct.pack('<III', *entry) for entry in entries)), (4, b'\1')], node, port)

    def test_read_write_roundtrip_changes_only_volatile_shadow(self):
        self.opened()
        self.assertEqual(self.io(0, [(2, PHYSICAL + 512, 2)])[10:14], bytes(4))
        expected = self.blob[576 + 1024:576 + 2048]
        self.assertEqual(C.string_at(self.lib.buffer(1) + 512, 1024), expected)
        data = bytes([0x61]) * 512
        C.memmove(self.lib.buffer(1) + 512, data, 512)
        self.assertEqual(self.io(1, [(2, PHYSICAL + 512, 1)])[10:14], bytes(4))
        self.assertEqual(C.string_at(self.lib.buffer(2) + 1024, 512), data)
        self.assertEqual(C.string_at(self.storage, len(self.blob)), self.blob)
        self.assertEqual(self.lib.metric(6), 2); self.assertEqual(self.lib.metric(7), 1)
        self.assertEqual(self.lib.guards(), 0)

    def test_whole_iovec_is_checked_before_any_transfer(self):
        self.opened()
        before = C.string_at(self.lib.buffer(1), R.SHARED_BYTES)
        for entry in [(0, PHYSICAL - 512, 1), (7, PHYSICAL, 2), (0xffffffff, PHYSICAL, 1),
                      (0, 0xfffffe00, 2), (0, PHYSICAL, 0), (0, PHYSICAL + 1, 1)]:
            response = self.io(0, [(0, PHYSICAL, 1), entry])
            self.assertEqual(response[10:14], b'\1\0\1\0')
            self.assertEqual(C.string_at(self.lib.buffer(1), R.SHARED_BYTES), before)
        self.assertEqual(self.lib.metric(6), 0); self.assertEqual(self.lib.guards(), 0)

    def test_caller_node_port_and_allocated_length_are_enforced(self):
        self.opened(512)
        for kwargs in ({'caller': 0}, {'caller': 99}, {'node': 2}, {'port': 8}):
            self.assertNotEqual(self.io(0, [(0, PHYSICAL, 1)], **kwargs)[10:14], bytes(4))
        self.assertNotEqual(self.io(0, [(0, PHYSICAL, 2)])[10:14], bytes(4))
        self.assertEqual(self.lib.metric(6), 0)

    def test_close_reopen_keeps_ram_changes_without_reopening_storage(self):
        self.opened(); C.memset(self.lib.buffer(1), 0xab, 512)
        self.io(1, [(0, PHYSICAL, 1)])
        self.qmi(2, [(1, struct.pack('<I', 1))])
        self.opened(); self.io(0, [(0, PHYSICAL + 512, 1)])
        self.assertEqual(C.string_at(self.lib.buffer(1) + 512, 512), b'\xab' * 512)
        self.assertEqual(C.string_at(self.storage, len(self.blob)), self.blob)

    def test_malformed_unknown_paths_and_duplicate_tlvs_grant_nothing(self):
        for fields in ([], [(1, b'/boot/../persist')], [(1, b'/boot/modem_fs1\0')],
                       [(1, b'/boot/modem_fs1'), (1, b'/boot/modem_fs1')]):
            response = self.qmi(1, fields)
            self.assertEqual(len(response), 14); self.assertNotEqual(response[10:14], bytes(4))
        self.assertEqual(self.lib.metric(4), 0); self.assertEqual(self.lib.metric(5), 0)

    def test_owner_or_barrier_loss_stops_before_copy_and_send_failure_poisons(self):
        for fail in range(3):
            self.setUp(); self.opened(); before = C.string_at(self.lib.buffer(1), 512)
            self.lib.fail(fail)
            fields = b'\1\4\0\1\0\0\0\2\1\0\0\3\15\0\1' + struct.pack('<III', 0, PHYSICAL, 1) + b'\4\1\0\1'
            packet = struct.pack('<BHHH', 0, 1, 3, len(fields)) + fields
            self.assertNotEqual(self.lib.request(0, 7, packet, len(packet)), 0)
            self.assertEqual(self.lib.metric(9), 1)
            if fail != 1:
                self.assertEqual(C.string_at(self.lib.buffer(1), 512), before)
            self.assertEqual(self.lib.guards(), 0)

    def test_snapshot_parser_rejects_corruption_and_rehashed_wrong_extents(self):
        for offset in (0, 20, 64, 128, 144, 576):
            damaged = bytearray(self.blob); damaged[offset] ^= 1
            self.assertNotEqual(self.lib.reset(bytes(damaged), len(damaged), hashlib.sha256(damaged).digest(), sha256), 0)

    def test_hyp_has_exact_native_two_destination_layout_and_64bit_extra_args(self):
        scratch = 0x181000000
        self.assertEqual(self.lib.prepare(scratch, PHYSICAL), 0)
        data = C.string_at(self.lib.arguments(), 16384)
        self.assertEqual(struct.unpack_from('<QQ', data), (PHYSICAL, R.SHARED_BYTES))
        self.assertEqual(struct.unpack_from('<I', data, 0x40)[0], 3)
        self.assertEqual(struct.unpack_from('<IIQII', data, 0x80), (3, 6, 0, 0, 0))
        self.assertEqual(struct.unpack_from('<IIQII', data, 0x98), (15, 6, 0, 0, 0))
        self.assertEqual(struct.unpack_from('<7Q', data, 0x100), (4, scratch + 0x80, 48, 0, 0, 0, 0))
        self.assertEqual(self.lib.hyp(0, scratch), 0)
        self.assertEqual([self.lib.hyp_metric(i) for i in range(8, 16)],
                         [0x42000c16, 0x1117, scratch, 16, scratch + 0x40, scratch + 0x100, 0, 0])

    def test_hyp_retries_continuations_and_errors_are_bounded(self):
        for mode, success, calls in ((1, False, 1), (2, False, 1), (3, True, 2), (4, False, 4),
                                     (5, True, 2), (6, False, 1), (7, False, 1)):
            self.assertEqual(self.lib.hyp(mode, 0x181000000) == 0, success)
            self.assertEqual(self.lib.hyp_metric(0), calls); self.assertEqual(self.lib.hyp_metric(1), 0)
        for physical in (0, 0x181000001, 0x200000000):
            self.assertNotEqual(self.lib.hyp(0, physical), 0); self.assertEqual(self.lib.hyp_metric(0), 0)

    def test_allocator_skips_all_fixed_reservations_and_does_not_invent_a_missing_bank(self):
        changes = {'/memory': {'reg': struct.pack('>4Q', 0xc0000000, 0x40000000, 0x180000000, 0x100000000)}}
        allocation = R.reserve_low(live_fdt(changes), 0x180000000, 0x80000000)
        self.assertEqual(allocation['pool'][0] + allocation['pool'][1], 1 << 32)
        changes['/reserved-memory/ramoops'] = {'reg': struct.pack('>QQ', 0xffc00000, 0x400000)}
        self.assertLessEqual(sum(R.reserve_low(live_fdt(changes), 0x180000000, 0x80000000)['pool']), 0xffc00000)
        changes['/memory']['reg'] = struct.pack('>QQ', 0x180000000, 0x100000000)
        with self.assertRaises(ValueError):
            R.reserve_low(live_fdt(changes), 0x180000000, 0x80000000)

    def test_producer_rejects_changed_snapshot_hash_and_missing_read_proof(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name); manifest = inventory(directory)
            report = json.loads(manifest.read_text()); report['files'][0]['independent_reads_match'] = False
            manifest.write_text(json.dumps(report))
            with self.assertRaises(ValueError):
                R.pack(manifest, live_fdt(), 0x180000000, 0x80000000)
            inventory(directory); (directory / 'modemst1.img').write_bytes(bytes(4096))
            with self.assertRaises(ValueError):
                R.pack(manifest, live_fdt(), 0x180000000, 0x80000000)

    def test_real_packer_and_loader_require_unclaimed_pool_and_zero_scratch(self):
        directory = self.directory
        kernel, tree_path = directory / 'kernel', directory / 'tree'
        kernel.write_bytes(mock_kernel()); tree_path.write_bytes(mkadt.adt.serialize(mkadt.build(0x180000000, 0x80000000)))
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', ResourceWarning)
            payload, _ = mkpayload.build(kernel, tree_path, ARGS)
        firmware = bundle(); digest = hashlib.sha256(firmware).hexdigest()
        native = {'schema': 1, 'bundle_bytes': len(firmware), 'bundle_sha256': digest, 'assets': 3,
                  'memory_bytes': 0x11800000, 'hardware_started': False, 'signature_authenticated': False}
        auxiliary = (b'a' * 64, {'schema': 1, 'bytes': 64, 'sha256': hashlib.sha256(b'a' * 64).hexdigest()})
        packed, _ = B.pack(payload, firmware, digest, native, 0x8000000, start=True, transport=True,
            probe_exclusions=[(0x180000000, 0x80000000), (0xa0000000, 0x2300000)],
            auxiliary=auxiliary, rmtfs=(self.blob, self.proof))
        (directory / 'config.h').write_text('#define XNU_PAYLOAD_SIZE 65536\n')
        library = directory / 'loader.so'
        subprocess.run(['cc', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC', '-DREDFIN_LOADER_TEST',
            '-I', str(directory), str(HERE / 'loader.c'), str(HERE / 'fdt.c'), '-o', str(library)], check=True, capture_output=True)
        loader = C.CDLL(str(library)); loader.redfin_fdt.argtypes = [C.c_void_p, C.POINTER(Hardware)]
        loader.redfin_validate.argtypes = [C.c_void_p, C.c_uint64, C.c_uint64, C.c_uint64, C.c_uint64,
                                          C.POINTER(Hardware), C.c_uint64]
        loader.redfin_validate.restype = C.c_char_p
        device = C.create_string_buffer(live_fdt()); hardware = Hardware()
        self.assertEqual(loader.redfin_fdt(device, C.byref(hardware)), 0)

        def accepted(data, hw=hardware):
            storage = C.create_string_buffer(len(data) + 16384); address = (C.addressof(storage) + 16383) & -16384
            C.memmove(address, bytes(data), len(data))
            return loader.redfin_validate(address, len(data), address, address + len(data), C.addressof(device), C.byref(hw), 0)

        self.assertIsNone(accepted(packed))
        offset, size = struct.unpack_from('<QQ', packed, 32)
        root, _ = mkadt.adt.parse(packed[offset:offset + size]); node = next(n for n in root.children if n.name == 'redfin-rmtfs')
        self.assertEqual(node.prop('shim-owned'), bytes(4))
        damaged = bytearray(packed)
        marker = b'shim-owned'.ljust(32, b'\0') + struct.pack('<I', 4)
        at = packed.index(marker, offset) + len(marker); struct.pack_into('<I', damaged, at, 1)
        self.assertEqual(accepted(damaged), b'RMTFS RAM ownership')
        scratch = struct.unpack('<QQ', node.prop('scratch-reg'))
        count, = struct.unpack_from('<I', packed, 12)
        for i in range(count):
            address, _, source, _ = struct.unpack_from('<4Q', packed, 680 + 32 * i)
            if address - struct.unpack_from('<Q', packed, 16)[0] + 0x180000000 == scratch[0]:
                damaged = bytearray(packed); damaged[source] = 1
                self.assertEqual(accepted(damaged), b'RMTFS RAM ownership')
        hardware.reserved[hardware.reservations].base = self.proof['pool'][0]
        hardware.reserved[hardware.reservations].size = 16384; hardware.reservations += 1
        self.assertEqual(accepted(packed), b'RMTFS RAM ownership')


if __name__ == '__main__':
    unittest.main()
