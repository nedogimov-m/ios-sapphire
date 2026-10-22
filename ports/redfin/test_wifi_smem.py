"""Exercise the actual read-only C SMEM parser against bounded wire layouts."""
import ctypes
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SIZE, TOC, PART, PART_SIZE = 0x200000, 0x1ff000, 0x10000, 0x10000
FIELDS = ('version', 'partitions', 'modem_partition', 'partition_offset', 'partition_bytes',
          'uncached_items', 'cached_uninspected', 'descriptor', 'tx_bytes', 'rx_bytes',
          'tx_tail', 'tx_head', 'rx_tail', 'rx_head', 'tx_pending', 'rx_pending')


class Report(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in FIELDS]


def fixture(items=True):
    data = bytearray(SIZE)
    struct.pack_into('<I', data, 0x5c, 12 << 16)
    struct.pack_into('<I', data, 0xc0, 1)
    struct.pack_into('<4sII', data, TOC, b'$TOC', 1, 1)
    struct.pack_into('<IIIHHI', data, TOC + 32, PART, PART_SIZE, 0, 0, 1, 32)
    cursor = 32
    if items:
        for item, value in [(478, struct.pack('<8I', 0x3ff8, 8, 0, 24, 0, 0, 0, 0)),
                            (479, bytes(0x4000)), (480, bytes(0x4000))]:
            struct.pack_into('<HHIHHI', data, PART + cursor, 0xa5a5, item, len(value), 0, 0, 0)
            data[PART + cursor + 16:PART + cursor + 16 + len(value)] = value
            cursor += 16 + len(value)
    struct.pack_into('<4sHHIII', data, PART, b'$PRT', 0, 1, PART_SIZE, cursor, PART_SIZE)
    return data


class WifiSmemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('cc')
        if not cc:
            raise unittest.SkipTest('host C compiler unavailable')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        base = Path(cls.temporary.name)
        source, library = base / 'parser.c', base / 'parser.so'
        source.write_text('#include "wifi_smem.h"\n'
                          'int inspect(const uint8_t *p,size_t n,struct redfin_smem_report *r)'
                          '{return redfin_smem_inspect(p,n,r);}\n')
        subprocess.run([cc, '-std=c11', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                        '-I', str(HERE), str(source), '-o', str(library)], check=True)
        cls.library = ctypes.CDLL(str(library))
        cls.library.inspect.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(Report)]
        cls.library.inspect.restype = ctypes.c_int
        cls.cli = base / 'wifi-smem'
        subprocess.run([cc, '-std=c11', '-Wall', '-Wextra', '-Werror',
                        str(HERE / 'wifi-smem.c'), '-o', str(cls.cli)], check=True)

    def inspect(self, value, length=None):
        before = bytes(value)
        buffer = ctypes.create_string_buffer(before)
        report = Report()
        status = self.library.inspect(buffer, len(before) if length is None else length,
                                      ctypes.byref(report))
        self.assertEqual(buffer.raw[:-1], before, 'parser must not write shared memory')
        return status, report

    def test_real_layout_and_wrapped_fifo_counts(self):
        status, report = self.inspect(fixture())
        self.assertEqual(status, 0)
        self.assertEqual((report.modem_partition, report.uncached_items, report.descriptor), (1, 3, 1))
        self.assertEqual((report.tx_bytes, report.rx_bytes, report.tx_pending, report.rx_pending),
                         (16384, 16384, 16, 24))

    def test_initialized_without_glink_is_not_reported_as_dead_modem(self):
        status, report = self.inspect(fixture(False))
        self.assertEqual(status, 0)
        self.assertEqual((report.modem_partition, report.descriptor, report.rx_pending), (1, 0, 0))
        data = fixture(False)
        struct.pack_into('<HH', data, TOC + 44, 0, 2)
        status, report = self.inspect(data)
        self.assertEqual((status, report.modem_partition), (0, 0))

    def test_header_and_table_validation(self):
        for offset, value, expected in [(0xc0, 0, 2), (0xcc, 1, 2), (0x5c, 11 << 16, 3),
                                        (TOC, 0, 4), (TOC + 4, 2, 4), (TOC + 8, 65, 4),
                                        (TOC + 32, SIZE - 8, 5), (TOC + 36, 0xffffffff, 5)]:
            with self.subTest(offset=offset, value=value):
                data = fixture()
                struct.pack_into('<I', data, offset, value)
                self.assertEqual(self.inspect(data)[0], expected)
        self.assertEqual(self.inspect(bytes(128))[0], 1)
        self.assertEqual(self.inspect(fixture(), SIZE - 1)[0], 1)

    def test_partition_duplicates_overlaps_and_free_bounds(self):
        for offset, value in [(PART, 0), (PART + 4, 0x00020000), (PART + 8, PART_SIZE - 1),
                              (PART + 12, 31), (PART + 12, PART_SIZE + 1), (PART + 16, 32)]:
            data = fixture()
            struct.pack_into('<I', data, offset, value)
            self.assertEqual(self.inspect(data)[0], 5)
        data = fixture()
        struct.pack_into('<I', data, TOC + 8, 2)
        data[TOC + 80:TOC + 128] = data[TOC + 32:TOC + 80]
        self.assertEqual(self.inspect(data)[0], 5)
        struct.pack_into('<I', data, TOC + 80, PART + PART_SIZE)
        self.assertEqual(self.inspect(data)[0], 5)  # duplicate APPS/MODEM partition

    def test_private_item_bounds_and_duplicate_descriptor(self):
        for offset, fmt, value in [(PART + 32, '<H', 0), (PART + 36, '<I', 0xffffffff),
                                   (PART + 40, '<H', 32), (PART + 42, '<H', 0xffff)]:
            data = fixture()
            struct.pack_into(fmt, data, offset, value)
            self.assertEqual(self.inspect(data)[0], 6)
        data = fixture()
        struct.pack_into('<H', data, PART + 32 + 16 + 32 + 2, 478)
        self.assertEqual(self.inspect(data)[0], 6)

    def test_glink_descriptor_and_fifo_bounds(self):
        for offset, value in [(PART + 48, 16384), (PART + 52, 1), (PART + 56, 16384)]:
            data = fixture()
            struct.pack_into('<I', data, offset, value)
            self.assertEqual(self.inspect(data)[0], 7)
        data = fixture()
        struct.pack_into('<H', data, PART + 40, 8)  # descriptor payload is now 24 bytes
        self.assertEqual(self.inspect(data)[0], 7)

    def test_host_cli_refuses_symlink_and_partial_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            raw = base / 'smem.raw'
            raw.write_bytes(fixture())
            result = subprocess.run([str(self.cli), str(raw)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"remote_running_proven":false', result.stdout)
            link = base / 'link'
            link.symlink_to(raw)
            self.assertEqual(subprocess.run([str(self.cli), str(link)], capture_output=True).returncode, 2)
            raw.write_bytes(bytes(128))
            self.assertEqual(subprocess.run([str(self.cli), str(raw)], capture_output=True).returncode, 2)

    def test_actual_kernel_observer_gates_read_only_mapping_and_cleanup(self):
        patch = (HERE / 'wifi-probe.patch').read_text()
        added = '\n'.join(line[1:] for line in patch.splitlines()
                          if line.startswith('+') and not line.startswith('+++'))
        helper = added.split('/* REDFIN_WIFI_OBSERVER_TEST_BEGIN:', 1)[1]
        helper = helper.split('*/', 1)[1].split('/* REDFIN_WIFI_OBSERVER_TEST_END */', 1)[0]
        harness = r'''
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "wifi_smem.h"
typedef void *DTEntry;
enum {kSuccess=0,kIODirectionIn=1,kIOMapReadOnly=2,kIOMapWriteCombineCache=4};
static int mode, maps, allocations, releases, violations, logs;
static uint8_t snapshot[REDFIN_SMEM_BYTES];
static bool PE_parse_boot_argn(const char *key,void *out,unsigned bytes) {
    uint32_t value = !strcmp(key,"redfinwifi") ? (mode==1 ? 0 : 1) : (mode==5 ? 2 : 1);
    if(bytes!=4) violations++;
    memcpy(out,&value,4); return true;
}
static int SecureDTLookupEntry(void *,const char *path,DTEntry *out) {
    if(mode==6 && !strcmp(path,"/redfin-wifi")) return 1;
    *out=!strcmp(path,"/chosen") ? (void *)2 : (void *)1; return 0;
}
static int SecureDTGetProperty(DTEntry,const char *key,const void **out,unsigned *length) {
    static uint32_t marker;
    static uint64_t reg[2],base,size;
    marker=mode==2 ? 0 : 1; reg[0]=mode==3 ? REDFIN_SMEM_PHYSICAL+0x4000 : REDFIN_SMEM_PHYSICAL;
    reg[1]=REDFIN_SMEM_BYTES; base=mode==4 ? REDFIN_SMEM_PHYSICAL : 0x180000000ull; size=0x80000000;
    if(!strcmp(key,"reg")){*out=reg;*length=16;}
    else if(!strcmp(key,"reserved-memory-verified")){*out=&marker;*length=4;}
    else if(!strcmp(key,"dram-base")){*out=&base;*length=8;}
    else if(!strcmp(key,"dram-size")){*out=&size;*length=8;}
    else return 1;
    return 0;
}
static void IOLog(const char *,...) {++logs;}
class IOMemoryMap {
public:
    uint64_t getLength(){return REDFIN_SMEM_BYTES;}
    uintptr_t getVirtualAddress(){return (uintptr_t)snapshot;}
    void release(){++releases;delete this;}
};
class IOMemoryDescriptor {
public:
    static IOMemoryDescriptor *withPhysicalAddress(uint64_t base,uint64_t size,int direction){
        if(base!=REDFIN_SMEM_PHYSICAL || size!=REDFIN_SMEM_BYTES || direction!=kIODirectionIn)++violations;
        ++allocations; return mode==8 ? NULL : new IOMemoryDescriptor;
    }
    IOMemoryMap *map(int flags){
        if(flags!=(kIOMapReadOnly|kIOMapWriteCombineCache))++violations;
        ++maps;return mode==7 ? NULL : new IOMemoryMap;
    }
    void release(){++releases;delete this;}
};
#define OSSafeReleaseNULL(p) do{if(p){p->release();p=NULL;}}while(0)
'''
        main = r'''
int main(int argc,char **argv){
    if(argc!=2)return 9;
    mode=atoi(argv[1]);
    redfin_wifi_observe();redfin_wifi_observe();
    if(violations)return 10;
    if(mode>=1 && mode<=6)return allocations || maps || releases ? 11 : 0;
    if(mode==7)return allocations!=1 || maps!=1 || releases!=1 ? 12 : 0;
    if(mode==8)return allocations!=1 || maps!=0 || releases!=0 ? 13 : 0;
    return allocations!=1 || maps!=1 || releases!=2 || logs!=3 ? 14 : 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source, executable = Path(directory) / 'observer.cpp', Path(directory) / 'observer'
            source.write_text(harness + helper + main)
            subprocess.run([shutil.which('c++'), '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            '-I', str(HERE), str(source), '-o', str(executable)], check=True)
            for mode in range(9):
                with self.subTest(mode=mode):
                    self.assertEqual(subprocess.run([str(executable), str(mode)]).returncode, 0)


if __name__ == '__main__':
    unittest.main()
