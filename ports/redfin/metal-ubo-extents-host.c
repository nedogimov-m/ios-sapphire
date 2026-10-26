/* SPDX-License-Identifier: MIT
 * Execute the actual analysis on real Mesa NIR. Serialize before and after
 * every analysis so a runtime optimization cannot silently become a compiler
 * change under the old shader-cache identity. */
#undef NDEBUG
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "nir.h"
#include "nir_builder.h"
#include "nir_serialize.h"
#include "pipe/p_state.h"
#include "util/blob.h"
#include "metal-ubo-extents.h"
#include "metal-ubo-extents.inc"

static const nir_shader_compiler_options options={0};
static nir_builder shader(void)
{return nir_builder_init_simple_shader(MESA_SHADER_COMPUTE,&options,"UBO extent contract");}
static void fixed(nir_builder *b,unsigned slot,uint32_t offset,unsigned components,unsigned bits)
{
   (void)nir_load_ubo(b,components,bits,nir_imm_int(b,slot),nir_imm_int(b,offset),
      .align_mul=1,.align_offset=0,.range_base=0,.range=~0u);
}
static struct redfin_metal_ubo_extents analyze(nir_builder *b)
{
   struct blob before,after;blob_init(&before);blob_init(&after);
   nir_serialize(&before,b->shader,false);
   struct redfin_metal_ubo_extents out;
   redfin_metal_ubo_read_extents(b->shader,&out);
   nir_serialize(&after,b->shader,false);
   assert(before.size==after.size&&!memcmp(before.data,after.data,before.size));
   blob_finish(&before);blob_finish(&after);return out;
}
static void extent(const struct redfin_metal_ubo_extents *e,unsigned slot,size_t remaining,size_t wanted,bool proof)
{
   bool proven=!proof;
   assert(redfin_metal_ubo_snapshot_bytes(e,slot,remaining,&proven)==wanted);
   assert(proven==proof);
}
int main(void)
{
   glsl_type_singleton_init_or_ref();unsigned cases=0;
   nir_builder b=shader();fixed(&b,1,0,1,32);fixed(&b,1,52,1,32);fixed(&b,31,96,2,64);
   struct redfin_metal_ubo_extents e=analyze(&b);
   extent(&e,1,256*1024,56,true);extent(&e,31,256*1024,112,true);
   extent(&e,2,256*1024,256*1024,false);extent(&e,32,64,64,false);
   /* A proof larger than this particular view is not evidence of a bad
    * caller: the access can be conditional. Keep its existing full extent. */
   extent(&e,1,32,32,false);ralloc_free(b.shader);++cases;

   b=shader();fixed(&b,3,60,3,16);e=analyze(&b);extent(&e,3,1000,66,true);ralloc_free(b.shader);++cases;

   b=shader();fixed(&b,1,0,1,32);fixed(&b,2,52,1,32);
   nir_def *dynamic=nir_channel(&b,nir_load_local_invocation_id(&b),0);
   (void)nir_load_ubo(&b,1,32,nir_imm_int(&b,1),dynamic,.align_mul=1,.range_base=0,.range=4);
   fixed(&b,1,4,1,32);e=analyze(&b);
   extent(&e,1,4096,4096,false);extent(&e,2,4096,56,true);ralloc_free(b.shader);++cases;

   b=shader();fixed(&b,0,0,1,32);dynamic=nir_channel(&b,nir_load_local_invocation_id(&b),0);
   (void)nir_load_ubo(&b,1,32,dynamic,nir_imm_int(&b,0),.align_mul=1,.range=4);
   e=analyze(&b);extent(&e,0,4096,4096,false);ralloc_free(b.shader);++cases;

   b=shader();fixed(&b,1,UINT32_MAX-1,1,32);e=analyze(&b);
   extent(&e,1,128,128,false);ralloc_free(b.shader);++cases;

   b=shader();fixed(&b,0,0,1,32);
   nir_intrinsic_instr *size=nir_intrinsic_instr_create(b.shader,nir_intrinsic_get_ubo_size);
   size->src[0]=nir_src_for_ssa(nir_imm_int(&b,0));nir_def_init(&size->instr,&size->def,1,32);
   nir_builder_instr_insert(&b,&size->instr);e=analyze(&b);
   extent(&e,0,8192,8192,false);ralloc_free(b.shader);++cases;

   b=shader();fixed(&b,0,0,1,32);
   nir_variable *variable=nir_variable_create(b.shader,nir_var_mem_ubo,glsl_uint_type(),"unlowered UBO");
   (void)nir_load_deref(&b,nir_build_deref_var(&b,variable));e=analyze(&b);
   extent(&e,0,8192,8192,false);ralloc_free(b.shader);++cases;

   b=shader();fixed(&b,0,0,1,32);
   nir_function *callee=nir_function_create(b.shader,"opaque call");
   nir_call_instr *call=nir_call_instr_create(b.shader,callee);nir_builder_instr_insert(&b,&call->instr);
   e=analyze(&b);extent(&e,0,8192,8192,false);ralloc_free(b.shader);++cases;

   redfin_metal_ubo_read_extents(NULL,&e);extent(&e,0,8192,8192,false);
   extent(NULL,0,8192,8192,false);++cases;
   glsl_type_singleton_decref();
   printf("NIR UBO EXTENTS: cases=%u fixed-half-vector64-boundaries=1 unknown-dominates=1 dynamic-binding-size-deref-call-fallback=1 serialized-NIR-unchanged=1\n",cases);
   return 0;
}
