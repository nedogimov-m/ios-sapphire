"""Run the actual owned GMU translation lease with native register semantics."""
import ctypes
import errno
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
HARNESS = r'''
#include <string.h>
#include "include/redfin_gmu_mapping.h"
static uint32_t regs[0x10000/4];
static struct rf_gmm_lease lease;
static struct rf_gm_pt_plan plan;
static unsigned issue,fail_write,writes,samples,publishes,violations,lost;
static char table_memory[0x4000],data_memory[0x4000];
static int check(void *c){if(c!=&lease)violations++;return lost?ECANCELED:0;}
static bool valid(void *c){return !check(c);}
static bool owns(void *c,const struct rf_gm_memory *m,unsigned use){
 if(check(c))violations++;
 return issue!=6 && ((use==RF_GM_PT_TABLE_POOL && m->token==100) || (use==RF_GM_PT_DATA && m->token==1));
}
static int raw_global(void *c,uint32_t at,uint32_t *v){(void)c;*v=regs[at/4];return 0;}
static int raw_bank(void *c,unsigned bank,uint32_t at,uint32_t *v){(void)c;*v=regs[(0x8000+bank*0x1000+at)/4];return 0;}
static int sample(void *c,struct rf_gs_snapshot *g,struct rf_gc_snapshot *b){
 samples++;if(check(c))violations++;
 if(issue==8 && writes==4)regs[0xc04/4]^=0x100;
 if(issue==9 && writes==8)regs[(0x9000+0x28)/4]=0x1000;
 if(issue==16 && writes==5)regs[(0x9000+0x10)/4]^=0x20;
 const struct rf_gs_ops go={c,valid,raw_global};const struct rf_gc_ops bo={c,valid,raw_bank};
 int e=rf_gs_snapshot_run(&go,0x06020001,g);return e?e:rf_gc_snapshot_run(&bo,g,b);
}
static int read_word(void *c,unsigned block,uint32_t at,uint32_t *v){
 if(check(c))violations++;
 *v=regs[((block?0x9000:0)+at)/4];
 if(issue==10 && block && at==0x7f4)*v=1;
 if(issue==11 && writes==3 && !block && at==0x1004)*v^=0x10000;
 return 0;
}
static int write_word(void *c,unsigned block,uint32_t at,uint32_t v){
 if(check(c))violations++;
 unsigned eb;uint32_t ea,ev;
 if(rf_gmm_step(&lease,&plan,writes,&eb,&ea,&ev) || eb!=block || ea!=at || ev!=v)violations++;
 writes++;if(writes==fail_write)return EIO;
 unsigned index=((block?0x9000:0)+at)/4;
 if(block && at==0x34){violations++;return EPERM;} /* AArch32-only register. */
 if(block && at==0x10)v=(regs[index]&~0x38017u)|(v&0x38017u);
 if(block && at==0x30)v=(regs[index]&~0x00c0ffbfu)|(v&0x00c0ffbfu);
 if(block && at==0 && v)v=(v&~6u); /* AFE/TRE can read as zero in AArch64. */
 if(issue==13 && block && at==0x10)v^=1;
 if(issue==14 && block && at==0x30)v^=0x100;
 if(issue==15 && block && at==0 && v)v|=0x80;
 if(issue==17 && block && at==0x30)v|=0x400000;
 if(issue==18 && block && at==0 && v)v|=0x100000;
 regs[index]=v;
 if(!block && at==0x1804)regs[(0x9000+0x58)/4]=0x400;
 if(issue==12 && writes==2)lost=1;
 return 0;
}
static int publish(void *c,const struct rf_gm_pt_plan *p){
 if(check(c) || p!=&plan || writes)violations++;publishes++;return issue==7?EIO:0;
}
static int pause_us(void *c,unsigned us){if(check(c) || us!=1)violations++;return 0;}
static const struct rf_gmm_ops ops={&lease,check,sample,read_word,write_word,publish,pause_us};
int run(unsigned mode,unsigned failure){
 memset(regs,0,sizeof(regs));memset(&lease,0,sizeof(lease));memset(&plan,0,sizeof(plan));
 issue=mode;fail_write=failure;writes=samples=publishes=violations=lost=0;
 regs[0x20/4]=0x4c017e05;regs[0x24/4]=0x20000005;regs[0x28/4]=0x5511;regs[0x3c/4]=0x24;regs[0]=0x220406;
 for(unsigned i=0;i<5;i++)regs[(0xc00+4*i)/4]=0x200ff;
 for(unsigned bank=0;bank<2;bank++)for(unsigned i=0;i<RF_GC_WORDS;i++)
  regs[(0x8000+bank*0x1000+rf_gc_offsets[i])/4]=i==0?0xabc0:i==8?0:0x12340000+rf_gc_offsets[i];
 if(issue==1)regs[0xc10/4]=1; /* latent reference in an invalid SMR */
 if(issue==2){regs[0x808/4]=0x84000005;regs[0xc08/4]=0;}
 if(issue==3)regs[0x9000/4]|=1;
 if(issue==4)regs[(0x9000+0x58)/4]=2;
 plan.granule=0x1000;plan.virtual_bits=39;plan.physical_bits=36;plan.mair0=0xf404ff44;
 plan.tables=(struct rf_gm_memory){table_memory,0x180800000ULL,0x4000,100,0};
 plan.root_physical=plan.tables.physical;plan.table_count=4;plan.table_bytes=0x4000;plan.extent_count=1;
 plan.extents[0].memory=(struct rf_gm_memory){data_memory,0x180900000ULL,0x4000,1,0x4000};plan.extents[0].mapped_bytes=0x4000;
 if(issue==5)plan.root_physical+=8;
 regs[(0x9000+0x10)/4]=0x30061; /* Captured native reserved bits6:5. */
 struct rf_gs_snapshot g;struct rf_gc_snapshot b;
 int e=sample(&lease,&g,&b);if(e)return e;
 const struct rf_gm_memory_owner owner={&lease,valid,owns};
 return rf_gmm_claim(&lease,&ops,&g,&b,&plan,&owner);
}
unsigned stat(unsigned i){const unsigned v[]={writes,publishes,violations,lease.active,lease.poisoned,lease.polls,lease.owned};return i<7?v[i]:999;}
int retry(void){struct rf_gs_snapshot g;struct rf_gc_snapshot b;memset(&g,0,sizeof(g));memset(&b,0,sizeof(b));
 const struct rf_gm_memory_owner owner={&lease,valid,owns};return rf_gmm_claim(&lease,&ops,&g,&b,&plan,&owner);}
int fault_format(void){struct rf_gs_snapshot g;struct rf_gc_snapshot b;lost=0;int e=sample(&lease,&g,&b);return e?-1:(int)b.fault_mask;}
'''


class GMUMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        root = Path(cls.temporary.name)
        source, library = root / 'gmu_mapping.c', root / 'gmu_mapping.so'
        source.write_text(HARNESS)
        subprocess.run([shutil.which('cc') or 'cc', '-std=c11', '-O2', '-shared', '-fPIC',
            '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation',
            '-I', str(HERE), str(source), '-o', str(library)],
            check=True, capture_output=True)
        cls.lib = ctypes.CDLL(str(library))

    def test_exact_native_sequence_uses_owned_memory_and_format_is_not_a_fault(self):
        self.assertEqual(self.lib.run(0, 0), 0)
        self.assertEqual([self.lib.stat(i) for i in range(7)], [16, 1, 0, 1, 0, 1, 1])
        self.assertEqual(self.lib.fault_format(), 0)
        self.assertEqual(self.lib.retry(), errno.EBUSY)
        self.assertEqual(self.lib.stat(0), 16)

    def test_latent_foreign_context_live_stream_faults_and_invalid_root_never_write(self):
        for mode in range(1, 7):
            with self.subTest(mode=mode):
                self.assertNotEqual(self.lib.run(mode, 0), 0)
                self.assertEqual(self.lib.stat(0), 0)
                self.assertEqual(self.lib.stat(1), 0)
                self.assertEqual(self.lib.stat(2), 0)

    def test_failed_cache_publication_performs_no_hardware_write(self):
        self.assertEqual(self.lib.run(7, 0), errno.EIO)
        self.assertEqual(self.lib.stat(0), 0)
        self.assertEqual(self.lib.stat(1), 1)

    def test_foreign_route_and_owned_ttbr_changes_stop_before_another_write(self):
        for mode, writes in ((8, 4), (9, 8), (16, 5)):
            self.assertEqual(self.lib.run(mode, 0), errno.EAGAIN)
            self.assertEqual(self.lib.stat(0), writes)
            self.assertEqual(self.lib.stat(3), 0)
            self.assertEqual(self.lib.stat(2), 0)

    def test_every_failed_store_wrong_readback_timeout_and_revocation_stop(self):
        for failed in range(1, 17):
            self.assertEqual(self.lib.run(0, failed), errno.EIO)
            self.assertEqual(self.lib.stat(0), failed)
            self.assertEqual(self.lib.stat(3), 0)
        self.assertEqual(self.lib.run(10, 0), errno.ETIMEDOUT)
        self.assertEqual(self.lib.stat(5), 1000)
        self.assertEqual(self.lib.run(11, 0), errno.EIO)
        self.assertEqual(self.lib.run(12, 0), errno.ECANCELED)
        self.assertEqual(self.lib.stat(0), 2)
        self.assertEqual(self.lib.stat(2), 0)

    def test_native_reserved_readback_does_not_hide_critical_field_failures(self):
        for mode, writes in ((13, 4), (14, 5), (15, 14), (17, 5), (18, 14)):
            self.assertEqual(self.lib.run(mode, 0), errno.EIO)
            self.assertEqual(self.lib.stat(0), writes)
            self.assertEqual(self.lib.stat(3), 0)
            self.assertEqual(self.lib.stat(2), 0)


if __name__ == '__main__':
    unittest.main()
