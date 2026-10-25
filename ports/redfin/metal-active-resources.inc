/* SPDX-License-Identifier: MIT */
/* Pipeline requirements come from specialized executable NIR. Declaration and
 * argument-buffer layout queries keep the full, original ABI independently.
 * Indices are never compacted. Unknown dynamic choices conservatively keep a
 * resource, so this cannot hide a live binding by guessing its runtime value.
 */
static bool
redfin_binding_may_equal(nir_def *def, unsigned component, uint32_t value, unsigned depth)
{
   if (!def || component >= def->num_components || depth >= 32)
      return true;
   if (nir_src_is_const(nir_src_for_ssa(def)))
      return (uint32_t)nir_src_comp_as_uint(nir_src_for_ssa(def), component) == value;
   nir_instr *instruction = def->parent_instr;
   if (instruction->type == nir_instr_type_phi) {
      nir_phi_instr *phi = nir_instr_as_phi(instruction);
      nir_foreach_phi_src(source, phi)
         if (redfin_binding_may_equal(source->src.ssa, component, value, depth + 1))
            return true;
      return false;
   }
   if (instruction->type != nir_instr_type_alu)
      return true;
   nir_alu_instr *alu = nir_instr_as_alu(instruction);
#define RF_MATCH(source, wanted) \
   redfin_binding_may_equal(alu->src[source].src.ssa, alu->src[source].swizzle[component], wanted, depth + 1)
   if (nir_op_is_vec(alu->op))
      return redfin_binding_may_equal(alu->src[component].src.ssa,
                                      alu->src[component].swizzle[0], value, depth + 1);
   switch (alu->op) {
   case nir_op_mov:
      return RF_MATCH(0, value);
   case nir_op_bcsel:
      return RF_MATCH(1, value) || RF_MATCH(2, value);
   case nir_op_b2i8:
   case nir_op_b2i16:
   case nir_op_b2i32:
   case nir_op_b2i64:
      return value <= 1;
   case nir_op_ineg:
      return RF_MATCH(0, 0u - value);
   case nir_op_inot:
      return RF_MATCH(0, ~value);
   case nir_op_u2u8:
   case nir_op_u2u16:
   case nir_op_u2u32:
   case nir_op_u2u64:
      if (def->bit_size < 32 && value >= (1u << def->bit_size))
         return false;
      if (alu->src[0].src.ssa->bit_size <= def->bit_size)
         return RF_MATCH(0, value);
      return true;
   case nir_op_iadd:
      for (unsigned source = 0; source < 2; source++) {
         if (!nir_src_is_const(alu->src[source].src))
            continue;
         uint32_t add = nir_src_comp_as_uint(alu->src[source].src,
                                              alu->src[source].swizzle[component]);
         return RF_MATCH(1 - source, value - add);
      }
      return true;
   case nir_op_iand:
      for (unsigned source = 0; source < 2; source++) {
         if (nir_src_is_const(alu->src[source].src)) {
            uint32_t mask = nir_src_comp_as_uint(alu->src[source].src,
                                                  alu->src[source].swizzle[component]);
            if (value & ~mask)
               return false;
         }
      }
      return true;
   default:
      return true;
   }
#undef RF_MATCH
}

static bool
redfin_texture_binding_may_equal(nir_tex_instr *texture, bool sampler, unsigned index)
{
   unsigned base = sampler ? texture->sampler_index : texture->texture_index;
   int offset = nir_tex_instr_src_index(texture, sampler ? nir_tex_src_sampler_offset :
                                                          nir_tex_src_texture_offset);
   return offset < 0 ? base == index :
      redfin_binding_may_equal(texture->src[offset].src.ssa, 0, index - base, 0);
}

