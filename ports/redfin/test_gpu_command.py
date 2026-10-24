"""Native A620 packets/tables, owned SMMU routes and PAS13 fail-stop behavior."""
import ctypes
import errno
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


def rpmh_header():
    patch = (HERE / 'rpmh-probe.patch').read_text()
    body = patch.split('+++ b/bsd/dev/redfin_rpmh.h\n', 1)[1].split('diff --git ', 1)[0]
    return ''.join(line[1:] for line in body.splitlines(True) if line.startswith('+'))


HARNESS = r'''
#include <stdint.h>
#include <string.h>
#include "redfin_rpmh.h"
#include "include/redfin_gpu_mapping.h"
static uint8_t mem[4][0x8000];
static struct rf_gm_memory data[3],pool;
static struct rf_gm_pt_plan plan;
static struct rf_gmm_lease gmu;
static struct rf_a6_mapping mapping;
static struct rf_gs_snapshot global;
static struct rf_gc_snapshot banks;
static unsigned live,denied,writes,fail_write,samples,fail_sample,bad,published,problem;
static uint64_t now;
static bool valid(void *p){return p==&mapping && live;}
static bool owns(void *p,const struct rf_gm_memory *m,unsigned use){
 if(!valid(p)||denied)return false;
 if(use==2)return m->token==pool.token && m->host==pool.host && m->physical==pool.physical;
 for(unsigned i=0;i<3;i++)if(m->token==data[i].token && m->host==data[i].host && m->physical==data[i].physical)return true;
 return false;
}
static int check(void *p){return valid(p)?0:ECANCELED;}
static int sample(void *p,struct rf_gs_snapshot *g,struct rf_gc_snapshot *b){
 if(!valid(p))return ECANCELED;samples++;if(samples==fail_sample)return EFAULT;*g=global;*b=banks;return 0;
}
static int read_word(void *p,unsigned block,uint32_t at,uint32_t *v){
 if(!valid(p)||block>1)return ECANCELED;
 if(!block){
  if(at==0x1800)*v=global.cba2r[0];else if(at==0x1000)*v=global.cbar[0];
  else if(at>=0x800&&at<0x814)*v=global.smr[(at-0x800)/4];
  else if(at>=0xc00&&at<0xc14)*v=global.s2cr[(at-0xc00)/4];else {bad++;return EINVAL;}
 }else{
  *v=0;for(unsigned i=0;i<RF_GC_WORDS;i++)if(rf_gc_offsets[i]==at)*v=banks.words[0][i];
 }
 return 0;
}
static int write_word(void *p,unsigned block,uint32_t at,uint32_t v){
 if(!valid(p)||!published)return ECANCELED;
 unsigned eb;uint32_t ea,ev;
 if(rf_a6_map_step(&mapping,&plan,mapping.step,&eb,&ea,&ev)||block!=eb||at!=ea||v!=ev)bad++;
 if(++writes==fail_write)return EIO;
 if(!block){
  if(at==0x1800){global.cba2r[0]=v;banks.words[0][8]=0x400;}
  else if(at==0x1000)global.cbar[0]=v;
  else if(at>=0x800&&at<0x814)global.smr[(at-0x800)/4]=v;
  else if(at>=0xc00&&at<0xc14)global.s2cr[(at-0xc00)/4]=v|(problem==6?0x1000000u:0);
  else bad++;
 }else for(unsigned i=0;i<RF_GC_WORDS;i++)if(rf_gc_offsets[i]==at)
  banks.words[0][i]=at==0x10?v|0x60u:at==0?v&~0x1000u:v;
 return 0;
}
static int publish(void *p,const struct rf_gm_pt_plan *t){
 if(!valid(p)||t!=&plan||!owns(p,&t->tables,2))return EACCES;published++;return 0;
}
static int pause_us(void *p,unsigned us){if(!valid(p)||us!=1)bad++;now+=us*1000;return 0;}
static const struct rf_gm_memory_owner owner={&mapping,valid,owns};
static const struct rf_gmm_ops ops={&mapping,check,sample,read_word,write_word,publish,pause_us};
static void reset(void){
 memset(&mapping,0,sizeof(mapping));memset(&gmu,0,sizeof(gmu));memset(mem,0xa5,sizeof(mem));
 global=(struct rf_gs_snapshot){.stage=4,.stable=true,.map_format_supported=true,
 .id0=0x4c017e05,.id1=0x20000005,.id2=0x5511,.id7=0x24,.page_bytes=4096,
 .global_bytes=0x8000,.streams=5,.contexts=5,.sid_bits=15,.input_bits=36,.output_bits=36,.virtual_bits=48};
 for(unsigned i=0;i<5;i++)global.s2cr[i]=0x10000;
 global.smr[0]=0x84000005;global.s2cr[0]=1;global.cba2r[1]=1;global.cbar[1]=0x1f300;
 global.smr[4]=0x84000002;global.s2cr[4]=2;global.cba2r[2]=1;global.cbar[2]=0x30000;
 banks=(struct rf_gc_snapshot){.stage=3,.stable=true,.disabled_mask=1};
 banks.words[1][0]=0x27;banks.words[1][8]=0x400;banks.words[1][2]=0x81000000;banks.words[1][3]=0x10001;
 gmu.active=1;gmu.expected=global;gmu.banks=banks;
 for(unsigned i=0;i<3;i++)data[i]=(struct rf_gm_memory){mem[i],0x184000000ULL+i*0x10000,0x8000,i+1,0x1000000+i*0x100000};
 pool=(struct rf_gm_memory){mem[3],0x184100000ULL,0x8000,99,0};
 live=1;denied=writes=fail_write=samples=fail_sample=bad=published=problem=0;now=0;
}
int run(unsigned issue,unsigned failure,unsigned audit_failure){
 reset();problem=issue;fail_write=failure;fail_sample=audit_failure;
 if(problem==1)denied=1;
 if(problem==2)data[1].physical=data[0].physical;
 if(problem==3)gmu.expected.smr[3]=0x84000001;
 if(problem==4)gmu.expected.references[0]=1;
 if(problem==5)gmu.banks.words[0][0]=1;
 int rc=rf_a6_pt_build(&gmu.expected,data,&pool,&owner,&plan);if(rc)return rc;
 return rf_a6_map_claim(&mapping,&ops,&gmu,&plan);
}
unsigned stat(unsigned i){unsigned a[]={writes,samples,bad,published,mapping.state.active,mapping.slots[0],mapping.slots[1]};return i<7?a[i]:999;}
uint64_t descriptor(unsigned page,unsigned slot){
 const uint8_t *p=mem[3]+4096*page+8*slot;uint64_t v=0;for(unsigned i=0;i<8;i++)v|=(uint64_t)p[i]<<(i*8);return v;
}
uint32_t route(unsigned slot,unsigned kind){return kind?global.s2cr[slot]:global.smr[slot];}
int matches(unsigned slot,unsigned sid){return rf_gs_stream_matches(global.smr[slot],sid);}
uint32_t context_word(unsigned index){return index<RF_GC_WORDS?banks.words[0][index]:UINT32_MAX;}
int packets(unsigned kind,uint32_t *out){return kind==0?(int)rf_a6_me_init(out):kind==1?(int)rf_a6_unsecure(out):(int)rf_a6_mem_write(out,kind-2,0x1234abcd);}
uint32_t reg_value(unsigned at){for(unsigned i=0;i<sizeof(rf_a6_registers)/sizeof(rf_a6_registers[0]);i++)
 if(rf_a6_registers[i].at==at)return rf_a6_registers[i].value;return UINT32_MAX;}
static struct rf_a6_perf perf;
int performance(unsigned issue){
 struct rf_cmddb_resource gfx={.type=3,.aux_version=0x1000,.level_count=16,.levels={0,16,48,64,128,192,256,320,384}},cx=gfx,mx=gfx;
 if(issue==1)gfx.levels[3]=32;if(issue==2)mx.level_count=0;if(issue==3)gfx.levels[9]=400;
 if(issue==4)gfx.levels[10]=500;
 return rf_a6_perf_make(&gfx,&cx,&mx,&perf);
}
uint32_t performance_word(unsigned i){return ((uint32_t *)&perf)[i];}
static struct rf_a6_bw bw;
int bandwidth(unsigned problem){
 struct rf_a6_bcm b[4]={{0x50004,1000000,16,1,0},{0x50000,1000000,4,0,0},{0x50088,0,0,2,0},{0x5006c,100000,8,3,0}};
 struct rf_a6_bcm sn10={0x50028,530000,16,2,0};
 if(problem==1)b[0].unit=0;if(problem==2)b[1].address=b[0].address;if(problem==3)b[2].vcd=16;
 if(problem==4)sn10.address=b[3].address;if(problem==5)sn10.unit=0;if(problem==6)sn10.vcd=3;
 return rf_a6_bw_make(b,&sn10,&bw);
}
uint32_t bandwidth_word(unsigned i){return ((uint32_t *)&bw)[i];}
int zap_plan(const uint8_t *p,unsigned n,unsigned segment){struct rf_a6_zap z;return rf_a6_zap_plan(p,n,segment,&z);}
static unsigned pas_issue,pas_calls,pas_bad;
static struct rf_sq_report pas_report;
static uint64_t pas_fn;
static bool pas_valid(void *p){return p==&pas_report && !(pas_issue==5 && pas_calls);}
static uint64_t pas_time(void *p){if(p!=&pas_report)pas_bad++;return now;}
static void pas_delay(void *p,unsigned us){if(p!=&pas_report||us!=30000)pas_bad++;now+=us*1000;}
static int pas_invoke(void *p,struct rf_sq_regs *r){
 if(p!=&pas_report||r->x[7]||(r->x[0]!=pas_fn && r->x[0]!=1))pas_bad++;
 if(r->x[0]==pas_fn){
  unsigned cmd=(unsigned)pas_fn&255;
  if(r->x[2]!=13||r->x[1]!=(cmd==1?0x82u:cmd==2?3u:1u)||
   r->x[3]!=(cmd==5?0:0x184000000ULL)||r->x[4]!=(cmd==2?4096:0))pas_bad++;
 }else if(r->x[6]!=0xabcddcba)pas_bad++;
 pas_calls++;r->x[0]=pas_issue==1?UINT64_MAX:pas_issue==3?(uint64_t)-12:
  (pas_issue==4||pas_calls==1)?1:0;
 r->x[1]=pas_issue==2?7:0;r->x[6]=0xabcddcba;now+=100000;
 return 0;
}
int pas(unsigned cmd,unsigned problem,uint64_t physical){
 now=0;pas_calls=pas_bad=0;pas_issue=problem;pas_fn=0x42000200u|cmd;
 struct rf_sq_ops o={&pas_report,pas_valid,pas_invoke,pas_delay,pas_time};
 return rf_a6_pas_run(&o,cmd,physical,&pas_report);
}
unsigned pas_stat(unsigned i){unsigned a[]={pas_calls,pas_bad,pas_report.completed,pas_report.resumes};return i<4?a[i]:999;}
'''


class GPUCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        root = Path(cls.tmp.name)
        (root / 'redfin_rpmh.h').write_text(rpmh_header())
        source, library = root / 'command.c', root / 'command.so'
        source.write_text(HARNESS)
        result = subprocess.run([shutil.which('cc') or 'cc', '-std=c11', '-O2', '-shared', '-fPIC',
            '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation', '-I', str(root),
            '-I', str(HERE), str(source), '-o', str(library)], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        cls.lib = ctypes.CDLL(str(library))
        cls.lib.descriptor.restype = ctypes.c_uint64
        cls.lib.route.restype = cls.lib.reg_value.restype = ctypes.c_uint32
        cls.lib.stat.restype = ctypes.c_uint32
        cls.lib.performance_word.restype = cls.lib.bandwidth_word.restype = ctypes.c_uint32
        cls.lib.pas.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_uint64]

    def test_full_owned_gpu_mapping_preserves_gmu_and_secure_routes_and_maps_readonly_sqe(self):
        self.assertEqual(self.lib.run(0, 0, 0), 0)
        self.assertEqual([self.lib.stat(i) for i in (0, 2, 3, 4, 5, 6)], [16, 0, 1, 1, 1, 0xFFFFFFFF])
        self.assertEqual([self.lib.route(i, 0) for i in (0, 1, 2, 4)],
                         [0x84000005, 0x84010000, 0, 0x84000002])
        self.assertEqual([self.lib.route(i, 1) for i in (0, 1, 2, 4)], [1, 0, 0x10000, 2])
        self.assertEqual(self.lib.descriptor(2, 0) & 0xFFF, 0xE43)
        self.assertEqual(self.lib.descriptor(2, 256) & 0xFFF, 0xEC3)
        self.assertEqual(self.lib.descriptor(3, 0) & 0xFFF, 0xE43)
        self.assertEqual(self.lib.descriptor(3, 1), 0)
        self.assertEqual(self.lib.context_word(3), 1)  # PA high word, ASID0.
        for sid in (0, 1, 0x400, 0x401):
            self.assertEqual(self.lib.matches(1, sid), 1)
        for sid in (2, 3, 4, 5, 0x402, 0x403, 0x404, 0x405):
            self.assertEqual(self.lib.matches(1, sid), 0)

    def test_every_context_write_and_audit_failure_stops_without_rollback(self):
        for write in range(1, 17):
            self.assertEqual(self.lib.run(0, write, 0), errno.EIO)
            self.assertEqual(self.lib.stat(0), write)
            self.assertEqual(self.lib.stat(4), 0)
            self.assertEqual(self.lib.stat(2), 0)
        self.assertEqual(self.lib.run(0, 0, 0), 0)
        samples = self.lib.stat(1)
        for failure in range(1, samples + 1):
            self.assertEqual(self.lib.run(0, 0, failure), errno.EFAULT)
            self.assertEqual(self.lib.stat(1), failure)
            self.assertEqual(self.lib.stat(4), 0)

    def test_denied_ram_aliases_conflicting_streams_or_busy_cb0_never_write_smmu(self):
        for problem in range(1, 6):
            self.assertNotEqual(self.lib.run(problem, 0, 0), 0, problem)
            self.assertEqual(self.lib.stat(0), 0)

    def test_native_translation_route_check_retains_hyp_privilege_readback_for_later_audits(self):
        self.assertEqual(self.lib.run(6, 0, 0), 0)
        self.assertEqual(self.lib.route(1, 1), 0x1000000)
        self.assertEqual(self.lib.route(2, 1), 0x10000)
        self.assertEqual(self.lib.stat(4), 1)
        self.assertEqual(self.lib.stat(2), 0)

    def test_packets_have_native_parity_ordinals_and_no_unmapped_reglist(self):
        words = (ctypes.c_uint32 * 16)()
        self.assertEqual(self.lib.packets(0, words), 12)
        self.assertEqual(list(words)[1:12], [0x6F, 3, 0x20000000, 0, 0, 0, 2, 0, 0, 0, 0])
        self.assertEqual(self.lib.packets(1, words), 2)
        self.assertEqual((words[0] >> 16) & 0x7F, 0x66)
        self.assertEqual(self.lib.packets(2, words), 5)
        self.assertEqual(list(words)[1:4], [0x1200100, 0, 0x1234ABCD])
        for kind in range(4):
            self.lib.packets(kind, words)
            header = words[0]
            size, opcode = header & 0x3FFF, (header >> 16) & 0x7F
            self.assertEqual((size.bit_count() + ((header >> 15) & 1)) % 2, 1)
            self.assertEqual((opcode.bit_count() + ((header >> 23) & 1)) % 2, 1)
        self.assertEqual(self.lib.reg_value(4 * 0x9E00), 0x10200)
        self.assertEqual(self.lib.reg_value(4 * 0x1F), 0x4003FFFF)
        self.assertEqual(self.lib.reg_value(4 * 0x8E08), 0x12)
        self.assertEqual(self.lib.reg_value(4 * 0xB34), 0xFFFFFFFF)

    def test_native_low_opp_voltage_dependencies_and_bcm_vcd_order(self):
        self.assertEqual(self.lib.performance(0), 0)
        self.assertEqual([self.lib.performance_word(i) for i in range(9)],
                         [0, 2, 2, 0, 0xFFFFFFFF, 0, 0x400303, 0xFFFFFFFF, 275000])
        for problem in (1, 2, 4):
            self.assertNotEqual(self.lib.performance(problem), 0)
        self.assertEqual(self.lib.bandwidth(0), 0)
        self.assertEqual([self.lib.bandwidth_word(i) for i in range(6)], [0, 13, 2, 3, 3, 7])
        self.assertEqual([self.lib.bandwidth_word(i) for i in (6, 7)], [0x50028, 0x5006C])
        self.assertEqual([self.lib.bandwidth_word(i) for i in (12, 13)], [0x40000000, 0x40000000])
        self.assertEqual([self.lib.bandwidth_word(i) for i in (18, 19)], [0x60000001, 0x60000001])
        # Native full-size table, sorted VCDs: MC0, SH0, ACV.
        self.assertEqual([self.lib.bandwidth_word(i) for i in range(24, 27)], [0x50000, 0x50004, 0x50088])
        for problem in range(1, 6):
            self.assertNotEqual(self.lib.bandwidth(problem), 0)
        self.assertEqual(self.lib.bandwidth(6), 0)
        self.assertEqual(self.lib.bandwidth_word(4), 2)
        self.assertEqual(self.lib.bandwidth_word(12), 0)

    def test_pas13_uses_native_scm64_encoding_resume_cookie_and_both_success_values(self):
        for cmd in (1, 2, 5):
            self.assertEqual(self.lib.pas(cmd, 0, 0x184000000), 0)
            self.assertEqual([self.lib.pas_stat(i) for i in range(4)], [2, 0, 1, 1])
            for problem, error in ((1, errno.EIO), (2, errno.EIO), (3, errno.EBUSY),
                                   (4, errno.ETIMEDOUT), (5, errno.ECANCELED)):
                self.assertEqual(self.lib.pas(cmd, problem, 0x184000000), error)
                self.assertEqual(self.lib.pas_stat(1), 0)
        for cmd, address in ((4, 0x184000000), (6, 0x184000000), (1, 0x8BC15400),
                              (2, 0x184004000), (5, 0)):
            self.assertEqual(self.lib.pas(cmd, 0, address), errno.EINVAL)
            self.assertEqual(self.lib.pas_stat(0), 0)

    def test_signed_zap_load_span_uses_only_relocatable_segment(self):
        mdt = bytearray(6860)
        mdt[:7] = b'\x7fELF\x01\x01\x01'
        struct.pack_into('<I', mdt, 28, 52)
        struct.pack_into('<3H', mdt, 40, 52, 32, 3)
        struct.pack_into('<8I', mdt, 116, 1, 0x3000, 0x5000, 0x5000, 1676, 1676, 0x8000007, 0x100000)
        raw = ctypes.create_string_buffer(bytes(mdt))
        self.assertEqual(self.lib.zap_plan(raw, 6860, 1676), 0)
        for at in (0, 4, 28, 42, 44, 116, 128, 132, 136, 140, 144):
            changed = bytearray(mdt)
            changed[at] ^= 1
            self.assertNotEqual(self.lib.zap_plan(ctypes.create_string_buffer(bytes(changed)), 6860, 1676), 0)


