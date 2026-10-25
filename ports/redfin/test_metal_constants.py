"""A specialization owns exact scalar/vector values and preserves absence."""
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent


class MetalConstantsTests(unittest.TestCase):
    def test_native_snapshot_distinguishes_zero_absence_and_copies_full_vectors(self):
        source=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <stdio.h>
#include "metal-function-constants.h"
struct air_constant_value {unsigned index;union {uint64_t bits;uint64_t words[4];};bool undefined;};
static unsigned air_module_function_constants(void *ctx,const void *data,size_t bytes,struct air_constant_value **out)
{
 (void)ctx;(void)data;(void)bytes;*out=calloc(3,sizeof(**out));
 (*out)[0].index=7;(*out)[1].index=41;(*out)[2].index=58;return 3;
}
static void say(char *why,size_t bytes,const char *format,...)
{va_list args;va_start(args,format);vsnprintf(why,bytes,format,args);va_end(args);}
#include "metal-function-constants.inc"
int main(void)
{
 char why[128]={0};struct air_constant_value *values=NULL;
 const uint8_t vector[32]={1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,
  17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32};
 struct redfin_metal_constant supplied[2]={{.index=41,.bytes=32},{.index=58,.bytes=3}};
 memcpy(supplied[0].words,vector,sizeof(vector));memcpy(supplied[1].words,"\3\21\107",3);
 struct redfin_metal_constants set={.values=supplied,.count=2};
 assert(rwa_redfin_constants_for_module(NULL,NULL,0,&set,&values,why,sizeof(why))==3);
 assert(values[0].undefined&&!values[0].bits&&!values[1].undefined&&!values[2].undefined);
 assert(!memcmp(values[1].words,vector,32));assert(values[2].bits==0x471103);
 memset(supplied,0,sizeof(supplied));assert(!memcmp(values[1].words,vector,32));free(values);
 supplied[0]=(struct redfin_metal_constant){.index=7,.bytes=4};set.count=1;
 assert(rwa_redfin_constants_for_module(NULL,NULL,0,&set,&values,why,sizeof(why))==3);
 assert(!values[0].undefined&&!values[0].bits&&values[1].undefined&&values[2].undefined);free(values);
 supplied[1]=supplied[0];set.count=2;
 assert(rwa_redfin_constants_for_module(NULL,NULL,0,&set,&values,why,sizeof(why))<0);
 assert(strstr(why,"duplicate"));free(values);
 set.count=1;supplied[0].index=99;
 assert(rwa_redfin_constants_for_module(NULL,NULL,0,&set,&values,why,sizeof(why))<0);
 assert(strstr(why,"absent"));free(values);
 supplied[0].index=7;supplied[0].bytes=33;
 assert(rwa_redfin_constants_for_module(NULL,NULL,0,&set,&values,why,sizeof(why))<0);free(values);
 set.count=0;set.reserved=1;
 assert(rwa_redfin_constants_for_module(NULL,NULL,0,&set,&values,why,sizeof(why))<0);free(values);
 assert(rwa_redfin_constants_for_module(NULL,NULL,0,NULL,&values,why,sizeof(why))==3);
 assert(!values[0].undefined&&!values[1].undefined);free(values);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);(out/'constants.c').write_text(source)
            compiled=subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror','-I',str(HERE),
                str(out/'constants.c'),'-o',str(out/'constants')],capture_output=True)
            self.assertEqual(compiled.returncode,0,compiled.stderr.decode(errors='replace'))
            subprocess.run([str(out/'constants')],check=True,capture_output=True,timeout=10)


if __name__=='__main__':unittest.main()