static bool
redfin_pipeline_resource_used(nir_shader *nir, const struct air_resource *resource)
{
   if (resource->kind == AIR_RESOURCE_THREADGROUP_BUFFER)
      return true; /* retain the existing explicit dynamic-threadgroup contract */
   nir_foreach_function_impl(impl, nir) {
      nir_foreach_block(block, impl) {
         nir_foreach_instr(instruction, block) {
            if (instruction->type == nir_instr_type_tex) {
               nir_tex_instr *texture = nir_instr_as_tex(instruction);
               if (resource->kind == AIR_RESOURCE_TEXTURE &&
                   redfin_texture_binding_may_equal(texture, false, resource->index))
                  return true;
               if (resource->kind == AIR_RESOURCE_SAMPLER &&
                   nir_tex_instr_need_sampler(texture) &&
                   redfin_texture_binding_may_equal(texture, true, resource->index))
                  return true;
               continue;
            }
            if (instruction->type != nir_instr_type_intrinsic)
               continue;
            nir_intrinsic_instr *in = nir_instr_as_intrinsic(instruction);
            enum air_resource_kind kind;
            unsigned source = 0;
            switch (in->intrinsic) {
            case nir_intrinsic_load_ubo:
            case nir_intrinsic_load_ubo_vec4:
            case nir_intrinsic_get_ubo_size:
               kind = AIR_RESOURCE_CONSTANT_BUFFER;
               break;
            case nir_intrinsic_load_ssbo:
            case nir_intrinsic_get_ssbo_size:
            case nir_intrinsic_ssbo_atomic:
            case nir_intrinsic_ssbo_atomic_swap:
               kind = AIR_RESOURCE_DEVICE_BUFFER;
               break;
            case nir_intrinsic_store_ssbo:
               kind = AIR_RESOURCE_DEVICE_BUFFER;
               source = 1;
               break;
            default:
               /* AIR emits indexed image_* intrinsics. Deref/bindless variants
                * are not part of its resource representation at this stage. */
               if (strncmp(nir_intrinsic_infos[in->intrinsic].name, "image_", 6))
                  continue;
               kind = AIR_RESOURCE_IMAGE;
               break;
            }
            if (resource->kind == kind &&
                redfin_binding_may_equal(in->src[source].ssa, 0, resource->index, 0))
               return true;
         }
      }
   }
   return false;
}

static void
redfin_pipeline_requirements(nir_shader *nir, struct air_shader_info *info)
{
   unsigned declared = info->num_resources, active = 0;
   for (unsigned i = 0; i < declared; i++) {
      struct air_resource resource = info->resources[i];
      if (redfin_pipeline_resource_used(nir, &resource))
         info->resources[active++] = resource;
   }
   info->num_resources = active;
   info->raster_order_groups = 0;
   nir->info.num_ubos = 0;
   nir->info.num_ssbos = 0;
   nir->info.num_textures = 0;
   nir->info.num_images = 0;
   BITSET_ZERO(nir->info.textures_used);
   BITSET_ZERO(nir->info.images_used);
   for (unsigned i = 0; i < active; i++) {
      const struct air_resource *resource = &info->resources[i];
      if (resource->raster_order_group >= 0)
         info->raster_order_groups |= 1u << resource->raster_order_group;
      switch (resource->kind) {
      case AIR_RESOURCE_CONSTANT_BUFFER:
         nir->info.num_ubos = MAX2(nir->info.num_ubos, resource->index + 1); break;
      case AIR_RESOURCE_DEVICE_BUFFER:
         nir->info.num_ssbos = MAX2(nir->info.num_ssbos, resource->index + 1); break;
      case AIR_RESOURCE_TEXTURE:
         nir->info.num_textures = MAX2(nir->info.num_textures, resource->index + 1);
         BITSET_SET(nir->info.textures_used, resource->index); break;
      case AIR_RESOURCE_IMAGE:
         nir->info.num_images = MAX2(nir->info.num_images, resource->index + 1);
         BITSET_SET(nir->info.images_used, resource->index); break;
      default: break;
      }
   }
   if (nir->info.stage == MESA_SHADER_VERTEX) {
      NIR_PASS(_, nir, nir_remove_dead_variables, nir_var_shader_in, NULL);
      nir->num_inputs = 0;
      nir->info.inputs_read = 0;
      info->vertex_attributes_read = 0;
      for (unsigned i = 0; i < info->num_vertex_attributes; i++) {
         struct air_vertex_attribute *attribute = &info->vertex_attributes[i];
         attribute->used = false;
         attribute->driver_location = ~0u;
      }
      nir_foreach_shader_in_variable(variable, nir) {
         variable->data.driver_location = nir->num_inputs++;
         nir->info.inputs_read |= BITFIELD64_BIT(variable->data.location);
         for (unsigned i = 0; i < info->num_vertex_attributes; i++) {
            struct air_vertex_attribute *attribute = &info->vertex_attributes[i];
            if (variable->data.location != VERT_ATTRIB_GENERIC0 + attribute->index)
               continue;
            attribute->used = true;
            attribute->driver_location = variable->data.driver_location;
            info->vertex_attributes_read |= 1u << attribute->index;
         }
      }
   }
   static unsigned reports;
   if (declared != active && __sync_fetch_and_add(&reports, 1) < 64)
      printf("REDFIN AIR PIPELINE RESOURCES: function=%s declared=%u active=%u original-indices=1\n",
             info->entry_point ? info->entry_point : "unnamed", declared, active);
}
