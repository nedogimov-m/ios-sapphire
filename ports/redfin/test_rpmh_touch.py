"""Run the actual one-shot RPMh touch voter against bounded register/rail models."""
import ctypes as C
import errno
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

try:
    from ports.redfin.test_rpmh_probe import added_file as rpmh_file, database
except ModuleNotFoundError as error:
    if error.name != 'ports':
        raise
    from test_rpmh_probe import added_file as rpmh_file, database

HERE = Path(__file__).resolve().parent


def patch_file(patch, name):
    text = (HERE / patch).read_text()
    section = text.split('+++ b/bsd/dev/' + name + '\n', 1)[1].split('diff --git ', 1)[0]
    return '\n'.join(line[1:] for line in section.splitlines() if line.startswith('+')) + '\n'


PREFIX = r'''
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include "redfin_rpmh.h"
#include "redfin_rpmh_touch.h"
#define printf(...) ((void)0)
#define ARM64_BOARD_CONFIG_SWEET 1
#define kSuccess 0
typedef uintptr_t vm_offset_t;
typedef size_t vm_size_t;
typedef uintptr_t DTEntry;
static uint8_t db[RF_CMDDB_BYTES];
static uint32_t rsc[0x10000/4],gic[0x4000/4],hits[0x10000/4];
static uint32_t offsets[32],values[32];
static unsigned maps,reads,writes,bad,rail_calls,delay1,delay100,polls;
static int ready,platform,failmap,rail_mode,post_mode,fail_rail_at,drop_at,completion;
static unsigned mutate_offset,mutate_hit;
static uint32_t mutate_value;
static bool triggered,completed;
static uint64_t ram_base,ram_size;
static char root_arg[16];
static bool root_present;
static int context_token;
struct host_arg { const char *name; uint32_t value; bool present; };
static struct host_arg args[]={
 {"redfinrpmhtouch",1,true},{"redfintouch",2,true},{"redfintouchsetup",1,true},{"cpus",1,true},
 {"redfinroot",0,true},{"sweethw",0,true},{"sweetkeys",0,true},{"sweetbattery",0,true},
 {"sweetusb",0,true},{"modem",0,true},{"wifi",0,true},{"gpu",0,true},
 {"redfingpu",0,true},{"redfinwifi",0,true},{"redfinusb",0,true}
};
static bool PE_parse_boot_argn(const char *key,void *out,size_t size)
{
 if (!strcmp(key,"rd")) {
  if (!root_present) return false;
  if (size!=16) { bad++;return false; }
  memcpy(out,root_arg,size);return true;
 }
 for (unsigned i=0;i<sizeof(args)/sizeof(args[0]);i++) if (!strcmp(key,args[i].name)) {
  if (!args[i].present) return false;
  if (size!=4) { bad++;return false; }
  memcpy(out,&args[i].value,4);return true;
 }
 bad++;return false;
}
int redfin_spmi_return_ready(void) { return ready; }
static int SecureDTLookupEntry(void *unused,const char *name,DTEntry *entry)
{
 (void)unused;if(platform==4)return -1;
 if(!strcmp(name,"/")){*entry=1;return 0;}
 if(!strcmp(name,"/chosen")){*entry=2;return 0;}
 bad++;return -1;
}
static int SecureDTGetProperty(DTEntry entry,const char *name,const void **out,unsigned *size)
{
 static const char compatible[]="google,redfin\0qcom,sm7250";
 if(entry==1 && !strcmp(name,"compatible")) {
  if(platform==1){*out="google,redfin-clone";*size=sizeof("google,redfin-clone");}
  else if(platform==2){*out="google,redfin";*size=sizeof("google,redfin");}
  else if(platform==3){*out=compatible;*size=sizeof(compatible)-1;}
  else {*out=compatible;*size=sizeof(compatible);}
  return 0;
 }
 if(entry==2 && !strcmp(name,"dram-base")){*out=&ram_base;*size=platform==5?4:8;return 0;}
 if(entry==2 && !strcmp(name,"dram-size")){*out=&ram_size;*size=platform==6?4:8;return 0;}
 bad++;return -1;
}
vm_offset_t ml_io_map_wcomb(vm_offset_t pa,vm_size_t size)
{
 maps++;if(pa!=0x80860000 || size!=RF_CMDDB_BYTES)bad++;
 return maps==(unsigned)failmap?0:(vm_offset_t)db;
}
vm_offset_t ml_io_map(vm_offset_t pa,vm_size_t size)
{
 maps++;
 if(pa==0x18220000 && size==0x10000)return maps==(unsigned)failmap?0:(vm_offset_t)rsc;
 if(pa==0x17a00000 && size==0x4000)return maps==(unsigned)failmap?0:(vm_offset_t)gic;
 bad++;return 0;
}
static void delay(unsigned us)
{ if(us==1)delay1++;else if(us==100)delay100++;else bad++; }
static void model_barrier(void) {}
static bool valid_rsc_read(unsigned offset)
{
 if(offset==0 || offset==0xc || offset==0xd00 || offset==0xd04)return true;
 for(unsigned t=0;t<8;t++){
  unsigned base=0xd00+0x2a0*t;
  if(offset==base+0x10 || offset==base+0x14 || offset==base+0x18 || offset==base+0x1c)return true;
  for(unsigned n=0;n<16;n++){
   unsigned cmd=base+0x30+n*0x14;
   if(offset==cmd || offset==cmd+4 || offset==cmd+8 || (t==0 && n<3 && offset==cmd+12))return true;
  }
 }
 return false;
}
static void finish_model(void)
{
 if(!triggered)return;
 polls++;
 if(completion==1)return; /* old complete status without a fresh local IRQ */
 rsc[0xd04/4]=completion==3?3:1;
 rsc[(0xd00+0x18)/4]=completion==4?0:1;
 for(unsigned n=0;n<3;n++)rsc[(0xd00+0x3c+n*0x14)/4]=
  completion==2?0:(completion==5?0xffffffffu:0x10100);
 if(completion==8)rsc[0xd64/4]=0;
 if(completion==9)rsc[0xd3c/4]=0x100;
 if(completion==10)rsc[0xd50/4]=0x10000;
 completed=completion==0;
}
static uint32_t model_read(vm_offset_t base,unsigned offset)
{
 reads++;
 if(offset&3){bad++;return 0;}
 if(base==(vm_offset_t)rsc && offset<sizeof(rsc)){
  if(!valid_rsc_read(offset))bad++;
  if(++hits[offset/4]==mutate_hit && offset==mutate_offset)rsc[offset/4]=mutate_value;
  if(triggered && completion==7 && offset==0xd00)return rsc[offset/4]^2;
  if(offset==0xd04)finish_model();
  return rsc[offset/4];
 }
 if(base==(vm_offset_t)gic && (offset==0x104 || offset==0x204 || offset==0x304)){
  if(triggered && completion==6 && offset==0x104)return gic[offset/4]|(1u<<5);
  return gic[offset/4];
 }
 bad++;return 0;
}
static void expected_write(unsigned n,unsigned *offset,uint32_t *value)
{
 const uint32_t address[]={0x41300,0x41308,0x41304},data[]={3304,7,1};
 if(n<9){unsigned cmd=n/3,part=n%3;*offset=0xd30+cmd*0x14+part*4;
  *value=part==0?0x10108:(part==1?address[cmd]:data[cmd]);return;}
 const unsigned off[]={0xd10,0xd1c,0xd14,0xd14,0xd14,0xd14,0xd14,0xd1c,0xd10,0xd08};
 const uint32_t val[]={7,7,0,0x10000,0x1010000,0x10000,0,0,0,1};
 if(n>=19){bad++;*offset=0;*value=0;return;}
 *offset=off[n-9];*value=val[n-9];
}
static void model_write(vm_offset_t base,unsigned offset,uint32_t value)
{
 unsigned expected_offset;uint32_t expected_value;
 expected_write(writes,&expected_offset,&expected_value);
 if(base!=(vm_offset_t)rsc || offset!=expected_offset || value!=expected_value)bad++;
 if(writes<32){offsets[writes]=offset;values[writes]=value;}writes++;
 if(writes==(unsigned)drop_at)return;
 if(offset==0xd08){rsc[0xd04/4]=0;triggered=false;return;}
 if(offset>=sizeof(rsc) || (offset&3)){bad++;return;}
 rsc[offset/4]=value;
 if(offset==0xd14 && value==0x1010000){triggered=true;}
}
static int physical(void *context,struct redfin_touch_rail_state *out)
{
 rail_calls++;if(context!=&context_token){bad++;return EINVAL;}
 if(rail_calls==(unsigned)fail_rail_at)return EIO;
 *out=(struct redfin_touch_rail_state){.index_verified=true,.pmic_type=0x51,.pmic_subtype=0x1e,
  .sid=1,.peripheral_type=4,.peripheral_subtype=0x7d,.base=0x5000,
  .millivolts=3304,.valid_millivolts=3200,.mode=7,.enable=0,.status=3};
 switch(rail_mode){
 case 1:out->index_verified=false;break;case 2:out->pmic_type=0x50;break;
 case 3:out->pmic_subtype=0x1f;break;case 4:out->sid=0;break;case 5:out->base=0x5100;break;
 case 6:out->peripheral_type=3;break;case 7:out->peripheral_subtype=0x23;break;
 case 8:out->millivolts=3300;break;case 9:out->millivolts=3400;break;
 case 10:out->mode=4;break;case 11:out->enable=1;break;case 12:out->status=0x20;break;
 case 13:out->status=0x83;break;
 case 14:case 15:case 16:out->enable=0x80;out->status=0x83;
  out->valid_millivolts=rail_mode==15?3300:3304;if(rail_mode==16)out->status=3;break;
 case 17:if(rail_calls==2)out->millivolts=3303;break;
 case 18:if(rail_calls==3)out->mode=4;break;
 default:break;
 }
 if(rail_calls>=4 && completed){
  out->enable=0x80;out->status=0x83;out->valid_millivolts=3304;
  switch(post_mode){case 1:out->enable=0;out->status=3;break;
  case 2:out->valid_millivolts=3300;break;case 3:out->millivolts=3400;break;
  case 4:out->status=0xa3;break;case 5:out->status=rail_calls&1?0x80:0x83;break;
  case 6:out->index_verified=false;break;case 7:out->mode=4;break;default:break;}
 }
 return 0;
}
'''


