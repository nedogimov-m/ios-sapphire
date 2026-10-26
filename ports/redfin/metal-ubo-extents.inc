/* SPDX-License-Identifier: MIT
 * Read the exact pipeline NIR without changing it or its serialized metadata.
 * A bound covers EVERY explicit UBO read, including all blocks/functions.
 * Dynamic byte offsets may use Mesa's unsigned SSA upper-bound proof. Dynamic
 * bindings, unsupported reads and unknown/overflowing bounds stay conservative.
 */
#include "util/hash_table.h"
_Static_assert(PIPE_MAX_CONSTANT_BUFFERS==REDFIN_METAL_UBO_SLOTS,
   "constant snapshot analysis must match the paired Gallium binding domain");

static void
redfin_metal_ubo_unknown_all(struct redfin_metal_ubo_extents *out)
{
   for(unsigned i=0;i<REDFIN_METAL_UBO_SLOTS;++i)out->unbounded[i]=true;
}

static void
redfin_metal_ubo_read_extents(nir_shader *nir,struct redfin_metal_ubo_extents *out)
{
   memset(out,0,sizeof(*out));
   if(!nir){redfin_metal_ubo_unknown_all(out);return;}
   nir_foreach_function_impl(impl,nir) {
      /* Mesa keys this analysis by SSA index, which is local to an impl.
       * Never carry its cache into a different function. No shader, metadata
       * or SSA numbering is modified; this runs once when the stage is made. */
      struct hash_table *ranges=NULL;
      nir_foreach_block(block,impl) {
         nir_foreach_instr(instr,block) {
            if(instr->type==nir_instr_type_call) {
               redfin_metal_ubo_unknown_all(out);continue;
            }
            if(instr->type!=nir_instr_type_intrinsic)continue;
            const nir_intrinsic_instr *in=nir_instr_as_intrinsic(instr);
            const nir_intrinsic_info *description=&nir_intrinsic_infos[in->intrinsic];
            /* A dereference that has not been lowered to an explicit UBO load
             * is not described by the scalar-offset analysis below. */
            for(unsigned i=0;i<description->num_srcs;++i) {
               const nir_def *source=in->src[i].ssa;
               if(source&&source->parent_instr->type==nir_instr_type_deref&&
                  (nir_instr_as_deref(source->parent_instr)->modes&nir_var_mem_ubo))
                  redfin_metal_ubo_unknown_all(out);
            }
            if(in->intrinsic!=nir_intrinsic_load_ubo) {
               /* Includes size queries, vec4/driver UBO forms and implicit
                * uniform/push-constant storage. A query must see the original
                * descriptor size, not just the bytes of an explicit load. */
               if(strstr(description->name,"ubo")||strstr(description->name,"load_uniform")||
                  strstr(description->name,"push_constant")||
                  !strcmp(description->name,"load_constant"))redfin_metal_ubo_unknown_all(out);
               continue;
            }
            const nir_def *binding=in->src[0].ssa,*offset=in->src[1].ssa;
            if(!binding||binding->num_components!=1||!binding->bit_size||binding->bit_size>32||
               !nir_src_is_const(in->src[0])) {
               redfin_metal_ubo_unknown_all(out);continue;
            }
            unsigned slot=nir_src_as_uint(in->src[0]);
            if(slot>=REDFIN_METAL_UBO_SLOTS) {
               redfin_metal_ubo_unknown_all(out);continue;
            }
            if(!offset||offset->num_components!=1||!offset->bit_size||offset->bit_size>32||
               !in->def.num_components||
               !in->def.bit_size||(in->def.bit_size%8)) {
               out->unbounded[slot]=true;continue;
            }
            if(out->unbounded[slot])continue;
            uint64_t first;
            if(nir_src_is_const(in->src[1]))first=nir_src_as_uint(in->src[1]);
            else {
               if(!ranges)ranges=_mesa_hash_table_create(NULL,_mesa_hash_pointer,_mesa_key_pointer_equal);
               if(!ranges){out->unbounded[slot]=true;continue;}
               /* Use the generic conservative limits, not dispatch dimensions
                * or AIR type sizes. range/range_base are not an access proof. */
               first=nir_unsigned_upper_bound(nir,ranges,nir_get_scalar(in->src[1].ssa,0),NULL);
            }
            uint64_t bytes=(uint64_t)in->def.num_components*(in->def.bit_size/8);
            uint64_t end=first+bytes;
            if(!bytes||end>UINT32_MAX)out->unbounded[slot]=true;
            else if(end>out->bytes[slot])out->bytes[slot]=(uint32_t)end;
         }
      }
      if(ranges)_mesa_hash_table_destroy(ranges,NULL);
   }
}
