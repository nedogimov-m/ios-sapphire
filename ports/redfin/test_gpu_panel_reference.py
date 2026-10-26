"""Actual panel verification uses its completed route and independent memory."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_display_geometry import function

HERE=Path(__file__).resolve().parent


class GPUPanelReferenceTests(unittest.TestCase):
    def test_actual_direct_panel_oracle_ignores_old_stage_and_retains_exact_fail_closed_checks(self):
        body=function((HERE/'gpu-display.inc').read_text(),'static bool gd_panel_readback(')
        source=r'''
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <cstdarg>
#include <initializer_list>
#include "redfin_gpu_runtime.h"
#include "redfin_gpu_display.h"
struct gd_buffer {uint8_t *kernel;uint64_t size,address;void *memory;};
struct gd_submit_marks {};
static struct {gd_buffer stage,panel,verification;unsigned calls,direct_verified;bool uncertain;}gd;
static unsigned references,invalidations;static bool fail;
static rf_gd_layer layer={};
static uint32_t value(unsigned x,unsigned y){return 0xff000000u|(x*17+y*41);}
static void fill(gd_buffer *b,unsigned pitch,unsigned offset){
 memset(b->kernel,0x3c,b->size);
 for(unsigned y=0;y<8;++y)for(unsigned x=0;x<8;++x){
  unsigned px=x*(RF_GD_PANEL_W-1)/7,py=y*(RF_GD_PANEL_H-2)/7+(x&1);
  uint32_t pixel=value(px,py);memcpy(b->kernel+offset+(uint64_t)py*pitch+px*4,&pixel,4);
 }
}
static bool gd_submit(const rf_gd_layer *layers,unsigned count,uint64_t packed,uint64_t bytes,
 bool panel,uint32_t *fence,gd_submit_marks *marks,int route){
 assert(layers==&layer&&count==1&&packed==gd.verification.address+64&&bytes==RF_GD_PANEL_MAPPED);
 assert(!panel&&!marks&&route==1);++references;
 if(fail)return false;
 fill(&gd.verification,RF_GD_PANEL_PITCH,64);*fence=29;return true;
}
static void redfin_gpu_invalidate(void *memory,uint64_t bytes){assert(memory&&bytes);++invalidations;}
static void IOLog(const char *,...){}
'''+body+r'''
int main(){
 gd.stage.size=RF_GD_STAGE_BYTES;gd.panel.size=RF_GD_PANEL_MAPPED;
 gd.verification.size=RF_GD_PANEL_MAPPED+16384;gd.verification.address=0x1a000000;
 for(gd_buffer *b:{&gd.stage,&gd.panel,&gd.verification}){
  b->kernel=(uint8_t *)malloc(b->size);assert(b->kernel);b->memory=b->kernel;
 }
 gd.calls=100;memset(gd.stage.kernel,0x3c,gd.stage.size);fill(&gd.panel,RF_GD_PANEL_PITCH,0);
 for(unsigned n=0;n<4;++n){
  assert(gd_panel_readback(27,&layer,1,true));assert(gd.direct_verified==n+1);
  assert(gd.stage.kernel[0]==0x3c); /* obsolete stage is never the oracle */
 }
 assert(references==4&&invalidations==8&&!gd.uncertain);
 assert(gd_panel_readback(27,&layer,1,true)&&references==4); /* bounded startup only */
 gd.direct_verified=0;gd.panel.kernel[0]^=1;
 assert(!gd_panel_readback(27,&layer,1,true)&&gd.direct_verified==0&&!gd.uncertain);
 fill(&gd.panel,RF_GD_PANEL_PITCH,0);fail=true;
 assert(!gd_panel_readback(27,&layer,1,true)&&gd.uncertain&&!gd.direct_verified);
 fail=false;gd.uncertain=false;gd.calls=0;unsigned before=references;
 fill(&gd.stage,RF_GD_STAGE_PITCH,0);
 assert(gd_panel_readback(27,&layer,1,false)&&references==before); /* original legacy oracle */
 gd.stage.kernel[0]^=1;assert(!gd_panel_readback(27,&layer,1,false));
 gd.calls=4;assert(gd_panel_readback(27,&layer,1,false));
 for(gd_buffer *b:{&gd.stage,&gd.panel,&gd.verification})free(b->kernel);
 return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='redfin-panel-reference-') as directory:
            path=Path(directory)/'panel.cpp';path.write_text(source);exe=path.with_suffix('')
            result=subprocess.run(['c++','-std=c++17','-O2','-Wall','-Wextra','-Werror','-Wno-missing-field-initializers',
                '-I'+str(HERE/'include'),str(path),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
