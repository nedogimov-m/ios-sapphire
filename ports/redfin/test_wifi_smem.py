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
          'tx_tail', 'tx_head', 'rx_tail', 'rx_head', 'tx_pending', 'rx_pending',
          'failure_detail', 'toc_version', 'entry_index', 'entry_offset', 'entry_bytes',
          'entry_host0', 'entry_host1', 'entry_cacheline', 'other_index', 'other_offset', 'other_bytes',
          'header_present', 'header_magic', 'header_host0', 'header_host1', 'header_bytes',
          'free_uncached', 'free_cached')


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

    def test_48_byte_entries_global_partition_and_unused_slots(self):
        data = fixture()
        modem_entry = data[TOC + 32:TOC + 80]
        struct.pack_into('<I', data, TOC + 8, 64)
        data[TOC + 32:TOC + 80] = bytes(48)
        struct.pack_into('<IIIHHI', data, TOC + 32, 0x1000, PART - 0x1000, 0,
                         0xfffe, 0xfffe, 32)
        # An unused slot may retain host/reserved metadata; stride remains 48.
        struct.pack_into('<HH', data, TOC + 80 + 12, 9, 10)
        struct.pack_into('<I', data, TOC + 80 + 44, 0xffffffff)
        data[TOC + 128:TOC + 176] = modem_entry
        status, report = self.inspect(data)
        self.assertEqual((status, report.partitions, report.entry_index), (0, 64, 2))
        self.assertEqual((report.entry_host0, report.entry_host1, report.entry_cacheline), (0, 1, 32))

    def test_partition_rejection_preserves_bounds_and_host_metadata(self):
        for offset, size, detail in [(0, PART_SIZE, 1), (PART, 0, 1),
                                     (0xfffffff0, 0x100, 2), (TOC - 16, 32, 2)]:
            with self.subTest(offset=offset, size=size):
                data = fixture()
                struct.pack_into('<II', data, TOC + 32, offset, size)
                status, report = self.inspect(data)
                self.assertEqual((status, report.failure_detail, report.partitions), (5, detail, 1))
                self.assertEqual((report.version, report.toc_version, report.entry_index), (12 << 16, 1, 0))
                self.assertEqual((report.entry_offset, report.entry_bytes), (offset, size))
                self.assertEqual((report.entry_host0, report.entry_host1), (0, 1))
                self.assertEqual((report.header_present, report.header_magic), (0, 0))
                self.assertEqual(report.other_index, 0xffffffff)

    def test_non_apps_entries_are_not_interpreted_as_apps_heaps(self):
        # Device V4 lists the TOC itself first, with no APPS owner. Linux
        # filters by host before mapping a private partition (smem.c:965).
        for offset, size, host0, host1 in ((TOC, 0x1000, 0xffff, 0xffff),
                                          (0xfffffff0, 0xffffffff, 2, 3)):
            with self.subTest(offset=offset, host0=host0):
                data = fixture()
                modem_entry = data[TOC + 32:TOC + 80]
                struct.pack_into('<I', data, TOC + 8, 2)
                data[TOC + 80:TOC + 128] = modem_entry
                struct.pack_into('<IIIHHI', data, TOC + 32, offset, size, 0, host0, host1, 0)
                status, report = self.inspect(data)
                self.assertEqual((status, report.modem_partition, report.entry_index), (0, 1, 1))
                self.assertEqual((report.descriptor, report.tx_bytes, report.rx_bytes), (1, 0x4000, 0x4000))
                # The same invalid extent becomes an error if APPS owns it.
                struct.pack_into('<HH', data, TOC + 44, 0, host1)
                self.assertEqual(self.inspect(data)[0], 5)

    def test_partition_header_rejection_identifies_exact_field(self):
        cases = [(PART, 0, 5), (PART + 4, 0x00020000, 6),
                 (PART + 8, PART_SIZE - 1, 7), (PART + 12, 31, 8),
                 (PART + 12, PART_SIZE + 1, 8), (PART + 16, 32, 8)]
        for offset, value, detail in cases:
            with self.subTest(offset=offset, value=value):
                data = fixture()
                struct.pack_into('<I', data, offset, value)
                status, report = self.inspect(data)
                self.assertEqual((status, report.failure_detail, report.partitions), (5, detail, 1))
                self.assertEqual((report.entry_index, report.modem_partition, report.header_present), (0, 1, 1))
                self.assertEqual(report.header_magic, struct.unpack_from('<I', data, PART)[0])
                self.assertEqual((report.header_host0, report.header_host1),
                                 struct.unpack_from('<HH', data, PART + 4))
                self.assertEqual((report.header_bytes, report.free_uncached, report.free_cached),
                                 struct.unpack_from('<III', data, PART + 8))
        # Google permits either host order; our existing exact-order rule stays strict.
        data = fixture()
        struct.pack_into('<HH', data, PART + 4, 1, 0)
        self.assertEqual(self.inspect(data)[1].failure_detail, 6)
        struct.pack_into('<HH', data, TOC + 44, 1, 0)
        self.assertEqual(self.inspect(data)[0], 0)

    def test_overlap_and_duplicate_report_both_entry_bounds(self):
        for second_offset, detail in [(PART + 32, 3), (PART + PART_SIZE, 4)]:
            data = fixture(False)
            struct.pack_into('<I', data, TOC + 8, 2)
            data[TOC + 80:TOC + 128] = data[TOC + 32:TOC + 80]
            struct.pack_into('<I', data, TOC + 80, second_offset)
            status, report = self.inspect(data)
            self.assertEqual((status, report.failure_detail, report.partitions), (5, detail, 2))
            self.assertEqual((report.entry_index, report.entry_offset, report.entry_bytes),
                             (1, second_offset, PART_SIZE))
            self.assertEqual((report.other_index, report.other_offset, report.other_bytes),
                             (0, PART, PART_SIZE))

    def test_embedded_header_is_exact_copy(self):
        from test_overlay_sources import sensor_overlay
        first = (HERE / 'wifi-probe.patch').read_text().split('\ndiff --git ', 1)[0]
        embedded = '\n'.join(line[1:] for line in first.splitlines()
                             if line.startswith('+') and not line.startswith('+++')) + '\n'
        embedded=sensor_overlay(embedded,'iokit/bsddev/redfin_wifi_smem.h')
        self.assertEqual(embedded, (HERE / 'wifi_smem.h').read_text())

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
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include "wifi_smem.h"
typedef void *DTEntry;
enum {kSuccess=0,kIODirectionIn=1,kIOMapReadOnly=2,kIOMapWriteCombineCache=4};
static int mode, maps, allocations, releases, violations, logs;
static uint8_t snapshot[REDFIN_SMEM_BYTES];
static char output[2048];
static unsigned output_bytes;
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
static void IOLog(const char *format,...) {
    char line[256];
    va_list args;va_start(args,format);
    int n=vsnprintf(line,sizeof(line),format,args);va_end(args);
    if(n<0 || (unsigned)n>=sizeof(line) || output_bytes+((unsigned)n)>=sizeof(output)){
        ++violations;return;
    }
    memcpy(output+output_bytes,line,(unsigned)n+1);output_bytes+=(unsigned)n;++logs;
}
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
    if(mode==9 || mode==10){
        uint32_t v=12u<<16;memcpy(snapshot+0x5c,&v,4);
        v=1;memcpy(snapshot+0xc0,&v,4);
        unsigned toc=REDFIN_SMEM_BYTES-0x1000u;
        memcpy(snapshot+toc,"$TOC",4);memcpy(snapshot+toc+4,&v,4);memcpy(snapshot+toc+8,&v,4);
        v=mode==9 ? 0xfffffff0u : 0x10000u;memcpy(snapshot+toc+32,&v,4);
        v=0x10000u;memcpy(snapshot+toc+36,&v,4);memcpy(snapshot+toc+44,&v,4);
        if(mode==10)memset(snapshot+0x10000,0xff,32);
    }
    redfin_wifi_observe();redfin_wifi_observe();
    if(violations)return 10;
    if(mode>=1 && mode<=6)return allocations || maps || releases ? 11 : 0;
    if(mode==7)return allocations!=1 || maps!=1 || releases!=1 ? 12 : 0;
    if(mode==8)return allocations!=1 || maps!=0 || releases!=0 ? 13 : 0;
    if(mode==9 && (!strstr(output,"partitions=1") ||
        !strstr(output,"reject detail=2 entry=0 offset=0xfffffff0") ||
        !strstr(output,"hosts=0/1") || !strstr(output,"header=0 magic=0")))return 15;
    if(mode==10 && (!strstr(output,"reject detail=5 entry=0") ||
        !strstr(output,"header=1 magic=0xffffffff hosts=65535/65535") ||
        !strstr(output,"size=0xffffffff free_u=0xffffffff free_c=0xffffffff")))return 16;
    return allocations!=1 || maps!=1 || releases!=2 || logs!=5 ? 14 : 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source, executable = Path(directory) / 'observer.cpp', Path(directory) / 'observer'
            source.write_text(harness + helper + main)
            subprocess.run([shutil.which('c++'), '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            '-I', str(HERE), str(source), '-o', str(executable)], check=True)
            for mode in range(11):
                with self.subTest(mode=mode):
                    self.assertEqual(subprocess.run([str(executable), str(mode)]).returncode, 0)


if __name__ == '__main__':
    unittest.main()
