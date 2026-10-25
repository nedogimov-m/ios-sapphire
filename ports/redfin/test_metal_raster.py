"""Invalid recorded geometry/imports must be refused before GPU state or DMA."""
from pathlib import Path
import subprocess
import tempfile
import unittest


class MetalRasterTests(unittest.TestCase):
    def native(self, body):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'raster.c'
            source.write_text('#include <assert.h>\n#include <string.h>\n'
                '#include "metal-raster.h"\n#include "metal-linear-import.h"\n'
                'int main(void){\n'+body+'\nreturn 0;}\n')
            result=subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-O2',
                '-I'+str(Path(__file__).parent),str(source),'-o',str(root/'raster')],capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
            subprocess.run([str(root/'raster')],check=True,capture_output=True,timeout=10)

    def test_recorded_state_refuses_nonfinite_overflow_and_unrepresentable_modes(self):
        self.native(r'''
struct redfin_metal_raster_state s={0},good={0};
assert(redfin_metal_raster_valid(NULL)&&redfin_metal_raster_valid(&s));
s.flags=3;double viewport[6]={8,12,40,32,0,1};memcpy(s.viewport,viewport,sizeof(viewport));
uint64_t scissor[4]={16,20,16,8};memcpy(s.scissor,scissor,sizeof(scissor));
assert(redfin_metal_raster_valid(&s));good=s;
for(unsigned i=0;i<6;++i){s=good;s.viewport[i]=NAN;assert(!redfin_metal_raster_valid(&s));
 s.viewport[i]=INFINITY;assert(!redfin_metal_raster_valid(&s));}
s=good;s.viewport[2]=-1;assert(!redfin_metal_raster_valid(&s));
s=good;s.viewport[4]=-0.01;assert(!redfin_metal_raster_valid(&s));
s=good;s.viewport[5]=1.01;assert(!redfin_metal_raster_valid(&s));
s=good;s.scissor[0]=UINT32_MAX;s.scissor[2]=1;assert(!redfin_metal_raster_valid(&s));
s=good;s.scissor[1]=UINT64_MAX;assert(!redfin_metal_raster_valid(&s));
s=good;s.cull=3;assert(!redfin_metal_raster_valid(&s));
s=good;s.flags|=4;assert(!redfin_metal_raster_valid(&s));
s=good;s.blend_color[2]=NAN;assert(!redfin_metal_raster_valid(&s));
''')

    def test_scissor_intersects_attachment_without_wrap_or_inclusive_last_pixel(self):
        self.native(r'''
struct redfin_metal_raster_state s={0};uint32_t rect[4];
redfin_metal_scissor(NULL,64,64,rect);assert(rect[0]==0&&rect[1]==0&&rect[2]==64&&rect[3]==64);
s.flags=2;s.scissor[0]=16;s.scissor[1]=20;s.scissor[2]=16;s.scissor[3]=8;
redfin_metal_scissor(&s,64,64,rect);assert(rect[0]==16&&rect[1]==20&&rect[2]==32&&rect[3]==28);
s.scissor[0]=60;s.scissor[1]=61;s.scissor[2]=20;s.scissor[3]=20;
redfin_metal_scissor(&s,64,64,rect);assert(rect[0]==60&&rect[1]==61&&rect[2]==64&&rect[3]==64);
s.scissor[0]=UINT32_MAX;s.scissor[1]=UINT32_MAX;s.scissor[2]=s.scissor[3]=0;
assert(redfin_metal_raster_valid(&s));redfin_metal_scissor(&s,64,64,rect);
assert(rect[0]==64&&rect[1]==64&&rect[2]==64&&rect[3]==64);
''')

    def test_real_source_layouts_and_copy_extents_fit_only_their_actual_allocation(self):
        self.native(r'''
assert(redfin_linear_layout_fits(120,32,4,480,0,16384));
assert(redfin_linear_layout_fits(1125,9,4,4512,0,65536));
assert(!redfin_linear_layout_fits(120,32,4,480,0,15359));
assert(!redfin_linear_layout_fits(120,32,4,480,1024,16383));
assert(!redfin_linear_layout_fits(121,32,4,480,0,16384));
assert(!redfin_linear_layout_fits(120,32,4,481,0,16384));
assert(!redfin_linear_layout_fits(120,32,4,480,1,16384));
assert(!redfin_linear_layout_fits(120,32,4,480,UINT64_MAX-31,16384));
assert(!redfin_linear_layout_fits(UINT32_MAX,UINT32_MAX,16,0x3ffff0,0,UINT64_MAX));
assert(!redfin_linear_layout_fits(0,1,4,480,0,16384));
assert(!redfin_linear_layout_fits(1,0,4,480,0,16384));
struct redfin_linear_copy_plan p={0};
assert(redfin_linear_copy_plan_make(&p,480,32,480,512,0,0,16384,32768));
assert(p.words==120&&p.rows==32&&p.source_pitch==480&&p.destination_pitch==512);
assert(redfin_linear_copy_plan_make(&p,4500,9,4512,4544,0,0,65536,65536));
assert(!redfin_linear_copy_plan_make(&p,480,32,480,512,0,0,15359,32768));
assert(!redfin_linear_copy_plan_make(&p,480,32,480,512,0,0,16384,16351));
assert(!redfin_linear_copy_plan_make(&p,480,32,480,512,2,0,16384,32768));
assert(!redfin_linear_copy_plan_make(&p,481,32,480,512,0,0,16384,32768));
assert(!redfin_linear_copy_plan_make(&p,480,UINT32_MAX,480,512,0,0,UINT64_MAX,UINT64_MAX));
assert(!redfin_linear_copy_plan_make(&p,480,32,480,512,UINT64_MAX-3,0,UINT64_MAX,32768));
''')


if __name__=='__main__':unittest.main()