SUFFIX = r'''
void host_reset(const void *fixture)
{
 memcpy(db,fixture,sizeof(db));memset(rsc,0,sizeof(rsc));memset(gic,0,sizeof(gic));memset(hits,0,sizeof(hits));
 memset(offsets,0,sizeof(offsets));memset(values,0,sizeof(values));
 maps=reads=writes=bad=rail_calls=delay1=delay100=polls=0;
 ready=1;platform=failmap=rail_mode=post_mode=fail_rail_at=drop_at=completion=0;
 mutate_offset=mutate_hit=mutate_value=0;triggered=completed=false;
 ram_base=0x180000000ULL;ram_size=0x80000000;
 memset(root_arg,0,sizeof(root_arg));memcpy(root_arg,"md0",3);root_present=true;
 for(unsigned i=0;i<sizeof(args)/sizeof(args[0]);i++){args[i].present=true;args[i].value=i==1?2:(i<4?1:0);}
 rt_attempted=rt_poisoned=false;
 rsc[0]=1u<<16;rsc[0xc/4]=(16u<<27)|(8u<<12);rsc[0xd00/4]=1;
 for(unsigned t=0;t<8;t++)rsc[(0xd00+0x2a0*t+0x18)/4]=1;
 for(unsigned t=2;t<7;t++){
  unsigned at=0xd00+0x2a0*t;rsc[(at+0x10)/4]=1;rsc[(at+0x1c)/4]=1;rsc[(at+0x14)/4]=0x10000;
  rsc[(at+0x30)/4]=0x10108;
  const uint32_t addresses[]={0x41300,0x41308,0x41304,0x4130c,0x42100};
  const uint32_t data[]={3304,7,1,900,5000};
  rsc[(at+0x34)/4]=addresses[t-2];rsc[(at+0x38)/4]=data[t-2];
 }
 for(unsigned n=0;n<3;n++)rsc[(0xd3c+n*0x14)/4]=0x10100; /* stale inherited completion */
}
void host_arg(const char *name,uint32_t value,int present)
{
 for(unsigned i=0;i<sizeof(args)/sizeof(args[0]);i++)if(!strcmp(name,args[i].name)){
  args[i].value=value;args[i].present=present;return;
 }
 bad++;
}
void host_root(const char *name,int present)
{memset(root_arg,0,sizeof(root_arg));size_t n=strlen(name);if(n>16)n=16;memcpy(root_arg,name,n);root_present=present;}
void host_config(unsigned key,uint64_t value)
{
 switch(key){case 0:ready=value;break;case 1:platform=value;break;case 2:failmap=value;break;
 case 3:rail_mode=value;break;case 4:post_mode=value;break;case 5:fail_rail_at=value;break;
 case 6:drop_at=value;break;case 7:completion=value;break;case 8:ram_base=value;break;
 case 9:ram_size=value;break;case 10:mutate_offset=value;break;case 11:mutate_hit=value;break;
 case 12:mutate_value=value;break;default:bad++;break;}
}
void host_reg(unsigned region,unsigned offset,uint32_t value)
{
 if(region==0 && offset<sizeof(rsc) && !(offset&3))rsc[offset/4]=value;
 else if(region==1 && offset<sizeof(gic) && !(offset&3))gic[offset/4]=value;
 else if(region==2 && offset<sizeof(db) && !(offset&3))memcpy(db+offset,&value,4);
 else bad++;
}
const void *host_page(unsigned region){return region==0?(void *)rsc:(region==1?(void *)gic:(void *)db);}
int host_prepare(unsigned variant)
{
 struct redfin_touch_rail_ops ops={.initial_md0_drv2_lease=variant!=2,.read=variant==3?NULL:physical,.context=&context_token};
 return redfin_rpmh_touch_prepare(variant==1?NULL:&ops);
}
unsigned host_stat(unsigned key)
{
 switch(key){case 0:return maps;case 1:return reads;case 2:return writes;case 3:return bad;
 case 4:return rail_calls;case 5:return delay1;case 6:return delay100;case 7:return polls;
 case 8:return rt_attempted;case 9:return rt_poisoned;default:return 0;}
}
uint32_t host_write(unsigned n,unsigned field){return n<32?(field?values[n]:offsets[n]):0;}
'''


class RpmhTouchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        for name, patch in (('redfin_touch_rail.h', 'touch-rail-ready.patch'),
                            ('redfin_rpmh_touch.h', 'rpmh-touch.patch')):
            (root / name).write_text(patch_file(patch, name))
        (root / 'redfin_rpmh.h').write_text(rpmh_file('redfin_rpmh.h'))
        code = patch_file('rpmh-touch.patch', 'redfin_rpmh_touch.c')
        code = '\n'.join(line for line in code.splitlines() if not line.startswith('#include '))
        seams = {
            '*(const volatile uint32_t *)(base + offset)': 'model_read(base,offset)',
            '*(volatile uint32_t *)(base + offset) = value;': 'model_write(base,offset,value);',
            '__asm__ volatile("dmb oshld" ::: "memory");': 'model_barrier();',
            '__asm__ volatile("dmb oshst" ::: "memory");': 'model_barrier();',
            '__asm__ volatile("dsb osh" ::: "memory");': 'model_barrier();',
        }
        for old, new in seams.items():
            if code.count(old) != 1:
                raise AssertionError('actual C model seam changed: ' + old)
            code = code.replace(old, new)
        source = root / 'touch.c'
        source.write_text(PREFIX + code + SUFFIX)
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            raise RuntimeError('actual-C RPMh tests require a C compiler')
        result = subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                                 '-shared', '-fPIC', str(source), '-o', str(root / 'touch.so')],
                                capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        cls.lib = C.CDLL(str(root / 'touch.so'))
        cls.lib.host_reset.argtypes = [C.c_void_p]
        cls.lib.host_arg.argtypes = [C.c_char_p, C.c_uint32, C.c_int]
        cls.lib.host_root.argtypes = [C.c_char_p, C.c_int]
        cls.lib.host_config.argtypes = [C.c_uint, C.c_uint64]
        cls.lib.host_reg.argtypes = [C.c_uint, C.c_uint, C.c_uint32]
        cls.lib.host_page.restype = C.c_void_p
        cls.lib.host_write.restype = C.c_uint32
        fixture = database()
        struct.pack_into('<I', fixture, 144+0x200+16, 0x41300)
        cls.fixture = C.create_string_buffer(bytes(fixture))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.reset()

    def tearDown(self):
        self.assertEqual(self.stat(3), 0, 'out-of-contract mapping, MMIO, write order, or callback')

    def reset(self):
        self.lib.host_reset(self.fixture)

    def stat(self, key):
        return self.lib.host_stat(key)

    def config(self, key, value):
        self.lib.host_config(key, value)

    def reg(self, region, offset, value):
        self.lib.host_reg(region, offset, value)

    def images(self):
        return tuple(C.string_at(self.lib.host_page(region), size)
                     for region, size in ((0, 0x10000), (1, 0x4000), (2, 0x20000)))

    def fail_no_writes(self):
        self.assertNotEqual(self.lib.host_prepare(0), 0)
        self.assertEqual(self.stat(2), 0)

    def one_shot(self):
        before = tuple(self.stat(key) for key in range(7))
        self.assertNotEqual(self.lib.host_prepare(0), 0)
        self.assertEqual(tuple(self.stat(key) for key in range(7)), before)

    def test_trusted_initial_owner_and_reader_required(self):
        for variant in (1, 2, 3):
            with self.subTest(variant=variant):
                self.reset()
                self.assertNotEqual(self.lib.host_prepare(variant), 0)
                self.assertEqual(tuple(self.stat(k) for k in (0, 1, 2, 4)), (0, 0, 0, 0))

    def test_explicit_modes_and_single_cpu(self):
        for name, wrong in ((b'redfinrpmhtouch', 0), (b'redfintouch', 1),
                            (b'redfintouchsetup', 0), (b'cpus', 2)):
            for present in (0, 1):
                with self.subTest(name=name, present=present):
                    self.reset()
                    self.lib.host_arg(name, wrong, present)
                    self.fail_no_writes()
                    self.assertEqual(self.stat(0), 0)

    def test_every_competing_path_is_disabled(self):
        for name in (b'redfinroot', b'sweethw', b'sweetkeys', b'sweetbattery', b'sweetusb',
                     b'modem', b'wifi', b'gpu', b'redfingpu', b'redfinwifi', b'redfinusb'):
            with self.subTest(name=name):
                self.reset()
                self.lib.host_arg(name, 1, 1)
                self.fail_no_writes()
                self.assertEqual((self.stat(0), self.stat(4)), (0, 0))

    def test_md0_and_return_proof(self):
        for root, present in ((b'md0', 0), (b'disk0s1', 1), (b'md0x', 1)):
            with self.subTest(root=root, present=present):
                self.reset()
                self.lib.host_root(root, present)
                self.fail_no_writes()
                self.assertEqual(self.stat(0), 0)
        self.reset()
        self.config(0, 0)
        self.fail_no_writes()
        self.assertEqual(self.stat(0), 0)

    def test_platform_and_ram_alias_guards(self):
        for platform in range(1, 7):
            with self.subTest(platform=platform):
                self.reset()
                self.config(1, platform)
                self.fail_no_writes()
                self.assertEqual(self.stat(0), 0)
        for base, size in ((0, 0x4000), (0x180000001, 0x4000), (0x180000000, 0),
                           (0x180000000, 1), (1 << 36, 0x4000), ((1 << 36)-0x4000, 0x8000),
                           (0x80860000, 0x20000), (0x18220000, 0x10000), (0x17a00000, 0x4000)):
            with self.subTest(base=base, size=size):
                self.reset()
                self.config(8, base)
                self.config(9, size)
                self.fail_no_writes()
                self.assertEqual(self.stat(0), 0)

    def test_fresh_verified_identity_exact_configured_floor_and_enable_consistency(self):
        for mode in tuple(range(1, 14)) + (15, 16):
            with self.subTest(mode=mode):
                self.reset()
                self.config(3, mode)
                self.fail_no_writes()
                self.assertEqual(self.stat(0), 0)
                self.one_shot()

    def test_already_powered_two_fresh_samples_need_no_maps_or_votes(self):
        self.config(3, 14)
        before = self.images()
        self.assertEqual(self.lib.host_prepare(0), 0)
        self.assertEqual(tuple(self.stat(k) for k in (0, 1, 2, 4)), (0, 0, 0, 2))
        self.assertEqual(self.images(), before)
        self.one_shot()

    def test_changed_pre_samples_and_last_physical_check_refuse_vote(self):
        for mode in (17, 18):
            with self.subTest(mode=mode):
                self.reset()
                self.config(3, mode)
                self.fail_no_writes()
                self.one_shot()
        for call in (1, 2, 3):
            with self.subTest(call=call):
                self.reset()
                self.config(5, call)
                self.fail_no_writes()
                self.one_shot()

    def test_cmddb_identity_and_mapping_failures(self):
        for offset, value in ((4, 0), (144+0x200+16, 0x41310), (144+0x200, 0)):
            with self.subTest(offset=offset):
                self.reset()
                self.reg(2, offset, value)
                self.fail_no_writes()
                self.one_shot()
        for mapping in (1, 2, 3):
            with self.subTest(mapping=mapping):
                self.reset()
                self.config(2, mapping)
                self.fail_no_writes()
                self.one_shot()

    def test_rsc_format_local_irq_and_gic_ownership(self):
        cases = ((0, 0, 3 << 16), (0, 0xc, 0xffffffff), (0, 0xc, (2 << 27)|(8 << 12)),
                 (0, 0xc, (16 << 27)|(7 << 12)), (0, 0xc, (16 << 27)|(10 << 12)),
                 (0, 0xd00, 0), (0, 0xd00, 0xffffffff), (0, 0xd04, 1))
        cases += tuple((1, offset, value) for offset in (0x104, 0x204, 0x304)
                       for value in (1 << 5, 0xffffffff))
        for region, offset, value in cases:
            with self.subTest(region=region, offset=offset, value=value):
                self.reset()
                self.reg(region, offset, value)
                self.fail_no_writes()
                self.one_shot()

    def test_all_inherited_slots_idle_and_active_slots_empty(self):
        cases = [(0xd00+t*0x2a0+0x18, 0) for t in range(8)]
        cases += [(0xd00+t*0x2a0+offset, 1) for t in (0, 1) for offset in (0x10, 0x14, 0x1c)]
        cases += [(0xd00+2*0x2a0+0x1c, 1 << 16)]
        for offset, value in cases:
            with self.subTest(offset=offset):
                self.reset()
                self.reg(0, offset, value)
                self.fail_no_writes()

    def test_inherited_target_votes_cannot_raise_floor_or_use_unknown_mode(self):
        cmd = 0xd00+2*0x2a0+0x30
        cases = ((0x41300, 3305, 0x10108), (0x41304, 2, 0x10108),
                 (0x41308, 5, 0x10108), (0x41301, 0, 0x10108), (0x41300, 3304, 0x108))
        for address, data, message in cases:
            with self.subTest(address=address, data=data, message=message):
                self.reset()
                for offset, value in ((cmd, message), (cmd+4, address), (cmd+8, data)):
                    self.reg(0, offset, value)
                self.fail_no_writes()

    def test_inherited_command_recheck_detects_mutation(self):
        for offset, value in ((0xd00+2*0x2a0+0x38, 3303), (0xd00+2*0x2a0+0x10, 0),
                              (0xd00+2*0x2a0+0x34, 0x42100)):
            with self.subTest(offset=offset):
                self.reset()
                self.config(10, offset)
                self.config(11, 2)
                self.config(12, value)
                self.fail_no_writes()

    def test_exact_success_sequence_preserves_unowned_slots_and_no_unvote(self):
        before = self.images()
        self.assertEqual(self.lib.host_prepare(0), 0)
        self.assertEqual(tuple(self.stat(k) for k in (0, 2, 4, 8, 9)), (3, 19, 5, 1, 0))
        writes = [(self.lib.host_write(i, 0), self.lib.host_write(i, 1)) for i in range(19)]
        expected = []
        for n, (address, data) in enumerate(((0x41300, 3304), (0x41308, 7), (0x41304, 1))):
            expected.extend(((0xd30+n*0x14, 0x10108), (0xd34+n*0x14, address), (0xd38+n*0x14, data)))
        expected += [(0xd10, 7), (0xd1c, 7), (0xd14, 0), (0xd14, 0x10000),
                     (0xd14, 0x1010000), (0xd14, 0x10000), (0xd14, 0), (0xd1c, 0), (0xd10, 0), (0xd08, 1)]
        self.assertEqual(writes, expected)
        after = self.images()
        self.assertEqual(after[1:], before[1:])
        allowed = {offset for offset, _ in expected} | {0xd04, 0xd18, 0xd3c, 0xd50, 0xd64}
        for offset in range(0, 0x10000, 4):
            if offset not in allowed:
                self.assertEqual(after[0][offset:offset+4], before[0][offset:offset+4], hex(offset))
        self.one_shot()

    def test_each_readback_failure_is_bounded_and_never_cleaned_up(self):
        for nth in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 16, 17, 18):
            with self.subTest(nth=nth):
                self.reset()
                self.config(6, nth)
                self.assertNotEqual(self.lib.host_prepare(0), 0)
                self.assertEqual(self.stat(2), nth)
                self.assertEqual(self.stat(5), 1000)
                self.assertEqual(self.stat(9), 1)
                self.one_shot()

    def test_stale_status_and_idle_cannot_replace_fresh_completion_irq(self):
        self.config(7, 1)
        self.assertEqual(self.lib.host_prepare(0), errno.ETIMEDOUT)
        self.assertEqual((self.stat(2), self.stat(5), self.stat(7), self.stat(9)), (14, 100000, 100000, 1))
        self.one_shot()

    def test_completion_requires_all_command_status_and_idle(self):
        for mode in (2, 4, 8, 9, 10):
            with self.subTest(mode=mode):
                self.reset()
                self.config(7, mode)
                self.assertEqual(self.lib.host_prepare(0), errno.ETIMEDOUT)
                self.assertEqual((self.stat(2), self.stat(5), self.stat(9)), (14, 100000, 1))
                self.one_shot()

    def test_uncertain_trigger_write_times_out_without_cleanup_or_retry(self):
        self.config(6, 14)
        self.assertEqual(self.lib.host_prepare(0), errno.ETIMEDOUT)
        self.assertEqual((self.stat(2), self.stat(5), self.stat(9)), (14, 100000, 1))
        self.one_shot()

    def test_completion_errors_or_lost_interrupt_ownership_stop_without_cleanup(self):
        for mode in (3, 5, 6, 7):
            with self.subTest(mode=mode):
                self.reset()
                self.config(7, mode)
                self.assertNotEqual(self.lib.host_prepare(0), 0)
                self.assertEqual(self.stat(2), 14)
                self.assertEqual(self.stat(9), 1)
                self.assertLess(self.stat(5), 3)
                self.one_shot()

    def test_irq_clear_failure_keeps_owner_quarantined(self):
        self.config(6, 19)
        self.assertNotEqual(self.lib.host_prepare(0), 0)
        self.assertEqual((self.stat(2), self.stat(9)), (19, 1))
        self.one_shot()

    def test_post_vote_configured_and_valid_power_are_both_required(self):
        for mode in range(1, 8):
            with self.subTest(mode=mode):
                self.reset()
                self.config(4, mode)
                self.assertNotEqual(self.lib.host_prepare(0), 0)
                self.assertEqual((self.stat(2), self.stat(9)), (19, 1))
                self.assertGreaterEqual(self.stat(4), 1003)
                self.one_shot()

    def test_post_vote_reader_failure_retains_vote_and_quarantine(self):
        for call in (4, 5):
            with self.subTest(call=call):
                self.reset()
                self.config(5, call)
                self.assertNotEqual(self.lib.host_prepare(0), 0)
                self.assertEqual((self.stat(2), self.stat(9)), (19, 1))
                self.one_shot()


if __name__ == '__main__':
    unittest.main()
