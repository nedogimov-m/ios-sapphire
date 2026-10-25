"""Protect native raw-alias mapping and Metal's 64-bit transfer bounds."""
from pathlib import Path
import subprocess
import ctypes
import random
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
MESA=ROOT/'research/redfin-metal-composition-v2/mesa-25.0.7'


class MetalBlitTests(unittest.TestCase):
    def native(self,source):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'check.c').write_text(source)
            built=subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',
                '-I'+str(HERE),str(root/'check.c'),'-o',str(root/'check')],capture_output=True)
            self.assertEqual(built.returncode,0,built.stderr.decode(errors='replace'))
            result=subprocess.run([str(root/'check')],capture_output=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))

    def test_actual_raw_alias_constructor_bypasses_the_real_depth_transfer_path(self):
        # Execute the exact constructor added by our patch against the actual
        # Mesa transfer-selection function. Allocation/BO bookkeeping is stubbed;
        # format selection and the conversion decision are real source bodies.
        added='\n'.join(line[1:] for line in (HERE/'metal-linear-import.patch').read_text().splitlines()
            if line.startswith('+') and not line.startswith('+++'))
        first=added.index('static struct pipe_resource *\nredfin_buffer_from_bo(')
        last=added.index('\n}',first)+2
        constructor=added[first:last]
        helper=(MESA/'src/gallium/auxiliary/util/u_transfer_helper.c').read_text()
        first=helper.index('static inline bool needs_in_place_zs_interleave(')
        last=helper.index('\n/* The pipe_transfer ptr',first)
        transfer=helper[first:last]
        native=(MESA/'src/gallium/drivers/freedreno/freedreno_resource.c').read_text()
        first=native.index('static enum pipe_format\nfd_resource_get_internal_format(')
        last=native.index('\n}',first)+2
        getter=native[first:last]
        self.native(r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
enum pipe_format {PIPE_FORMAT_NONE,PIPE_FORMAT_R8_UINT,PIPE_FORMAT_Z32_FLOAT_S8X24_UINT,PIPE_FORMAT_Z24X8_UNORM};
enum {PIPE_BUFFER,PIPE_BIND_SHADER_BUFFER=1,PIPE_BIND_CONSTANT_BUFFER=2,PIPE_BIND_INDEX_BUFFER=4,PIPE_BIND_VERTEX_BUFFER=8,PIPE_USAGE_DEFAULT=0};
struct u_transfer_helper;
struct pipe_screen {struct u_transfer_helper *transfer_helper;};
struct pipe_resource {struct pipe_screen *screen;enum pipe_format format;unsigned target,width0,height0,depth0,array_size,bind,usage,nr_samples;};
struct fd_bo {uint32_t size;unsigned references;};
struct fd_resource {struct {struct pipe_resource b;bool is_shared;} b;enum pipe_format internal_format;unsigned layout,valid_buffer_range;bool valid;struct fd_bo *bo;};
struct transfer_vtbl {enum pipe_format (*get_internal_format)(struct pipe_resource *);};
struct u_transfer_helper {const struct transfer_vtbl *vtbl;bool interleave_in_place,separate_stencil,separate_z32s8,z24_in_z32f,msaa_map;};
static bool util_format_is_depth_and_stencil(enum pipe_format f){return f==PIPE_FORMAT_Z32_FLOAT_S8X24_UINT;}
static struct fd_resource *fd_resource(struct pipe_resource *r){return (struct fd_resource *)r;}
static uint32_t fd_bo_size(struct fd_bo *bo){return bo->size;}
static void fd_bo_del(struct fd_bo *bo){assert(bo->references);--bo->references;}
static struct fd_resource *alloc_resource_struct(struct pipe_screen *s,const struct pipe_resource *shape){
 struct fd_resource *r=calloc(1,sizeof(*r));assert(r);r->b.b=*shape;r->b.b.screen=s;return r;
}
static void fd_resource_layout_init(struct pipe_resource *r){(void)r;}
static void fdl_layout_buffer(unsigned *layout,unsigned size){*layout=size;}
static void tc_buffer_disable_cpu_storage(struct pipe_resource *r){(void)r;}
static void fd_resource_set_bo(struct fd_resource *r,struct fd_bo *bo){r->bo=bo;}
static void util_range_add(struct pipe_resource *r,unsigned *range,unsigned start,unsigned size){assert(!start&&size==r->width0);*range=size;}
'''+getter+'\n'+transfer+'\n'+constructor+r'''
int main(void){
 const struct transfer_vtbl vtbl={fd_resource_get_internal_format};
 struct u_transfer_helper helper={.vtbl=&vtbl,.msaa_map=true,.interleave_in_place=true,.z24_in_z32f=true};
 struct pipe_screen screen={&helper};
 for(unsigned size=1;size<=65536;size*=16){
  struct fd_bo bo={size,1};struct pipe_resource *r=redfin_buffer_from_bo(&screen,&bo);
  assert(r&&r->width0==size&&r->format==PIPE_FORMAT_R8_UINT&&fd_resource(r)->b.is_shared&&fd_resource(r)->valid);
  assert(!handle_transfer(r));
  /* The previous missing initializer must actually reproduce the dangerous
   * conversion selection; this guards the harness's relevance. */
  fd_resource(r)->internal_format=PIPE_FORMAT_NONE;assert(handle_transfer(r));
  free(r);fd_bo_del(&bo);assert(!bo.references);
 }
 struct fd_bo empty={0,1};assert(!redfin_buffer_from_bo(&screen,&empty)&&!empty.references);
 assert(!redfin_buffer_from_bo(&screen,NULL));
 return 0;
}
''')

    def test_actual_buffer_range_refuses_64bit_wrap_and_dma_narrowing(self):
        text=(HERE/'metal-blit.inc').read_text()
        first=text.index('static bool\nrwa_blit_range(');last=text.index('\nstatic int',first)
        self.native('#include <assert.h>\n#include <stdbool.h>\n#include "metal-blit.h"\n'+text[first:last]+r'''
int main(void){
 assert(sizeof(struct redfin_metal_blit)==152);
 assert(rwa_blit_range(13,517,2048));assert(rwa_blit_range(2048,0,2048));
 assert(!rwa_blit_range(2049,0,2048));assert(!rwa_blit_range(2047,2,2048));
 assert(!rwa_blit_range(UINT64_MAX-1,4,UINT64_MAX));
 assert(!rwa_blit_range(UINT32_MAX,1,UINT64_MAX));
 assert(!rwa_blit_range(0,UINT64_MAX,UINT64_MAX));
 assert(rwa_blit_range(UINT32_MAX-1,1,UINT32_MAX));
 return 0;
}
''')

    def test_real_allocation_extent_keeps_every_logical_tail_in_a_complete_native_dword(self):
        self.native('#include <assert.h>\n#include "metal-buffer-import.h"\n'+r'''
int main(void){
 uint32_t physical=0;
 for(size_t n=1;n<131072;++n){
  assert(redfin_buffer_extent(n,&physical));assert(physical>=n&&physical-n<=3&&!(physical&3));
  assert(((n-1)/4)<physical/4); /* actual R32 descriptor's final addressable texel */
 }
 assert(redfin_buffer_extent(128u<<20,&physical)&&physical==(128u<<20));
 assert(!redfin_buffer_extent(0,&physical));assert(!redfin_buffer_extent(1,NULL));
 assert(!redfin_buffer_extent(UINT32_MAX,&physical));assert(!redfin_buffer_extent(SIZE_MAX,&physical));
 return 0;
}
''')

    def test_actual_aliased_texture_row_test_matches_independent_byte_ownership(self):
        text=(HERE/'metal-buffer-texture.inc').read_text()
        start=text.index('static bool\nrwa_redfin_view_rows_overlap(');end=text.index('\nstatic int',start)
        function=text[start:end].replace('static bool\n','bool\n',1)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'overlap.c').write_text('#include <stdint.h>\n#include <stdbool.h>\n'+function)
            built=subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
                str(root/'overlap.c'),'-o',str(root/'overlap.so')],capture_output=True)
            self.assertEqual(built.returncode,0,built.stderr.decode(errors='replace'))
            lib=ctypes.CDLL(str(root/'overlap.so'));f=lib.rwa_redfin_view_rows_overlap
            f.argtypes=[ctypes.c_uint64,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32]*2;f.restype=ctypes.c_bool
            rng=random.Random(620)
            for _ in range(5000):
                a,b=rng.randrange(64),rng.randrange(64);ap,bp=rng.randrange(1,33),rng.randrange(1,33)
                aw,bw=rng.randrange(1,ap+1),rng.randrange(1,bp+1);ah,bh=rng.randrange(1,9),rng.randrange(1,9)
                left={a+y*ap+x for y in range(ah) for x in range(aw)}
                right={b+y*bp+x for y in range(bh) for x in range(bw)}
                self.assertEqual(f(a,ap,aw,ah,b,bp,bw,bh),bool(left&right))
            self.assertFalse(f(0,64,16,32,32,64,16,32))
            self.assertTrue(f(2**64-2,4,4,1,0,4,4,1))


if __name__=='__main__':unittest.main()
