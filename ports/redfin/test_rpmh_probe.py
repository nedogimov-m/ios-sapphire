"""Run the actual CMD-DB reader and read-only RPMh probe without hardware."""
import ctypes as C
import errno
from pathlib import Path
import random
import shutil
import struct
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
DB_BYTES = 0x20000
ARC_NAMES = ('xo.lvl', 'cx.lvl', 'mx.lvl', 'gfx.lvl')
VRM_NAMES = ('ldoa17', 'ldoa5', 'ldoa12', 'ldoa2')


def added_file(name):
    patch = (HERE / 'rpmh-probe.patch').read_text()
    section = patch.split('+++ b/bsd/dev/' + name + '\n', 1)[1].split('diff --git ', 1)[0]
    return '\n'.join(line[1:] for line in section.splitlines() if line.startswith('+')) + '\n'


def database():
    data = bytearray(DB_BYTES)
    struct.pack_into('<II', data, 0, 1, 0x0c0330db)
    for slot, (kind, names, headers, aux) in enumerate(((3, ARC_NAMES, 0, 0x400), (4, VRM_NAMES, 0x200, 0x500))):
        struct.pack_into('<5H', data, 8 + slot * 16, kind, headers, aux, len(names), 0x100)
        for i, name in enumerate(names):
            at = 144 + headers + i * 24
            data[at:at + 8] = name.encode().ljust(8, b'\0')
            struct.pack_into('<IIIHH', data, at + 8, 1, 2, (kind << 16) + i * 16, 8 if kind == 3 else 0, i * 32)
            if kind == 3:
                struct.pack_into('<4H', data, 144 + aux + i * 32, 0, 48, 128, 384)
    return data


class Resource(C.Structure):
    _fields_ = [('address', C.c_uint32), ('priority', C.c_uint32 * 2),
                ('type', C.c_uint16), ('aux_version', C.c_uint16), ('aux_bytes', C.c_uint16),
                ('levels', C.c_uint16 * 16), ('level_count', C.c_uint)]


class RpmhProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('cc')
        if compiler is None:
            raise unittest.SkipTest('host C compiler required')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.work = Path(cls.temporary.name)
        (cls.work / 'redfin_rpmh.h').write_text(added_file('redfin_rpmh.h'))
        parser = cls.work / 'parser.c'
        parser.write_text('''#include "redfin_rpmh.h"
int validate(const uint8_t *p,size_t n){return rf_cmddb_validate(p,n);}
int lookup(const uint8_t *p,size_t n,const uint8_t *k,unsigned t,struct rf_cmddb_resource *r)
{return rf_cmddb_lookup(p,n,k,t,r);}
unsigned resource_size(void){return sizeof(struct rf_cmddb_resource);}
''')
        library = cls.work / 'parser.so'
        subprocess.run([compiler, '-std=c11', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                        str(parser), '-o', str(library)], check=True, capture_output=True)
        cls.lib = C.CDLL(str(library))
        cls.lib.validate.argtypes = [C.c_void_p, C.c_size_t]
        cls.lib.lookup.argtypes = [C.c_void_p, C.c_size_t, C.c_void_p, C.c_uint, C.POINTER(Resource)]
        assert cls.lib.resource_size() == C.sizeof(Resource)
        cls.fixture = cls.work / 'cmd-db.bin'
        cls.fixture.write_bytes(database())
        actual = added_file('redfin_rpmh.c')
        actual = '\n'.join(line for line in actual.splitlines() if not line.startswith('#include'))
        barrier = '__asm__ volatile("dmb oshld" ::: "memory");'
        assert actual.count(barrier) == 1
        actual = actual.replace(barrier, '__asm__ volatile("" ::: "memory");')
        load = '*(const volatile uint32_t *)(base + offset)'
        assert actual.count(load) == 1
        actual = actual.replace(load, 'model_read(base, offset)')
        harness = r'''
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <assert.h>
#include "redfin_rpmh.h"
#define ARM64_BOARD_CONFIG_SWEET 1
#define kSuccess 0
typedef uintptr_t vm_offset_t;
typedef size_t vm_size_t;
typedef uintptr_t DTEntry;
static unsigned mode,cpus,board,ready,fail_map,maps,variant,irq_reads;
static uint8_t db[RF_CMDDB_BYTES],db_before[RF_CMDDB_BYTES];
static uint32_t rsc[0x4000],gic[0x1000],rsc_before[0x4000],gic_before[0x1000];
static uint64_t ram_base,ram_bytes;
static int PE_parse_boot_argn(const char *name,void *out,int size)
{
 assert(size==4);uint32_t v;
 if(!strcmp(name,"redfinrpmh"))v=mode;else{assert(!strcmp(name,"cpus"));v=cpus;}
 memcpy(out,&v,4);return v!=0;
}
int redfin_spmi_return_ready(void){return ready;}
static int SecureDTLookupEntry(void *unused,const char *path,DTEntry *entry)
{(void)unused;*entry=!strcmp(path,"/") ? 1 : 2;return 0;}
static int SecureDTGetProperty(DTEntry entry,const char *key,const void **raw,unsigned *size)
{
 static const char compatible[]="D22AP\0iPhone10,3\0google,redfin\0qcom,sm7250";
 if(entry==1){assert(!strcmp(key,"compatible"));*raw=board ? "google,redfin-clone" : compatible;*size=board ? sizeof("google,redfin-clone") : sizeof(compatible);return 0;}
 assert(entry==2);
 if(!strcmp(key,"dram-base"))*raw=&ram_base;else{assert(!strcmp(key,"dram-size"));*raw=&ram_bytes;}
 *size=8;return 0;
}
vm_offset_t ml_io_map_wcomb(vm_offset_t pa,vm_size_t bytes)
{assert(pa==0x80860000 && bytes==RF_CMDDB_BYTES);maps++;return fail_map==maps ? 0 : (vm_offset_t)db;}
vm_offset_t ml_io_map(vm_offset_t pa,vm_size_t bytes)
{
 maps++;if(fail_map==maps)return 0;
 if(pa==0x18220000 && bytes==0x10000)return (vm_offset_t)rsc;
 assert(pa==0x17a00000 && bytes==0x4000);return (vm_offset_t)gic;
}
static uint32_t model_read(vm_offset_t base,unsigned offset)
{
 assert(!(offset&3));
 if(base==(vm_offset_t)rsc){
  assert(offset<sizeof(rsc));
  if(offset==0xd00 && ++irq_reads==2 && variant==16)return 1;
  return rsc[offset/4];
 }
 assert(base==(vm_offset_t)gic && offset<sizeof(gic));return gic[offset/4];
}
ACTUAL
int main(int argc,char **argv)
{
 assert(argc==3);variant=(unsigned)strtoul(argv[1],NULL,0);
 FILE *input=fopen(argv[2],"rb");assert(input && fread(db,1,sizeof(db),input)==sizeof(db));fclose(input);
 mode=1;cpus=1;ready=1;ram_base=0x180000000ULL;ram_bytes=0x80000000;
 rsc[0]=1u<<16;rsc[0xc/4]=(16u<<27)|(8u<<12);
 for(unsigned t=0;t<8;t++)rsc[(0xd00+0x2a0*t+0x18)/4]=1;
 switch(variant){
 case 1:mode=0;break;case 2:mode=2;break;case 3:cpus=2;break;
 case 4:ready=0;break;case 5:board=1;break;
 case 6:ram_base=0x80860000;break;case 7:ram_bytes=~0ULL;break;
 case 8:db[4]=0;break;case 9:rsc[0]=3u<<16;break;
 case 10:rsc[0xc/4]=0xffffffffu;break;case 11:gic[0x104/4]=0xffffffffu;break;
 case 12:fail_map=1;break;case 13:fail_map=2;break;case 14:fail_map=3;break;
 case 15:
  rsc[(0xd00+0x1c)/4]=1;rsc[(0xd00+0x10)/4]=1;
  rsc[(0xd00+0x30)/4]=0x10108;rsc[(0xd00+0x34)/4]=0x40000;
  rsc[(0xd00+0x38)/4]=3300;rsc[(0xd00+0x3c)/4]=0x10100;break;
 case 17:rsc[(0xd00+0x1c)/4]=1u<<16;break;
 case 18:gic[0x104/4]=1u<<5;gic[0x204/4]=1u<<5;gic[0x304/4]=1u<<5;break;
 case 19:rsc[0xc/4]=(17u<<27)|(8u<<12);break;
 case 20:rsc[0xc/4]=(16u<<27)|(7u<<12);break;
 case 21:rsc[0xc/4]=(16u<<27)|(10u<<12);break;
 case 22:rsc[0xc/4]=8u<<12;break;
 }
 memcpy(db_before,db,sizeof(db));memcpy(rsc_before,rsc,sizeof(rsc));memcpy(gic_before,gic,sizeof(gic));
 int result=redfin_rpmh_probe();unsigned first_maps=maps;
 int repeated=redfin_rpmh_probe();assert(maps==first_maps);
 assert(!memcmp(db,db_before,sizeof(db)) && !memcmp(rsc,rsc_before,sizeof(rsc)) && !memcmp(gic,gic_before,sizeof(gic)));
 printf("RESULT=%d MAPS=%u REPEATED=%d\n",result,maps,repeated);
 return 0;
}
'''
        source = cls.work / 'observer.c'
        source.write_text(harness.replace('ACTUAL', actual))
        cls.executable = cls.work / 'observer'
        subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=undefined', str(source), '-o', str(cls.executable)],
                       check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def validate(self, data, length=None):
        before = bytes(data)
        value = C.create_string_buffer(before)
        result = self.lib.validate(value, len(data) if length is None else length)
        self.assertEqual(value.raw[:len(data)], before)
        return result

    def lookup(self, data, name, kind):
        value = C.create_string_buffer(bytes(data))
        key = C.create_string_buffer(name.encode().ljust(8, b'\0'), 8)
        result = Resource()
        status = self.lib.lookup(value, len(data), key, kind, C.byref(result))
        self.assertEqual(value.raw[:len(data)], bytes(data))
        return status, result

    def observer(self, variant):
        result = subprocess.run([str(self.executable), str(variant), str(self.fixture)],
                                check=True, text=True, capture_output=True)
        last = result.stdout.splitlines()[-1]
        fields = dict(part.split('=') for part in last.split())
        return {key: int(value) for key, value in fields.items()}, result.stdout

    def test_typed_resource_lookup_reports_exact_names_types_priorities_and_raw_aux(self):
        data = database()
        self.assertEqual(self.validate(data), 0)
        for kind, names in ((3, ARC_NAMES), (4, VRM_NAMES)):
            for i, name in enumerate(names):
                status, resource = self.lookup(data, name, kind)
                self.assertEqual(status, 0)
                self.assertEqual((resource.address, resource.type, tuple(resource.priority)),
                                 ((kind << 16) + 16 * i, kind, (1, 2)))
                self.assertEqual(resource.aux_version, 0x100)
                self.assertEqual(resource.level_count, 4 if kind == 3 else 0)
                if kind == 3:
                    self.assertEqual(tuple(resource.levels[:4]), (0, 48, 128, 384))
        self.assertEqual(self.lookup(data, 'absent', 3)[0], 5)
        self.assertEqual(self.lookup(data, 'xo.lvl', 4)[0], 4)

    def test_header_length_standalone_type_range_and_aux_validation(self):
        data = database()
        for length in (0, 8, 143, DB_BYTES - 1, DB_BYTES + 1):
            self.assertEqual(self.validate(data, length), 1)
        for offset, value, expected in ((0, 2, 2), (4, 0, 2), (140, 1, 2)):
            altered = data.copy(); struct.pack_into('<I', altered, offset, value)
            self.assertEqual(self.validate(altered), expected)
        altered = data.copy(); struct.pack_into('<I', altered, 136, 0xdeadbeef)
        self.assertEqual(self.validate(altered), 0)  # Linux does not authenticate this field.
        for offset, value, expected in ((14, 0xffff, 3), (30, 0xffff, 3)):
            altered = data.copy(); struct.pack_into('<H', altered, offset, value)
            self.assertEqual(self.validate(altered), expected)
        altered = data.copy(); struct.pack_into('<I', altered, 144 + 16, 0x40000)
        self.assertEqual(self.validate(altered), 0)
        self.assertEqual(self.lookup(altered, 'xo.lvl', 3)[0], 4)
        altered = data.copy(); struct.pack_into('<HH', altered, 144 + 20, 0xffff, 0xffff)
        self.assertEqual(self.validate(altered), 3)
        for count in (3, 34):
            altered = data.copy(); struct.pack_into('<H', altered, 144 + 20, count)
            self.assertEqual(self.lookup(altered, 'xo.lvl', 3)[0], 7)

    def test_slave_id_uses_only_address_bits_18_to_16(self):
        data = database()
        for kind, names, headers in ((3, ARC_NAMES, 0), (4, VRM_NAMES, 0x200)):
            for i, name in enumerate(names):
                address = 0xa0c00000 | (kind << 16) | (i * 16)
                struct.pack_into('<I', data, 144 + headers + i * 24 + 16, address)
                status, resource = self.lookup(data, name, kind)
                self.assertEqual(status, 0)
                self.assertEqual((resource.address, resource.type), (address, kind))
        self.assertEqual(self.validate(data), 0)

    def test_unrelated_resource_addresses_and_directory_ids_do_not_define_validity(self):
        data = database()
        # Linux continues through any nonzero directory ID and derives the
        # requested resource's type from its address, not this directory ID.
        struct.pack_into('<H', data, 8, 2)
        struct.pack_into('<I', data, 144 + 24 + 16, 0xffff0001)
        self.assertEqual(self.validate(data), 0)
        self.assertEqual(self.lookup(data, 'xo.lvl', 3)[0], 0)
        self.assertEqual(self.lookup(data, 'cx.lvl', 3)[0], 4)
        # Byte reads allow an unaligned, structurally bounded entry array.
        moved = data[144:144 + 4 * 24]
        struct.pack_into('<H', data, 10, 0x101)
        data[144 + 0x101:144 + 0x101 + len(moved)] = moved
        self.assertEqual(self.lookup(data, 'xo.lvl', 3)[0], 0)

    def test_first_zero_directory_terminates_before_later_garbage(self):
        data = database()
        struct.pack_into('<H', data, 24, 0)
        struct.pack_into('<4H', data, 40, 4, 0xffff, 0xffff, 0xffff)
        self.assertEqual(self.validate(data), 0)
        self.assertEqual(self.lookup(data, 'xo.lvl', 3)[0], 0)
        self.assertEqual(self.lookup(data, 'ldoa17', 4)[0], 5)

    def test_entry_count_is_bounded_by_reserved_buffer_instead_of_arbitrary_512(self):
        data = database()
        struct.pack_into('<H', data, 14, 513)
        struct.pack_into('<H', data, 24, 0)
        data[144 + 4 * 24:] = bytes(DB_BYTES - 144 - 4 * 24)
        self.assertEqual(self.validate(data), 0)
        self.assertEqual(self.lookup(data, 'xo.lvl', 3)[0], 0)

    def test_duplicate_keys_and_last_aux_word_are_bounded(self):
        data = database()
        data[144 + 24:144 + 32] = data[144:152]
        self.assertEqual(self.lookup(data, 'xo.lvl', 3)[0], 6)
        data = database()
        struct.pack_into('<H', data, 8 + 4, 0xffff)
        struct.pack_into('<HH', data, 144 + 20, 2, DB_BYTES - 144 - 0xffff - 2)
        struct.pack_into('<H', data, DB_BYTES - 2, 0xabcd)
        status, result = self.lookup(data, 'xo.lvl', 3)
        self.assertEqual(status, 0)
        self.assertEqual((result.level_count, result.levels[0]), (1, 0xabcd))
        struct.pack_into('<H', data, 144 + 20, 4)
        self.assertEqual(self.validate(data), 3)

    def test_mutated_firmware_metadata_never_modifies_the_snapshot(self):
        rng = random.Random(7250)
        for _ in range(300):
            data = database()
            offset = rng.choice((8, 10, 12, 14, 24, 26, 28, 30, 164, 166, 188, 190))
            struct.pack_into('<H', data, offset, rng.randrange(0x10000))
            self.validate(data)
            self.lookup(data, 'xo.lvl', 3)

    def test_probe_default_unknown_modes_and_platform_return_up_ram_guards_do_not_map(self):
        for variant in range(1, 8):
            fields, _ = self.observer(variant)
            self.assertEqual(fields['MAPS'], 0)
            self.assertEqual(fields['RESULT'], errno.ENOTSUP if variant <= 2 else errno.ENXIO)

    def test_probe_mapping_and_geometry_failures_stop_before_later_regions(self):
        for variant, maps, error in ((8, 1, errno.EINVAL), (9, 2, errno.ENOTSUP),
                                    (10, 2, errno.ENOTSUP), (11, 3, errno.EIO),
                                    (12, 1, errno.ENOMEM), (13, 2, errno.ENOMEM), (14, 3, errno.ENOMEM),
                                    (17, 3, errno.EIO), (19, 2, errno.ENOTSUP), (20, 2, errno.ENOTSUP),
                                    (21, 2, errno.ENOTSUP), (22, 2, errno.ENOTSUP)):
            with self.subTest(variant=variant):
                fields, _ = self.observer(variant)
                self.assertEqual((fields['MAPS'], fields['RESULT'], fields['REPEATED']),
                                 (maps, error, errno.EBUSY))
        _, log = self.observer(8)
        self.assertIn('rejected CMD-DB dir0 slv=3 entries=0 aux=0x400 count=4 version=0x100', log)

    def test_probe_reports_only_observed_empty_slots_inherited_requests_and_irq_state(self):
        fields, log = self.observer(0)
        self.assertEqual((fields['MAPS'], fields['RESULT'], fields['REPEATED']), (3, 0, errno.EBUSY))
        self.assertIn('ACTIVE-empty-mask=0x3', log)
        self.assertIn('no ownership/votes/IRQ changes', log)
        self.assertEqual(log.count('REDFIN RPMH: resource '), 8)
        _, log = self.observer(15)
        self.assertIn('ACTIVE-empty-mask=0x2', log)
        self.assertIn('inherited TCS0 cmd0 ldoa17+0 data=0xce4', log)
        _, log = self.observer(18)
        self.assertIn('IRQ37 GIC-enabled=1 pending=1 active=1', log)

    def test_probe_marks_changing_rsc_snapshot_without_retry_or_writes(self):
        fields, log = self.observer(16)
        self.assertEqual(fields['RESULT'], errno.EAGAIN)
        self.assertIn('stable=0', log)


if __name__ == '__main__':
    unittest.main()
