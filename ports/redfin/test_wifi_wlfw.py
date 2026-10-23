"""Native legacy WLFW wire order, MSA bounds, indications and live handoff."""
import ctypes as C
import hashlib
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import warnings

import wifi_platform as P
import wifi_fw_blob as B
import wifi_rmtfs as R
from memory import _tree
from test_wifi_rmtfs import inventory, live_fdt, ARGS
from test_wifi_firmware import bundle, fdt
from test_loader import mock_kernel, mkadt
from test_fdt import Hardware
from tools import mkpayload

HERE = Path(__file__).resolve().parent
BASE = 0x8ba00000


def tlv(kind, data):
    return bytes([kind]) + struct.pack('<H', len(data)) + data


def response(message, transaction, extra=b'', *, result=0, error=0, indication=False):
    body = extra if indication else tlv(2, struct.pack('<HH', result, error)) + extra
    return struct.pack('<BHHH', 4 if indication else 2, transaction, message, len(body)) + body


def msa(regions):
    return tlv(3, bytes([len(regions)]) + b''.join(struct.pack('<QIB', *item) for item in regions))


def nodes():
    result, _ = _tree(live_fdt())
    result['/soc/qcom,icnss@18800000'] = {'compatible': b'qcom,icnss\0',
        'qcom,wlan-msa-fixed-region': struct.pack('>I', 0x9a)}
    result['/reserved-memory/pil_wlan_fw_region@8ba00000'] = {'compatible': b'removed-dma-pool\0',
        'no-map': b'', 'reg': struct.pack('>QQ', BASE, 0x200000), 'phandle': struct.pack('>I', 0x9a)}
    return result


def wlfw_fdt():
    selected = nodes()
    return fdt(extra=[('/soc/qcom,icnss@18800000', selected['/soc/qcom,icnss@18800000']),
        ('/reserved-memory/pil_wlan_fw_region@8ba00000', selected['/reserved-memory/pil_wlan_fw_region@8ba00000']),
        ('/soc/qcom,rmtfs_sharedmem@0', {'compatible': b'qcom,sharedmem-uio\0',
            'reg': struct.pack('>II', 0, 0x280000), 'reg-names': b'rmtfs\0', 'qcom,client-id': struct.pack('>I', 1)}),
        ('/psci', {'compatible': b'arm,psci-1.0\0', 'method': b'smc\0'})])


HARNESS = r'''
#include "wifi_qmi.h"
#include "wifi_wlfw.h"
static struct rf_wlfw_setup state;
static uint8_t sent[8][48];
static uint32_t lengths[8],sends,alive,fail_send;
static struct rf_wlfw_dynamic dynamic;
static uint8_t dynamic_packet[18];
static int check(void *p){return p==&state && alive ? 0 : -1;}
static int send(void *p,const uint8_t *data,uint32_t bytes){
 if(check(p)||fail_send||sends>=8||bytes>48)return -1;
 memcpy(sent[sends],data,bytes);lengths[sends++]=bytes;return 0;
}
static const struct rf_wlfw_ops ops={&state,check,send};
void reset(void){memset(&state,0,sizeof(state));memset(sent,0,sizeof(sent));sends=fail_send=0;alive=1;}
int begin(void){return rf_wlfw_begin(&state,&ops);}
int begin_features(unsigned value){return rf_wlfw_begin_features(&state,&ops,value);}
int receive(const uint8_t *data,uint32_t bytes){return rf_wlfw_receive(&state,&ops,data,bytes);}
uint8_t *packet(unsigned index){return index<8 ? sent[index] : NULL;}
uint32_t packet_bytes(unsigned index){return index<8 ? lengths[index] : 0;}
uint64_t metric(unsigned which){
 uint64_t values[]={state.stage,sends,state.registered,state.regions,state.msa_accepted,state.fw_ready,
 state.msa_ready_ind,state.ready_indications,state.pin_indications,state.result,state.error,state.poisoned,
 state.responses,state.ignored,state.already_registered,state.cap.chip,state.cap.family,state.cap.board,
 state.cap.soc,state.cap.firmware,state.cap.valid,state.rejuvenate,state.pin_valid,
 state.pin_value[0],state.pin_value[1],state.pin_value[2]};
 return which<sizeof(values)/sizeof(values[0]) ? values[which] : 0;
}
void fail(unsigned mode){if(mode==1)alive=0;if(mode==2)fail_send=1;}
int direct(unsigned stage){return rf_wlfw_send(&state,&ops,stage);}
uint8_t *dynamic_request(void){rf_wlfw_dynamic_request(dynamic_packet);return dynamic_packet;}
int dynamic_response(const uint8_t *data,uint32_t bytes){memset(&dynamic,0,sizeof(dynamic));return rf_wlfw_dynamic_parse(&dynamic,data,bytes);}
uint64_t dynamic_value(unsigned which){
 uint64_t values[]={dynamic.valid,dynamic.previous,dynamic.current,dynamic.result,dynamic.error};return which<5 ? values[which] : 0;
}
'''


class WlfwTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('cc'):
            raise unittest.SkipTest('host C compiler unavailable')
        cls.temporary = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        (cls.directory / 'test.c').write_text(HARNESS)
        library = cls.directory / 'test.so'
        result = subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
            '-I', str(HERE), str(cls.directory / 'test.c'), '-o', str(library)], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        cls.lib = C.CDLL(str(library)); cls.lib.receive.argtypes = [C.c_void_p, C.c_uint32]
        cls.lib.metric.restype = C.c_uint64; cls.lib.packet.restype = C.c_void_p
        cls.lib.dynamic_request.restype = C.c_void_p
        cls.lib.dynamic_response.argtypes = [C.c_void_p, C.c_uint32]
        cls.lib.dynamic_value.restype = C.c_uint64

    def setUp(self):
        self.lib.reset()

    def receive(self, data, code=0):
        self.assertEqual(self.lib.receive(data, len(data)), code)

    def packet(self, index):
        return C.string_at(self.lib.packet(index), self.lib.packet_bytes(index))

    def registered(self):
        self.assertEqual(self.lib.begin(), 0)
        self.receive(response(0x20, 1, tlv(0x10, bytes(8))))

    def msa_done(self):
        self.registered()
        self.receive(response(0x2d, 2, msa([(BASE, 0x100000, 1), (BASE + 0x100000, 0x100000, 0)])))
        self.receive(response(0x2e, 3))

    def test_register_msa_ready_cap_have_native_message_ids_and_exact_bytes(self):
        self.registered()
        expected = (tlv(0x10, b'\1') + tlv(0x13, b'\1') + tlv(0x14, b'\1') + tlv(0x15, struct.pack('<I', 0x4b4e454c)))
        self.assertEqual(self.packet(0), struct.pack('<BHHH', 0, 1, 0x20, len(expected)) + expected)
        expected = tlv(1, struct.pack('<Q', BASE)) + tlv(2, struct.pack('<I', 0x200000))
        self.assertEqual(self.packet(1), struct.pack('<BHHH', 0, 2, 0x2d, 18) + expected)
        self.receive(response(0x2d, 2, msa([(BASE, 0x200000, 0)])))
        self.assertEqual(self.packet(2), struct.pack('<BHHH', 0, 3, 0x2e, 0))
        self.receive(response(0x2e, 3))
        self.assertEqual(self.packet(3), struct.pack('<BHHH', 0, 4, 0x24, 0))
        cap = (tlv(0x10, struct.pack('<II', 0x123, 0x56)) + tlv(0x11, struct.pack('<I', 7)) +
               tlv(0x12, struct.pack('<I', 0x6200000)) + tlv(0x13, struct.pack('<I', 0xab)))
        self.receive(response(0x24, 4, cap))
        self.assertEqual([self.lib.metric(i) for i in (0, 1, 2, 4, 12, 15, 16, 17, 18, 19, 20)],
                         [5, 4, 1, 1, 4, 0x123, 0x56, 7, 0x6200000, 0xab, 15])
        self.assertEqual(self.lib.metric(5), 0)  # CAP success does not invent FW_READY.
        self.assertNotEqual(self.lib.begin(), 0)

    def test_early_and_interleaved_indications_do_not_skip_msa_handshake(self):
        self.registered()
        self.receive(response(0x21, 0, indication=True))
        self.receive(response(0x2b, 0, tlv(0x10, struct.pack('<I', 0x1ff000)) + tlv(0x11, struct.pack('<H', 4096)), indication=True))
        self.receive(response(0x2c, 0, tlv(0x10, struct.pack('<I', 3)), indication=True))
        self.assertEqual([self.lib.metric(i) for i in (0, 1, 5, 6, 7, 8)], [2, 2, 1, 1, 1, 1])
        self.receive(response(0x2d, 2, msa([])))  # Native fixed-memory response may have no regions.
        self.assertEqual(self.lib.metric(0), 3)

    def test_msa_regions_outside_reservation_overlapping_or_malformed_never_send_ready(self):
        cases = [[(BASE - 4096, 4096, 0)], [(BASE + 0x200000, 0, 0)], [(BASE, 0x200001, 0)],
                 [(0xfffffffffffff000, 4096, 0)], [(BASE, 4096, 2)],
                 [(BASE, 0x100000, 0), (BASE + 4096, 4096, 1)], [(BASE, 4096, 0)] * 3]
        for regions in cases:
            self.setUp(); self.registered()
            self.receive(response(0x2d, 2, msa(regions)), code=-1)
            self.assertEqual(self.lib.metric(1), 2); self.assertEqual(self.lib.metric(4), 0)
        for extra in (b'', tlv(3, b'\1'), msa([]) + msa([])):
            self.setUp(); self.registered(); self.receive(response(0x2d, 2, extra), code=-1)
            self.assertEqual(self.lib.metric(1), 2)

    def test_qmi_failures_and_already_registered_flag_are_reported_without_fabricated_success(self):
        self.assertEqual(self.lib.begin(), 0)
        self.receive(response(0x20, 1, result=1, error=90))
        self.assertEqual([self.lib.metric(i) for i in (0, 1, 9, 10)], [6, 1, 1, 90])
        self.setUp(); self.assertEqual(self.lib.begin(), 0)
        self.receive(response(0x20, 1, tlv(0x10, struct.pack('<Q', 1))))
        self.assertEqual([self.lib.metric(i) for i in (0, 1, 9, 10, 14)], [6, 1, 0, 0, 1])
        self.setUp(); self.registered(); self.receive(response(0x2d, 2, result=1, error=90))
        self.assertEqual(self.lib.metric(0), 6); self.assertEqual(self.lib.metric(1), 2)

    def test_foreign_transactions_duplicates_and_bad_results_do_not_advance(self):
        self.registered()
        for data in (response(0x20, 1), response(0x2d, 99, msa([])), response(0x24, 2)):
            self.receive(data, code=1)
        self.assertEqual(self.lib.metric(1), 2)
        self.receive(response(0x2d, 2, msa([]), result=2), code=-1)
        self.receive(response(0x2d, 2, msa([]), error=1), code=-1)
        self.assertEqual(self.lib.metric(0), 2)

    def test_owner_and_send_failures_stop_protocol_before_later_messages(self):
        self.lib.fail(1); self.assertNotEqual(self.lib.begin(), 0); self.assertEqual(self.lib.metric(1), 0)
        self.setUp(); self.assertEqual(self.lib.begin(), 0); self.lib.fail(2)
        self.receive(response(0x20, 1), code=-1)
        self.assertEqual(self.lib.metric(11), 1); self.assertEqual(self.lib.metric(1), 1)
        self.setUp()
        for stage in (1, 2, 3, 4):
            self.assertNotEqual(self.lib.direct(stage), 0)
        self.assertEqual(self.lib.metric(1), 0)

    def test_indication_hang_bounds_and_duplicate_tlvs_are_checked(self):
        self.registered()
        self.receive(response(0x2b, 0, tlv(0x10, struct.pack('<I', 0x200000)) + tlv(0x11, b'\1\0'), indication=True), code=-1)
        self.receive(response(0x21, 0, tlv(0x10, b'\1'), indication=True), code=-1)
        self.receive(response(0x2b, 0, tlv(0x10, bytes(4)) * 2, indication=True), code=-1)
        self.assertEqual(self.lib.metric(6), 0); self.assertEqual(self.lib.metric(5), 0)

    def test_native_power_profile_registers_rejuvenation_and_quarantines_that_epoch(self):
        self.assertEqual(self.lib.begin_features(1), 0)
        self.assertEqual(self.packet(0)[-7:], tlv(0x19, struct.pack('<I', 1)))
        self.assertEqual(len(self.packet(0)), 33)
        self.receive(response(0x39, 0, tlv(0x10, b'\1'), indication=True), code=-1)
        self.assertEqual([self.lib.metric(i) for i in (0, 1, 11, 21)], [6, 1, 1, 1])
        self.assertNotEqual(self.lib.begin(), 0)
        self.setUp(); self.assertNotEqual(self.lib.begin_features(2), 0); self.assertEqual(self.lib.metric(1), 0)

    def test_pin_results_preserve_native_values_and_presence(self):
        self.registered()
        self.receive(response(0x2c, 0, tlv(0x10, struct.pack('<I', 7)) + tlv(0x11, struct.pack('<I', 5)) +
                              tlv(0x12, struct.pack('<I', 11)), indication=True))
        self.assertEqual([self.lib.metric(i) for i in (22, 23, 24, 25)], [7, 7, 5, 11])

    def test_dynamic_feature_request_and_reply_match_native_u64_mask_contract(self):
        packet = C.string_at(self.lib.dynamic_request(), 18)
        self.assertEqual(packet, struct.pack('<BHHH', 0, 5, 0x3b, 11) + tlv(0x10, struct.pack('<Q', 1)))
        data = response(0x3b, 5, tlv(0x10, bytes(8)) + tlv(0x11, struct.pack('<Q', 1)))
        self.assertEqual(self.lib.dynamic_response(data, len(data)), 0)
        self.assertEqual([self.lib.dynamic_value(i) for i in range(5)], [3, 0, 1, 0, 0])
        data = response(0x3b, 5, result=1, error=0x5e)
        self.assertEqual(self.lib.dynamic_response(data, len(data)), 0)
        self.assertEqual([self.lib.dynamic_value(i) for i in (3, 4)], [1, 0x5e])
        for data in (response(0x3b, 4), response(0x3a, 5), response(0x3b, 5, tlv(0x10, b'\1')),
                     response(0x3b, 5, tlv(0x11, bytes(8)) * 2)):
            self.assertNotEqual(self.lib.dynamic_response(data, len(data)), 0)

    def test_live_contract_refuses_hyp_change_foreign_region_and_duplicate_reference(self):
        tree = mkadt.build(0x180000000, 0x80000000)
        P.add_wlfw_contract(tree, nodes())
        entry = next(n for n in tree.children if n.name == 'redfin-wifi-wlfw')
        self.assertEqual(entry.prop('reg'), struct.pack('<QQ', BASE, 0x200000))
        for change in ('hyp', 'region', 'reference', 'duplicate', 'disabled'):
            source = nodes()
            if change == 'hyp': source['/soc/qcom,icnss@18800000']['qcom,hyp_enabled'] = b''
            if change == 'region': source['/reserved-memory/pil_wlan_fw_region@8ba00000']['reg'] = struct.pack('>QQ', BASE, 0x300000)
            if change == 'reference': source['/soc/qcom,icnss@18800000']['qcom,wlan-msa-fixed-region'] = bytes(4)
            if change == 'duplicate': source['/duplicate'] = {'phandle': struct.pack('>I', 0x9a)}
            if change == 'disabled': source['/soc/qcom,icnss@18800000']['status'] = b'disabled\0'
            with self.assertRaises(ValueError):
                P.add_wlfw_contract(mkadt.build(0x180000000, 0x80000000), source)

    def test_actual_loader_requires_live_fixed_msa_reservation_and_unset_marker(self):
        directory = self.directory
        report_path = inventory(directory)
        live = wlfw_fdt()
        rmtfs = R.pack(report_path, live, 0x180000000, 0x80000000)
        root = mkadt.build(0x180000000, 0x80000000); P.add_wlfw_contract(root, _tree(live)[0])
        kernel, adt_path = directory / 'kernel', directory / 'tree'
        kernel.write_bytes(mock_kernel()); adt_path.write_bytes(mkadt.adt.serialize(root))
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', ResourceWarning)
            payload, _ = mkpayload.build(kernel, adt_path, ARGS)
        firmware = bundle(); digest = hashlib.sha256(firmware).hexdigest()
        native = {'schema': 1, 'bundle_bytes': len(firmware), 'bundle_sha256': digest, 'assets': 3,
                  'memory_bytes': 0x11800000, 'hardware_started': False, 'signature_authenticated': False}
        auxiliary = (b'a' * 64, {'schema': 1, 'bytes': 64, 'sha256': hashlib.sha256(b'a' * 64).hexdigest()})
        packed, _ = B.pack(payload, firmware, digest, native, 0x8000000, start=True, transport=True,
            probe_exclusions=[(0x180000000, 0x80000000), (0xa0000000, 0x2300000)], auxiliary=auxiliary, rmtfs=rmtfs)
        (directory / 'config.h').write_text('#define XNU_PAYLOAD_SIZE 65536\n')
        library = directory / 'loader.so'
        subprocess.run(['cc', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC', '-DREDFIN_LOADER_TEST',
            '-I', str(directory), str(HERE / 'loader.c'), str(HERE / 'fdt.c'), '-o', str(library)], check=True, capture_output=True)
        loader = C.CDLL(str(library)); loader.redfin_fdt.argtypes = [C.c_void_p, C.POINTER(Hardware)]
        loader.redfin_validate.argtypes = [C.c_void_p, C.c_uint64, C.c_uint64, C.c_uint64, C.c_uint64,
                                          C.POINTER(Hardware), C.c_uint64]
        loader.redfin_validate.restype = C.c_char_p
        device = C.create_string_buffer(live); hardware = Hardware()
        self.assertEqual(loader.redfin_fdt(device, C.byref(hardware)), 0)

        def accepted(data):
            storage = C.create_string_buffer(len(data) + 16384); address = (C.addressof(storage) + 16383) & -16384
            C.memmove(address, bytes(data), len(data))
            return loader.redfin_validate(address, len(data), address, address + len(data), C.addressof(device), C.byref(hardware), 0)

        self.assertIsNone(accepted(packed))
        marker = b'shim-verified'.ljust(32, b'\0') + struct.pack('<I', 4)
        at = packed.index(marker) + len(marker)
        damaged = bytearray(packed); struct.pack_into('<I', damaged, at, 1)
        self.assertEqual(accepted(damaged), b'RMTFS RAM ownership')
        for index in range(hardware.reservations):
            if hardware.reserved[index].base == BASE and hardware.reserved[index].size == 0x200000:
                hardware.reserved[index].base += 0x400000
        self.assertEqual(accepted(packed), b'RMTFS RAM ownership')


if __name__ == '__main__':
    unittest.main()
