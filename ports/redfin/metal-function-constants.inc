/* SPDX-License-Identifier: MIT */
static int
rwa_redfin_constants_for_module(void *context,const void *bitcode,size_t bytes,
    const struct redfin_metal_constants *supplied,struct air_constant_value **out,
    char *why,size_t why_size)
{
   unsigned count=air_module_function_constants(context,bitcode,bytes,out);
   if(!supplied)return (int)count; /* preserved legacy AIR harness contract */
   if(supplied->reserved||supplied->count>REDFIN_METAL_CONSTANTS_MAX||
      (supplied->count&&!supplied->values)) {
      say(why,why_size,"invalid native function constant snapshot");return -1;
   }
   for(unsigned i=0;i<count;++i)(*out)[i].undefined=true;
   for(unsigned i=0;i<supplied->count;++i) {
      const struct redfin_metal_constant *value=&supplied->values[i];
      if(!value->bytes||value->bytes>sizeof(value->words)) {
         say(why,why_size,"function constant %u has an invalid payload",value->index);return -1;
      }
      for(unsigned j=0;j<i;++j)if(supplied->values[j].index==value->index) {
         say(why,why_size,"duplicate function constant %u",value->index);return -1;
      }
      bool matched=false;
      for(unsigned j=0;j<count;++j)if((*out)[j].index==value->index) {
         memcpy((*out)[j].words,value->words,value->bytes);(*out)[j].undefined=false;matched=true;
      }
      if(!matched) {
         say(why,why_size,"function constant %u is absent from the actual module",value->index);return -1;
      }
   }
   return (int)count;
}
