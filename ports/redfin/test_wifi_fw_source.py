"""Run the native source/planner/copy adapter on owned guard-page storage."""
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

from test_wifi_firmware import BASE, REGION, bundle, firmware, sha256, SHA

HERE = Path(__file__).resolve().parent


def private_bundle():
    path = Path(os.environ['REDFIN_WIFI_PRIVATE_BUNDLE'])
    plan = Path(os.environ.get('REDFIN_WIFI_PRIVATE_PLAN', str(path.with_name('mpss-v1-plan.json'))))
    selected = json.loads(plan.read_text())
    data = path.read_bytes()
    if len(data) != selected['bundle_bytes'] or hashlib.sha256(data).hexdigest() != selected['bundle_sha256']:
        raise AssertionError('private bundle differs from the recorded verified inventory selection')
    return data, selected

HARNESS = r'''
#define _DARWIN_C_SOURCE 1
#define _GNU_SOURCE 1
#include "wifi_fw_source.h"
#include <string.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <unistd.h>
#define EVENTS 32768
static struct rf_wifi_fw_source source;
static struct rf_wifi_fw_blob blob;
static struct rf_wifi_fw_layout layout;
static struct redfin_mpss_workspace workspace;
static struct rf_wifi_fw_source_ops ops;
static struct rf_wifi_fw_copy_ops copy_ops;
static uint8_t readback[65536];
static uint8_t *source_map,*source_bytes,*destination_map,*destination;
static size_t source_map_bytes,destination_map_bytes,page_bytes,destination_bytes;
static unsigned source_live,destination_live,refs,events,unsafe,fail_event,corrupt_read,drop_write;
static unsigned source_checks,destination_checks,lose_source,lose_destination,phase;
static uint64_t last_address;static uint32_t last_bytes;
static struct {unsigned kind;uint64_t address;uint32_t bytes;} event[EVENTS];
static redfin_mpss_sha256_fn selected_hash;
static const struct redfin_mpss_range excluded[]={
 {0x180000000ULL,0x80000000ULL},{0xa0000000ULL,0x2300000ULL},{0xb7e41000ULL,0x400000ULL}};
static int record(unsigned kind,uint64_t address,uint32_t bytes) {
 if(events>=EVENTS){unsafe++;return -90;}
 event[events].kind=kind;event[events].address=address;event[events].bytes=bytes;events++;
 return events==fail_event ? -71 : 0;
}
static int source_check(void *context,const struct rf_wifi_fw_blob *b,const struct rf_wifi_fw_layout *l) {
 ++source_checks;
 if(lose_source && source_checks>=lose_source)source_live=0;
 return context==&source && source_live && !memcmp(b,&blob,sizeof(blob)) && !memcmp(l,&layout,sizeof(layout)) ? 0 : -72;
}
static int pin(void *context,uint64_t physical,uint64_t bytes,const uint8_t **out) {
 int error=record(1,physical,(uint32_t)bytes);
 if(error)return error;
 if(context!=&source || refs || !source_live || physical!=blob.physical || bytes!=blob.reserved){unsafe++;return -90;}
 refs=1;*out=source_bytes;return 0;
}
static void unpin(void *context) {
 if(context!=&source || !refs){unsafe++;return;}
 refs=0;(void)record(2,0,0);
}
static int hash(void *context,const uint8_t *data,size_t bytes,uint8_t output[32]) {
 return context==&source ? selected_hash(NULL,data,bytes,output) : -73;
}
static int destination_check(void *context,const struct redfin_mpss_plan *plan,unsigned requested) {
 ++destination_checks;
 if(lose_destination && destination_checks>=lose_destination)destination_live=0;
 return context==&workspace && destination_live && destination && plan==&workspace.plan && phase==requested ? 0 : -74;
}
static int range(uint64_t address,uint32_t bytes,unsigned kind) {
 if(!bytes || bytes>65536 || address<REDFIN_MPSS_BASE || address-REDFIN_MPSS_BASE>destination_bytes ||
    bytes>destination_bytes-(address-REDFIN_MPSS_BASE)){unsafe++;return 0;}
 if(kind==5)return address==last_address && bytes==last_bytes;
 if(phase==RF_WIFI_FW_METADATA)return kind==3 && address==REDFIN_MPSS_BASE && bytes==workspace.plan.metadata_bytes;
 for(unsigned i=0;i<workspace.plan.segments;i++) {
  const struct redfin_mpss_segment *s=&workspace.plan.segment[i];
  uint64_t first=s->physical_address+(kind==4 ? s->file_bytes : 0);
  uint64_t end=s->physical_address+(kind==4 ? s->memory_bytes : s->file_bytes);
  if(address>=first && address<end && bytes<=end-address)return 1;
 }
 unsafe++;return 0;
}
static int write_bytes(void *context,uint64_t address,const uint8_t *data,uint32_t bytes) {
 if(context!=&workspace || !range(address,bytes,3))return -90;
 int error=record(3,address,bytes);if(error)return error;
 last_address=address;last_bytes=bytes;
 if(events!=drop_write)memcpy(destination+(address-REDFIN_MPSS_BASE),data,bytes);
 return 0;
}
static int zero_bytes(void *context,uint64_t address,uint32_t bytes) {
 if(context!=&workspace || !range(address,bytes,4))return -90;
 int error=record(4,address,bytes);if(error)return error;
 last_address=address;last_bytes=bytes;
 if(events!=drop_write)memset(destination+(address-REDFIN_MPSS_BASE),0,bytes);
 return 0;
}
static int read_bytes(void *context,uint64_t address,uint8_t *data,uint32_t bytes) {
 if(context!=&workspace || !range(address,bytes,5))return -90;
 int error=record(5,address,bytes);if(error)return error;
 memcpy(data,destination+(address-REDFIN_MPSS_BASE),bytes);
 if(events==corrupt_read)data[0]^=1;
 return 0;
}
static int sync_bytes(void *context,uint64_t address,uint64_t bytes) {
 uint64_t expected=phase==RF_WIFI_FW_METADATA ? workspace.plan.metadata_bytes : workspace.plan.memory_bytes;
 if(context!=&workspace || address!=REDFIN_MPSS_BASE || bytes!=expected){unsafe++;return -90;}
 return record(6,address,(uint32_t)bytes);
}
void destroy(void) {
 if(source.pinned)rf_wifi_fw_source_close(&source,&ops);
 if(source_map)munmap(source_map,source_map_bytes);
 if(destination_map)munmap(destination_map,destination_map_bytes);
 source_map=source_bytes=destination_map=destination=NULL;source_live=destination_live=0;
}
int configure(const uint8_t *data,size_t bytes,const uint8_t digest[32],redfin_mpss_sha256_fn digest_fn,size_t storage_bytes) {
 destroy();memset(&source,0,sizeof(source));memset(&workspace,0,sizeof(workspace));
 memset(&blob,0,sizeof(blob));memset(&layout,0,sizeof(layout));memset(event,0,sizeof(event));
 events=unsafe=fail_event=corrupt_read=drop_write=source_checks=destination_checks=lose_source=lose_destination=refs=0;
 selected_hash=digest_fn;page_bytes=(size_t)getpagesize();
 blob.physical=0x184000000ULL;blob.bytes=bytes;blob.reserved=(bytes+16383)&~16383ULL;blob.boot_id=1;
 memcpy(blob.sha256,digest,32);
 layout.ram=(struct redfin_mpss_range){0x180000000ULL,0x80000000ULL};layout.kernel_end=0x182000000ULL;
 layout.adt=(struct redfin_mpss_range){blob.physical+blob.reserved,4096};
 layout.arguments=(struct redfin_mpss_range){layout.adt.base+4096,736};
 layout.top=(layout.arguments.base+736+16383)&~16383ULL;
 source_map_bytes=(size_t)blob.reserved+2*page_bytes;
 source_map=mmap(NULL,source_map_bytes,PROT_NONE,MAP_ANON|MAP_PRIVATE,-1,0);
 if(source_map==MAP_FAILED){source_map=NULL;return -1;}
 source_bytes=source_map+page_bytes;
 if(mprotect(source_bytes,(size_t)blob.reserved,PROT_READ|PROT_WRITE))return -2;
 memcpy(source_bytes,data,bytes);
 if(mprotect(source_bytes,(size_t)blob.reserved,PROT_READ))return -3;
 destination_bytes=(storage_bytes+page_bytes-1)&~(page_bytes-1);
 destination_map_bytes=destination_bytes+2*page_bytes;
 destination_map=mmap(NULL,destination_map_bytes,PROT_NONE,MAP_ANON|MAP_PRIVATE,-1,0);
 if(destination_map==MAP_FAILED){destination_map=NULL;return -4;}
 destination=destination_map+page_bytes;
 if(mprotect(destination,destination_bytes,PROT_READ|PROT_WRITE))return -5;
 memset(destination,0xa5,destination_bytes);
 source_live=destination_live=1;phase=RF_WIFI_FW_METADATA;
 ops=(struct rf_wifi_fw_source_ops){&source,source_check,pin,unpin,hash};
 copy_ops=(struct rf_wifi_fw_copy_ops){&workspace,destination_check,write_bytes,zero_bytes,read_bytes,sync_bytes};
 return 0;
}
int open_source(void){return rf_wifi_fw_source_open(&source,&blob,&layout,excluded,3,&workspace,&ops);}
int copy_metadata(void){phase=RF_WIFI_FW_METADATA;return rf_wifi_fw_copy_metadata(&source,&ops,&copy_ops,readback,sizeof(readback));}
int copy_segments(void){phase=RF_WIFI_FW_SEGMENTS;return rf_wifi_fw_copy_segments(&source,&ops,&copy_ops,readback,sizeof(readback));}
void close_source(void){rf_wifi_fw_source_close(&source,&ops);}
void option(unsigned key,unsigned value) {
 switch(key) {
 case 0:fail_event=value;break;case 1:corrupt_read=value;break;case 2:drop_write=value;break;
 case 3:lose_source=value;break;case 4:lose_destination=value;break;
 case 5:source_live=value;break;case 6:destination_live=value;break;
 case 7:ops.context=NULL;break;case 8:workspace.plan.segment[0].physical_address^=value;break;
 }
}
void change_layout(unsigned key,uint64_t value) {
 switch(key) {
 case 0:blob.physical=value;break;case 1:blob.bytes=value;break;case 2:blob.reserved=value;break;
 case 3:blob.boot_id=value;break;case 4:layout.ram.base=value;break;case 5:layout.ram.bytes=value;break;
 case 6:layout.kernel_end=value;break;case 7:layout.adt.base=value;break;case 8:layout.adt.bytes=value;break;
 case 9:layout.arguments.base=value;break;case 10:layout.arguments.bytes=value;break;case 11:layout.top=value;break;
 case 12:layout.ramdisk.base=value;break;case 13:layout.ramdisk.bytes=value;break;
 }
}
void corrupt_source(uint64_t offset) {
 if(offset>=blob.reserved)return;
 mprotect(source_bytes,(size_t)blob.reserved,PROT_READ|PROT_WRITE);source_bytes[offset]^=1;
 mprotect(source_bytes,(size_t)blob.reserved,PROT_READ);
}
uint64_t metric(unsigned which) {
 const uint64_t values[]={source.stage,source.poisoned,refs,events,unsafe,source_checks,destination_checks,
 source.metadata_written,source.copied_bytes,source.zeroed_bytes,source.readback_bytes,
 workspace.plan.phdrs,workspace.plan.segments,workspace.image.assets,workspace.plan.memory_bytes};
 return which<sizeof(values)/sizeof(values[0]) ? values[which] : 0;
}
uint64_t trace(unsigned index,unsigned field) {
 if(index>=events)return UINT64_MAX;
 return field==0 ? event[index].kind : field==1 ? event[index].address : event[index].bytes;
}
const uint8_t *get_destination(void){return destination;}
int error_value(unsigned which){return which==0 ? source.error : which==1 ? source.platform_error : source.planner_error;}
int bad_readback(unsigned which) {
 uint8_t *p=which==0 ? (uint8_t *)source.data : which==1 ? (uint8_t *)&workspace : which==2 ? (uint8_t *)&source :
  which==3 ? (uint8_t *)&ops : (uint8_t *)&copy_ops;
 return rf_wifi_fw_copy_metadata(&source,&ops,&copy_ops,p,65536);
}
int bad_workspace(unsigned which) {
 void *p=which==0 ? (void *)&source : which==1 ? (void *)&blob : which==2 ? (void *)&layout :
  which==3 ? (void *)&ops : (void *)excluded;
 return rf_wifi_fw_source_open(&source,&blob,&layout,excluded,3,(struct redfin_mpss_workspace *)p,&ops);
}
'''


class WifiFirmwareSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('host C compiler unavailable')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        source = cls.directory / 'source.c'; source.write_text(HARNESS)
        library = cls.directory / 'source.so'
        subprocess.run([compiler, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                        '-I', str(HERE), str(source), str(HERE / 'wifi_fw_source.c'), '-o', str(library)],
                       check=True, capture_output=True)
        cls.library = C.CDLL(str(library))
        cls.library.configure.argtypes = [C.c_void_p, C.c_size_t, C.c_void_p, SHA, C.c_size_t]
        cls.library.metric.restype = C.c_uint64
        cls.library.trace.restype = C.c_uint64
        cls.library.get_destination.restype = C.c_void_p
        cls.library.change_layout.argtypes = [C.c_uint, C.c_uint64]
        cls.library.corrupt_source.argtypes = [C.c_uint64]
        cls.addClassCleanup(cls.library.destroy)

    def setUp(self):
        self.data = bundle()
        self.configure()

    def configure(self, data=None, storage=0x40000):
        data = self.data if data is None else data
        self.assertEqual(self.library.configure(data, len(data), hashlib.sha256(data).digest(), sha256, storage), 0)

    def opened(self):
        self.assertEqual(self.library.open_source(), 0)

    def copied(self):
        self.opened()
        self.assertEqual(self.library.copy_metadata(), 0)
        self.assertEqual(self.library.copy_segments(), 0)

    def trace(self):
        return [tuple(self.library.trace(index, field) for field in range(3))
                for index in range(self.library.metric(3))]

    def test_actual_bundle_plan_metadata_copy_segments_zero_and_readback(self):
        self.copied()
        self.assertEqual([self.library.metric(i) for i in (0, 1, 2, 4, 11, 12, 13)], [4, 0, 1, 0, 5, 3, 3])
        metadata, blobs = firmware()
        memory = C.string_at(self.library.get_destination(), 0x40000)
        self.assertEqual(memory[:len(blobs[2])], blobs[2])
        self.assertEqual(memory[len(blobs[2]):0x14000], bytes(0x14000 - len(blobs[2])))
        self.assertEqual(memory[0x14000:0x14000 + len(blobs[4])], blobs[4])
        self.assertEqual(memory[0x14000 + len(blobs[4]):0x16000], bytes(0x2000 - len(blobs[4])))
        self.assertEqual(memory[0x16000:], b'\xa5' * (0x40000 - 0x16000))
        self.assertEqual(self.library.metric(7), len(metadata))
        self.assertEqual(self.library.metric(8), sum(map(len, blobs.values())))
        self.assertEqual(self.library.metric(10), len(metadata) + 0x16000)
        self.assertTrue(all(0 < size <= 65536 for kind, _address, size in self.trace() if kind in (3, 4, 5)))
        self.library.close_source(); self.library.close_source()
        self.assertEqual(self.library.metric(2), 0)
        self.assertEqual(sum(kind == 2 for kind, _address, _bytes in self.trace()), 1)

    def test_source_layout_placement_abi_and_zero_padding_fail_before_publication(self):
        bad = [(0, 0x184000001), (1, 0), (1, 0x10000001), (2, len(self.data)),
               (3, 0), (4, 0x180004000), (5, 0x4000), (6, 0x184004000),
               (7, 0), (8, 0x200001), (9, 0), (10, 735), (11, 0), (12, 0x184000000), (13, 16384)]
        for key, value in bad:
            self.configure(); self.library.change_layout(key, value)
            self.assertEqual(self.library.open_source(), 2, (key, value))
            self.assertEqual(self.library.metric(3), 0)
        self.configure(); self.library.corrupt_source(len(self.data))
        self.assertEqual(self.library.open_source(), 7)
        self.assertEqual(self.library.metric(2), 0)

    def test_whole_blob_hash_and_real_asset_hash_are_both_required(self):
        for offset in (0, 64 + 16, len(self.data) - 16):
            self.configure(); self.library.corrupt_source(offset)
            self.assertEqual(self.library.open_source(), 5)
            self.assertEqual(self.library.metric(2), 0)
        altered = bytearray(self.data); altered[-16] ^= 1
        self.configure(bytes(altered))  # Correct whole-blob hash, corrupt asset.
        self.assertEqual(self.library.open_source(), 6)
        self.assertEqual(self.library.metric(2), 0)

    def test_copy_phases_cannot_be_skipped_repeated_or_reopened(self):
        self.opened()
        self.assertEqual(self.library.copy_segments(), 3)
        self.assertEqual(self.library.copy_metadata(), 0)
        self.assertEqual(self.library.copy_metadata(), 3)
        self.assertEqual(self.library.copy_segments(), 0)
        self.assertEqual(self.library.copy_segments(), 3)
        self.assertEqual(self.library.open_source(), 3)

    def test_each_copy_io_failure_quarantines_and_stops_without_retry(self):
        self.copied()
        count = self.library.metric(3)
        for fail in range(2, count + 1):
            self.configure(); self.opened(); self.library.option(0, fail)
            status = self.library.copy_metadata()
            if not status:
                status = self.library.copy_segments()
            self.assertNotEqual(status, 0, fail)
            self.assertEqual(self.library.metric(3), fail)
            self.assertEqual(self.library.metric(1), 1)
            self.assertEqual(self.library.error_value(1), -71)
            before = self.library.metric(3)
            self.assertEqual(self.library.copy_segments(), 3)
            self.assertEqual(self.library.metric(3), before)
            self.assertEqual(self.library.metric(4), 0)

    def test_missing_write_or_zero_and_corrupted_readback_are_detected(self):
        self.copied()
        operations = self.trace()
        for index, (kind, _address, _size) in enumerate(operations, 1):
            if kind not in (3, 4, 5):
                continue
            self.configure(); self.opened()
            self.library.option(1 if kind == 5 else 2, index)
            status = self.library.copy_metadata()
            if not status:
                status = self.library.copy_segments()
            self.assertEqual(status, 8, (index, kind))
            self.assertEqual(self.library.metric(1), 1)

    def test_source_lease_destination_lease_and_workspace_mutation_prevent_writes(self):
        for option, value in ((5, 0), (6, 0), (7, 1), (8, 16384)):
            self.configure(); self.opened(); self.library.option(option, value)
            self.assertNotEqual(self.library.copy_metadata(), 0)
            self.assertFalse(any(kind in (3, 4) for kind, _address, _size in self.trace()))
            self.assertEqual(self.library.metric(1), 1)
        for option in (3, 4):
            self.configure(); self.opened(); checks = self.library.metric(5 if option == 3 else 6)
            self.library.option(option, checks + 8)
            status = self.library.copy_metadata()
            if not status:
                status = self.library.copy_segments()
            self.assertNotEqual(status, 0)
            self.assertEqual(self.library.metric(1), 1)

    def test_source_change_after_open_and_between_phases_never_reaches_next_copy(self):
        self.opened(); self.library.corrupt_source(len(self.data) - 16)
        self.assertEqual(self.library.copy_metadata(), 5)
        self.assertFalse(any(kind in (3, 4) for kind, _address, _size in self.trace()))
        self.configure(); self.opened(); self.assertEqual(self.library.copy_metadata(), 0)
        count = self.library.metric(3); self.library.corrupt_source(len(self.data) - 16)
        self.assertEqual(self.library.copy_segments(), 5)
        self.assertEqual(self.library.metric(3), count)

    def test_readback_must_be_private_and_cannot_alias_source_workspace_or_state(self):
        self.opened()
        for which in range(5):
            self.assertEqual(self.library.bad_readback(which), 1)
        self.assertFalse(any(kind in (3, 4) for kind, _address, _size in self.trace()))

    def test_workspace_cannot_alias_lease_state_descriptors_or_callbacks(self):
        for which in range(5):
            self.assertEqual(self.library.bad_workspace(which), 1)
        self.assertEqual(self.library.metric(3), 0)

    def test_c_cpp_and_freestanding_arm64_use_no_large_stack_buffers(self):
        compiler = shutil.which('c++')
        if compiler:
            subprocess.run([compiler, '-x', 'c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            '-I', str(HERE), '-fsyntax-only', str(HERE / 'wifi_fw_source.c')],
                           check=True, capture_output=True)
        compiler = shutil.which('clang')
        if compiler:
            output = self.directory / 'source-arm64.o'
            subprocess.run([compiler, '-target', 'aarch64-none-elf', '-ffreestanding', '-O2', '-std=c11',
                            '-Wall', '-Wextra', '-Werror', '-fstack-usage', '-I', str(HERE),
                            '-c', str(HERE / 'wifi_fw_source.c'), '-o', str(output)], check=True, capture_output=True)
            frames = [int(line.split('\t')[1]) for line in output.with_suffix('.su').read_text().splitlines()]
            self.assertLess(max(frames), 1024)

    def test_kernel_overlay_contains_exact_source_and_native_boot_adapter(self):
        patch = (HERE / 'wifi-fw-source.patch').read_text()
        entries = [('wifi_fw_source.h', 'bsd/dev/redfin_wifi_fw_source.h'),
                   ('wifi_fw_source.c', 'bsd/dev/redfin_wifi_fw_source.c'),
                   ('wifi_fw_boot.h', 'iokit/Kernel/arm/redfin_wifi_fw_boot.h'),
                   ('wifi_fw_boot.cpp', 'iokit/Kernel/arm/RedfinWiFiFWSource.cpp')]
        for source, target in entries:
            expected = (HERE / source).read_text()
            expected = expected.replace('"wifi_firmware.h"', '"../../iokit/Kernel/arm/redfin_wifi_firmware.h"')
            expected = expected.replace('"gui-profile.h"', '<arm64/redfin_gui_profile.h>')
            expected = expected.replace('"wifi_fw_source.h"', '"redfin_wifi_fw_source.h"' if source.endswith('.c')
                                        else '"../../../bsd/dev/redfin_wifi_fw_source.h"')
            section = patch.split('+++ b/' + target + '\n', 1)[1].split('diff --git ', 1)[0]
            actual = ''.join(line[1:] for line in section.splitlines(keepends=True) if line.startswith('+'))
            self.assertEqual(actual, expected)

    @unittest.skipUnless(os.environ.get('REDFIN_WIFI_PRIVATE_BUNDLE'), 'private bundle not requested')
    def test_private_verified_bundle_uses_actual_adapter_and_owned_storage(self):
        data, _selected = private_bundle()
        self.configure(data, storage=REGION)
        self.copied()
        self.assertEqual([self.library.metric(i) for i in (11, 12, 13, 14)], [35, 33, 31, REGION])
        self.assertEqual(self.library.metric(7), 9420)
        self.assertEqual(self.library.metric(8), 99384626)
        self.assertEqual(self.library.metric(9), 191553563)
        self.assertEqual(self.library.metric(10), 9420 + 99384626 + 191553563)
        self.assertEqual(self.library.metric(4), 0)


if __name__ == '__main__':
    unittest.main()