class GPUAllocationTests(unittest.TestCase):
    def test_actual_adapter_requests_physical_alignment_and_retains_uncertain_allocations(self):
        raw = (HERE / 'gpu-command.inc').read_text()
        body = re.search(r'^static int gx_allocate\([^\n]+\)\n\{.*?^\}', raw, re.M | re.S)[0]
        prefix = r'''
#include <stdint.h>
#include <string.h>
#include "redfin_rpmh.h"
#include "include/redfin_gpu_command.h"
typedef uintptr_t vm_offset_t,vm_size_t;
typedef uint64_t ppnum_t;
#define PAGE_SHIFT 14
#define PAGE_MASK 0x3fff
#define KMA_KOBJECT 1
#define KMA_ZERO 2
#define KMA_DATA 4
#define VM_KERN_MEMORY_IOKIT 5
#define KERN_SUCCESS 0
static uint8_t arena[RF_A6_ZAP_ALLOC];
static void *kernel_map=(void *)1;
static struct {void *context;uint64_t allocated;unsigned allocations;} gx;
static unsigned problem,calls;
static uint64_t va_mask,pa_mask,physical;
static int gx_check(void *p){return p==gx.context && problem!=4?0:ECANCELED;}
static int host_printf(const char *f,...){(void)f;return 0;}
#define printf host_printf
static uint64_t kvtophys(vm_offset_t p){if(p!=(vm_offset_t)arena)return 0;return physical;}
static int kmem_alloc_contig(void *map,vm_offset_t *out,vm_size_t bytes,vm_size_t mask,
 ppnum_t max_pnum,ppnum_t pnum_mask,unsigned flags,unsigned tag){
 calls++;va_mask=mask;pa_mask=pnum_mask;
 if(map!=kernel_map || bytes>sizeof(arena) || max_pnum!=0x7ffff || flags!=7 || tag!=5)return 2;
 if(problem==3)return 1;*out=(vm_offset_t)arena;return KERN_SUCCESS;
}
'''
        suffix = r'''
int run(unsigned secure,unsigned issue){
 struct rf_gm_memory m;problem=issue;calls=0;va_mask=pa_mask=0;
 gx.context=&gx;gx.allocated=issue==5?0x180000:0;gx.allocations=0;
 physical=secure && issue!=2?0x184000000ULL:0x184004000ULL;
 if(issue==6)physical=0x80000000;
 return gx_allocate(&m,secure?0:RF_A6_RING,secure?RF_A6_ZAP_ALLOC:0x8000,123,secure);
}
uint64_t stat(unsigned i){uint64_t s[]={calls,va_mask,pa_mask,gx.allocations,gx.allocated};return i<5?s[i]:999;}
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'redfin_rpmh.h').write_text(rpmh_header())
            source, library = root / 'allocate.c', root / 'allocate.so'
            source.write_text(prefix + body + suffix)
            subprocess.run([shutil.which('cc') or 'cc', '-std=c11', '-O2', '-shared', '-fPIC',
                '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation', '-I', str(root),
                '-I', str(HERE), str(source), '-o', str(library)], check=True, capture_output=True)
            lib = ctypes.CDLL(str(library))
            lib.stat.restype = ctypes.c_uint64
            self.assertEqual(lib.run(1, 0), 0)
            self.assertEqual([lib.stat(i) for i in range(5)], [1, 0xFFFFF, 0x3F, 1, 0x100000])
            self.assertEqual(lib.run(0, 0), 0)
            self.assertEqual([lib.stat(i) for i in range(5)], [1, 0x3FFF, 0, 1, 0x8000])
            for issue, result, allocated in ((2, errno.ERANGE, 1), (3, errno.ENOMEM, 0),
                                             (4, errno.ECANCELED, 0), (5, errno.EFBIG, 0),
                                             (6, errno.ERANGE, 1)):
                self.assertEqual(lib.run(1, issue), result)
                self.assertEqual(lib.stat(3), allocated)
                self.assertEqual(lib.stat(0), 0 if issue in (4, 5) else 1)


if __name__ == '__main__':
    unittest.main()
