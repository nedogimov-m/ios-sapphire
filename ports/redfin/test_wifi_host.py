"""Exercise captured asset hashes, actual QMI TLVs, and bounded RAM TFTP."""
import ctypes as C
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

import wifi_assets
from test_wifi_firmware import SHA, sha256

HERE = Path(__file__).resolve().parent
HARNESS = r'''
#include <string.h>
#include "wifi_firmware.h"
#include "wifi_assets.h"
#include "wifi_host.h"
#include "wifi_qmi.h"
static struct rf_host host;
static struct rf_wlan_assets assets;
static struct rf_wlfw_cap cap;
static uint8_t file[9000],output[RF_HOST_BLOCK+512];
static unsigned alive,sends,output_bytes,output_from,output_to,lookups,events;
static int check(void *p){return p==&host && alive ? 0 : -1;}
static int lookup(void *p,const char *name,const uint8_t **data,uint32_t *bytes){
 if(check(p))return -1;++lookups;if(strcmp(name,"image/wlanmdsp.mbn"))return -1;
 *data=file;*bytes=sizeof(file);return 0;
}
static int send(void *p,uint32_t from,uint32_t node,uint32_t to,const uint8_t *data,uint32_t bytes){
 if(check(p)||node!=0||bytes>sizeof(output))return -1;
 ++sends;output_bytes=bytes;output_from=from;output_to=to;memcpy(output,data,bytes);return 0;
}
static void event(void *p,unsigned kind,const char *name,uint32_t size){(void)p;(void)kind;(void)name;(void)size;++events;}
static const struct rf_host_ops ops={&host,check,lookup,send,event};
void reset(void){memset(&host,0,sizeof(host));memset(&assets,0,sizeof(assets));memset(&cap,0,sizeof(cap));
 alive=1;sends=output_bytes=output_from=output_to=lookups=events=0;
 for(unsigned i=0;i<sizeof(file);++i)file[i]=(uint8_t)(i*17u+3u);
}
void owner(unsigned value){alive=value;}
int receive(uint32_t to,uint32_t node,uint32_t from,const uint8_t *data,uint32_t bytes){
 if(to==0x4001)return rf_host_pd(&host,&ops,node,from,data,bytes);
 if(to==0x4002)return rf_host_tftp_request(&host,&ops,node,from,data,bytes);
 return rf_host_tftp_packet(&host,&ops,node,from,to,data,bytes);
}
uint8_t *response(void){return output;}
uint64_t metric(unsigned which){
 uint64_t values[]={sends,output_bytes,output_from,output_to,lookups,events,host.requests,host.reads,host.writes,
 host.missing,host.pd_requests,host.ram[0].bytes,host.poisoned};
 return which<sizeof(values)/sizeof(values[0]) ? values[which] : 0;
}
int parse_assets(const uint8_t *data,size_t bytes,const uint8_t expected[32],redfin_mpss_sha256_fn hash){
 return rf_wlan_assets_open(&assets,data,bytes,expected,hash,NULL);
}
unsigned asset_count(void){return assets.count;}
int parse_cap(const uint8_t *data,uint32_t bytes){return rf_wlfw_cap_parse(&cap,data,bytes,1);}
uint32_t cap_field(unsigned which){
 uint32_t values[]={cap.valid,cap.chip,cap.family,cap.board,cap.soc,cap.firmware,cap.result,cap.error};
 return which<8 ? values[which] : 0;
}
'''


class NativeWifiHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('host C compiler unavailable')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        (directory / 'host.c').write_text(HARNESS)
        result = subprocess.run([compiler, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                                 '-I', str(HERE), str(directory / 'host.c'), '-o', str(directory / 'host.so')],
                                capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        cls.library = C.CDLL(str(directory / 'host.so'))
        cls.library.receive.argtypes = [C.c_uint32, C.c_uint32, C.c_uint32, C.c_void_p, C.c_uint32]
        cls.library.response.restype = C.c_void_p
        cls.library.metric.restype = C.c_uint64
        cls.library.parse_assets.argtypes = [C.c_void_p, C.c_size_t, C.c_void_p, SHA]
        cls.library.parse_cap.argtypes = [C.c_void_p, C.c_uint32]

    def setUp(self):
        self.library.reset()

    def receive(self, data, to=0x4002, node=0, source=90):
        return self.library.receive(to, node, source, data, len(data))

    def output(self):
        return C.string_at(self.library.response(), self.library.metric(1))

    @staticmethod
    def request(command, path, *options):
        return struct.pack('>H', command) + b'\0'.join([path.encode(), b'octet', *[str(part).encode() for part in options]]) + b'\0'

    def test_tftp_read_negotiates_bounded_blocks_and_retransmits_without_skipping_bytes(self):
        request = self.request(1, '/readonly/firmware/image/wlanmdsp.mbn', 'blksize', 16384, 'wsize', 4, 'tsize', 0)
        self.assertEqual(self.receive(request), 0)
        self.assertTrue(self.output().startswith(b'\0\x06'))
        self.assertIn(b'blksize\x004096\0', self.output())
        self.assertIn(b'wsize\x001\0', self.output())
        self.assertIn(b'tsize\x009000\0', self.output())
        port = self.library.metric(2)
        received = bytearray()
        for ack in range(3):
            self.assertEqual(self.receive(struct.pack('>HH', 4, ack), to=port), 0)
            block = self.output()
            self.assertEqual(struct.unpack_from('>HH', block), (3, ack + 1))
            received.extend(block[4:])
            if ack == 1:
                self.assertEqual(self.receive(struct.pack('>HH', 4, ack), to=port), 0)
                self.assertEqual(self.output(), block)
        self.assertEqual(received, bytes((i * 17 + 3) % 256 for i in range(9000)))
        sends = self.library.metric(0)
        self.assertEqual(self.receive(struct.pack('>HH', 4, 3), to=port), 0)
        self.assertEqual(self.library.metric(0), sends)

    def test_tftp_stat_reports_full_file_size_and_does_not_read_a_zero_length_file(self):
        self.assertEqual(self.receive(self.request(1, '/readonly/firmware/image/wlanmdsp.mbn',
                                                  'tsize', 0, 'rsize', 0)), 0)
        self.assertIn(b'tsize\x009000\0', self.output())
        self.assertEqual(self.receive(struct.pack('>HH', 5, 9), to=self.library.metric(2)), 0)
        self.assertEqual(self.library.metric(7), 0)

    def test_readwrite_files_stay_in_bounded_ram_and_foreign_ports_cannot_modify_them(self):
        self.assertEqual(self.receive(self.request(2, '/readwrite/wlan/config')), 0)
        port = self.library.metric(2)
        self.assertEqual(self.output(), struct.pack('>HH', 4, 0))
        data = struct.pack('>HH', 3, 1) + b'ephemeral'
        self.assertNotEqual(self.receive(data, to=port, source=91), 0)
        self.assertEqual(self.library.metric(11), 0)
        self.assertEqual(self.receive(data, to=port), 0)
        self.assertEqual(self.receive(data, to=port), 0)
        self.assertEqual(self.library.metric(11), 9)
        self.assertEqual(self.receive(self.request(1, '/readwrite/wlan/config'), source=92), 0)
        self.assertEqual(self.output()[4:], b'ephemeral')
        self.assertEqual(self.library.metric(4), 0, 'RAM files cannot call the firmware lookup backend')

    def test_writes_to_readonly_assets_and_paths_outside_the_virtual_roots_are_refused(self):
        self.assertEqual(self.receive(self.request(2, '/readonly/firmware/image/wlanmdsp.mbn')), 0)
        self.assertEqual(struct.unpack_from('>HH', self.output()), (5, 2))
        for path in ('/readonly/firmware/image/../secret', '/readwrite/../efs', '/readwrite//file'):
            with self.subTest(path=path):
                self.assertNotEqual(self.receive(self.request(1, path)), 0)
        self.assertEqual(self.library.metric(4), 0)
        self.assertEqual(self.library.metric(8), 0)

    def test_malformed_requests_and_overflowing_options_do_not_reach_firmware_lookup(self):
        for data in (b'\0\1unterminated', self.request(1, '/readonly/firmware/image/wlanmdsp.mbn')[:-1],
                     self.request(1, '/readonly/firmware/image/wlanmdsp.mbn', 'blksize', '99999999999')):
            self.setUp()
            self.receive(data)
            self.assertEqual(self.library.metric(4), 0)
        self.setUp()
        self.library.owner(0)
        self.assertNotEqual(self.receive(self.request(1, 'image/wlanmdsp.mbn')), 0)
        self.assertEqual(self.library.metric(0), 0)

    def test_pd_mapper_encodes_native_domain_instance_and_rejects_truncated_tlvs(self):
        body = b'\1' + struct.pack('<H', 7) + b'wlan/fw'
        request = struct.pack('<BHHH', 0, 5, 0x21, len(body)) + body
        self.assertEqual(self.receive(request, to=0x4001), 0)
        response = self.output()
        self.assertEqual(struct.unpack_from('<BHHH', response), (2, 5, 0x21, len(response) - 7))
        self.assertIn(b'msm/modem/wlan_pd', response)
        self.assertIn(struct.pack('<I', 180), response)
        self.assertEqual(self.library.metric(10), 1)
        self.assertNotEqual(self.receive(request[:-1], to=0x4001), 0)

    def test_pd_mapper_uses_both_captured_domains_without_inventing_pdr_or_dump_services(self):
        for name, count in ((b'tms/servreg', 2), (b'gps/gps_service', 1), (b'tms/pdr_enabled', 0),
                            (b'tms/pddump_disabled', 0)):
            body = b'\1' + struct.pack('<H', len(name)) + name
            request = struct.pack('<BHHH', 0, 6, 0x21, len(body)) + body
            self.assertEqual(self.receive(request, to=0x4001), 0)
            output = self.output()
            self.assertIn(b'\x10\x02\0' + struct.pack('<H', count), output)
            if count == 2:
                self.assertIn(b'msm/modem/root_pd', output)
                self.assertIn(b'msm/modem/wlan_pd', output)

    def test_captured_inventory_hashes_are_consumed_by_the_actual_native_asset_parser(self):
        directory = Path(self.temporary.name) / 'assets'
        directory.mkdir(exist_ok=True)
        records = []
        for i, name in enumerate(wifi_assets.FILES):
            value = bytes([i + 1]) * (31 + i)
            path = directory / ('asset-' + str(i))
            path.write_bytes(value)
            records.append({'path': '/' + name, 'private_file': path.name, 'bytes': len(value),
                            'sha256': hashlib.sha256(value).hexdigest()})
        manifest = directory / 'inventory.json'
        manifest.write_text(json.dumps({'files': records}))
        blob, report = wifi_assets.pack(manifest)
        self.assertEqual(self.library.parse_assets(blob, len(blob), bytes.fromhex(report['sha256']), sha256), 0)
        self.assertEqual(self.library.asset_count(), 5)
        bad = bytearray(blob)
        bad[-16] ^= 1
        self.assertNotEqual(self.library.parse_assets(bytes(bad), len(bad), bytes.fromhex(report['sha256']), sha256), 0)
        self.assertEqual(self.library.asset_count(), 0)
        records[0]['sha256'] = '0' * 64
        manifest.write_text(json.dumps({'files': records}))
        with self.assertRaises(ValueError):
            wifi_assets.pack(manifest)

    def test_wlfw_capability_requires_the_expected_transaction_and_bounded_unique_fields(self):
        def tlv(kind, value):
            return bytes([kind]) + struct.pack('<H', len(value)) + value
        body = (tlv(2, bytes(4)) + tlv(0x10, struct.pack('<II', 0x1101, 0x3990)) +
                tlv(0x11, struct.pack('<I', 7)) + tlv(0x12, struct.pack('<I', 0x7250)))
        response = struct.pack('<BHHH', 2, 1, 0x24, len(body)) + body
        self.assertEqual(self.library.parse_cap(response, len(response)), 0)
        self.assertEqual([self.library.cap_field(i) for i in range(5)], [7, 0x1101, 0x3990, 7, 0x7250])
        for data in (response[:-1], response[:1] + b'\2\0' + response[3:],
                     struct.pack('<BHHH', 2, 1, 0x24, len(body) + 7) + body + tlv(2, bytes(4))):
            self.assertNotEqual(self.library.parse_cap(data, len(data)), 0)


if __name__ == '__main__':
    unittest.main()
