"""Read native VRM metadata without writes; bind actual ICNSS voltage inputs."""
import ctypes as C
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

import wifi_platform as P
from test_rpmh_probe import added_file
from test_wifi_wlfw import nodes, tlv, response
from test_loader import mkadt

HERE = Path(__file__).resolve().parent
NAMES = ('ldoa1', 'ldoa14', 'ldoc2', 'ldoc11', 'ldoc10')
CHILDREN = ('regulator-pm8150-l1', 'regulator-pm8150-l14', 'regulator-pm8150a-l2',
            'regulator-pm8150a-l11', 'regulator-pm8150a-l10')
SUPPLIES = ('vdd-cx-mx', 'vdd-1.8-xo', 'vdd-1.3-rfa', 'vdd-3.3-ch1', 'vdd-3.3-ch0')
BOUNDS = ((352000, 952000, 352000), (1616000, 1984000, 1616000), (1144000, 1328000, 1144000),
          (3000000, 3312000, 3000000), (3000000, 3312000, 3000000))


def database():
    data = bytearray(0x20000)
    struct.pack_into('<II', data, 0, 1, 0x0c0330db)
    struct.pack_into('<5H', data, 8, 4, 0, 0x200, 5, 0x1000)
    for index, name in enumerate(NAMES):
        at = 144 + 24 * index
        data[at:at + 8] = name.encode().ljust(8, b'\0')
        struct.pack_into('<IIIHH', data, at + 8, index + 1, index + 2, 0x40000 + index * 0x100, 0, 0)
    return data


def source_nodes():
    result = nodes(); icnss = result['/soc/qcom,icnss@18800000']
    for index, name in enumerate(NAMES):
        parent = '/soc/rsc@18200000/rpmh-regulator-' + name
        result[parent] = {'compatible': b'qcom,rpmh-vrm-regulator\0', 'qcom,resource-name': name.encode() + b'\0',
                          'qcom,regulator-type': b'pmic5-ldo\0'}
        reference = struct.pack('>I', 0xd0 + index)
        result[parent + '/' + CHILDREN[index]] = {'phandle': reference, 'qcom,set': struct.pack('>I', 3),
            'qcom,init-mode': struct.pack('>I', 2), **{key: struct.pack('>I', value) for key, value in zip(
                ('regulator-min-microvolt', 'regulator-max-microvolt', 'qcom,init-voltage'), BOUNDS[index])}}
        icnss[SUPPLIES[index] + '-supply'] = reference
        if index == 0: icnss['qcom,' + SUPPLIES[index] + '-config'] = bytes(8)
        elif index >= 3: icnss['qcom,' + SUPPLIES[index] + '-config'] = struct.pack('>II', 3000000, 3312000)
    return result


HARNESS = r'''
#include <string.h>
#include "redfin_rpmh.h"
#include "wifi_wlan.h"
#include "wifi_qmi.h"
static struct rf_wlan_resources resources;
static struct rf_wlfw_cap cap;
static struct rf_wlan_plan plan;
int observe(const uint8_t *data){memset(&resources,0,sizeof(resources));return rf_wlan_resources_read(data,&resources);}
uint32_t value(unsigned index,unsigned which){
 if(index>=5)return 0;const struct rf_cmddb_resource *r=&resources.supply[index];
 return which==0 ? r->address : which==1 ? r->aux_version : which==2 ? r->aux_bytes : r->priority[which==3 ? 0 : 1];
}
int capability(const uint8_t *data,uint32_t bytes){memset(&cap,0,sizeof(cap));return rf_wlfw_cap_parse(&cap,data,bytes,4);}
uint32_t cap_value(unsigned which){return which==0 ? cap.valid : cap.chain;}
int power_plan(const uint8_t *data,unsigned present,uint32_t chain){
 memset(&resources,0,sizeof(resources));memset(&plan,0,sizeof(plan));
 if(rf_wlan_resources_read(data,&resources))return -1;return rf_wlan_power_plan(&resources,present,chain,&plan);
}
uint32_t plan_value(unsigned index,unsigned which){
 if(which==0)return plan.votes;if(which==1)return plan.chain1;if(index>=plan.votes)return 0;
 return which==2 ? plan.vote[index].address : plan.vote[index].value;
}
'''


class WlanMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('cc'):
            raise unittest.SkipTest('host C compiler unavailable')
        cls.temporary = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        (directory / 'redfin_rpmh.h').write_text(added_file('redfin_rpmh.h'))
        (directory / 'test.c').write_text(HARNESS)
        library = directory / 'test.so'
        result = subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
            '-I', str(HERE), '-I', str(directory), str(directory / 'test.c'), '-o', str(library)],
            capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        cls.lib = C.CDLL(str(library)); cls.lib.observe.argtypes = [C.c_void_p]
        cls.lib.value.restype = C.c_uint32
        cls.lib.cap_value.restype = C.c_uint32
        cls.lib.capability.argtypes = [C.c_void_p, C.c_uint32]
        cls.lib.power_plan.argtypes = [C.c_void_p, C.c_uint, C.c_uint32]
        cls.lib.plan_value.restype = C.c_uint32

    def test_native_resource_reader_preserves_bytes_and_returns_five_distinct_vrm_addresses(self):
        data = bytes(database()); memory = C.create_string_buffer(data)
        self.assertEqual(self.lib.observe(memory), 0)
        self.assertEqual(C.string_at(memory, len(data)), data)
        self.assertEqual([self.lib.value(i, 0) for i in range(5)], [0x40000 + i * 0x100 for i in range(5)])

    def test_missing_wrong_type_aliased_or_unaligned_resources_never_produce_a_plan(self):
        for case in ('missing', 'type', 'alias', 'unaligned', 'header'):
            data = database()
            if case == 'missing': data[144] ^= 1
            if case == 'type': struct.pack_into('<I', data, 144 + 16, 0x30000)
            if case == 'alias': struct.pack_into('<I', data, 144 + 24 + 16, 0x40004)
            if case == 'unaligned': struct.pack_into('<I', data, 144 + 16, 0x40001)
            if case == 'header': data[0] = 0
            self.assertNotEqual(self.lib.observe(bytes(data)), 0)
            self.assertEqual(self.lib.value(0, 0), 0)

    def test_chain_capability_is_explicit_optional_metadata_with_checked_length_and_duplicates(self):
        for chain in (0, 1, 2, 0xffffffff):
            data = response(0x24, 4, tlv(0x1b, struct.pack('<I', chain)))
            self.assertEqual(self.lib.capability(data, len(data)), 0)
            self.assertEqual(self.lib.cap_value(0), 16); self.assertEqual(self.lib.cap_value(1), chain)
        for extra in (tlv(0x1b, b'\1'), tlv(0x1b, bytes(4)) * 2):
            data = response(0x24, 4, extra)
            self.assertNotEqual(self.lib.capability(data, len(data)), 0)

    def tree(self, source):
        root = mkadt.build(0x180000000, 0x80000000)
        P.add_wlfw_contract(root, source)
        return root

    def test_producer_binds_native_overrides_instead_of_icnss_default_voltages(self):
        source = source_nodes(); root = self.tree(source)
        P.add_wlan_observer_contract(root, source)
        node = next(n for n in root.children if n.name == 'redfin-wifi-wlan')
        self.assertEqual(struct.unpack('<10I', node.prop('source-contract')), (1, 5, 4, 4, 0, 352, 1800, 1304, 3000, 3000))
        self.assertEqual(node.prop('observe-only'), struct.pack('<I', 1))

    def test_changed_provider_voltage_consumer_reference_clock_or_load_is_rejected(self):
        parent = '/soc/rsc@18200000/rpmh-regulator-ldoa1'
        child = parent + '/' + CHILDREN[0]
        for case in ('type', 'voltage', 'duplicate', 'clock', 'override', 'disabled'):
            source = source_nodes()
            if case == 'type': source[parent]['qcom,regulator-type'] = b'pmic4-ldo\0'
            if case == 'voltage': source[child]['qcom,init-voltage'] = struct.pack('>I', 752000)
            if case == 'duplicate': source['/duplicate'] = {'phandle': struct.pack('>I', 0xd0)}
            if case == 'clock': source['/soc/qcom,icnss@18800000']['clocks'] = bytes(8)
            if case == 'override': source['/soc/qcom,icnss@18800000']['qcom,vdd-cx-mx-config'] = struct.pack('>II', 752000, 752000)
            if case == 'disabled': source[parent]['status'] = b'disabled\0'
            with self.assertRaises(ValueError):
                P.add_wlan_observer_contract(self.tree(source), source)

    def test_power_plan_uses_observed_resources_native_voltages_modes_and_chain_policy(self):
        data = database()
        addresses = [0x40800, 0x42100, 0x41d00, 0x41a00, 0x41900]
        for index, address in enumerate(addresses):
            struct.pack_into('<IIIHH', data, 144 + 24 * index + 8, 0, 0, address, 4, 4 * index)
        struct.pack_into('<H', data, 16, 0x100)
        self.assertEqual(self.lib.power_plan(bytes(data), 0, 0), 0)
        expected = [(0x40800, 352), (0x40808, 4), (0x40804, 1),
                    (0x42100, 1800), (0x42108, 4), (0x42104, 1),
                    (0x41d00, 1304), (0x41d08, 4), (0x41d04, 1),
                    (0x41a00, 3000), (0x41a08, 4), (0x41a04, 1),
                    (0x41900, 3000), (0x41908, 4), (0x41904, 1)]
        self.assertEqual(self.lib.plan_value(0, 0), 15)
        self.assertEqual([(self.lib.plan_value(i, 2), self.lib.plan_value(i, 3)) for i in range(15)], expected)
        self.assertEqual(self.lib.power_plan(bytes(data), 1, 1), 0)
        self.assertEqual(self.lib.plan_value(0, 0), 12); self.assertEqual(self.lib.plan_value(0, 1), 0)
        self.assertFalse(any(self.lib.plan_value(i, 2) in (0x41a00, 0x41a04, 0x41a08) for i in range(12)))
        self.assertNotEqual(self.lib.power_plan(bytes(data), 1, 3), 0)
        struct.pack_into('<I', data, 144 + 16, 0x40900)
        self.assertNotEqual(self.lib.power_plan(bytes(data), 0, 0), 0)
        self.assertEqual(self.lib.plan_value(0, 0), 0)

    def test_power_contract_requires_an_explicit_profile_and_pins_observed_addresses(self):
        source = source_nodes(); root = self.tree(source)
        P.add_wlan_observer_contract(root, source, power=True)
        node = next(n for n in root.children if n.name == 'redfin-wifi-wlan')
        self.assertEqual(struct.unpack('<I', node.prop('source-contract')[:4])[0], 2)
        self.assertEqual(node.prop('observe-only'), bytes(4))
        self.assertEqual(struct.unpack('<5I', node.prop('resource-addresses')), (0x40800, 0x42100, 0x41d00, 0x41a00, 0x41900))


if __name__ == '__main__':
    unittest.main()
