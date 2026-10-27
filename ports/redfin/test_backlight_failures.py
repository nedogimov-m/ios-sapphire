"""Native log forwarding preserves every argument and excludes encoded secrets."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parent

PRELUDE=r'''
#import <Foundation/Foundation.h>
#include <os/log.h>
#include <mach-o/loader.h>
#include <stdbool.h>
#include <stdint.h>
#include <assert.h>
#include <stdarg.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
static NSMutableString *transcript;
static void *expected_dso;static os_log_t expected_log;static os_log_type_t expected_type;
static const char *expected_format;static uint8_t *expected_buffer;static uint32_t expected_size;
static unsigned forwards[3];
static bool redfin_native_header_uuid(const struct mach_header_64 *header,const uint8_t uuid[16]) {
 return header==(void *)0x12340000&&uuid[0]==1;
}
#define REDFIN_CB_UUID_BYTES 1
static int fake_open(const char *name,int flags,...){(void)name;(void)flags;return 77;}
static ssize_t fake_write(int fd,const void *data,size_t size){assert(fd==77);
 [transcript appendString:[[NSString alloc] initWithBytes:data length:size encoding:NSUTF8StringEncoding]];return size;}
static int fake_close(int fd){assert(fd==77);return 0;}
#define open fake_open
#define write fake_write
#define close fake_close
static void forwarded(unsigned index,void *dso,os_log_t log,os_log_type_t type,const char *format,uint8_t *buffer,uint32_t size){
 assert(dso==expected_dso&&log==expected_log&&type==expected_type&&format==expected_format);
 assert(buffer==expected_buffer&&size==expected_size);++forwards[index];
}
#define _os_log_impl redfin_test_os_log_impl
#define _os_log_error_impl redfin_test_os_log_error_impl
#define _os_log_fault_impl redfin_test_os_log_fault_impl
static void _os_log_impl(void *dso,os_log_t log,os_log_type_t type,const char *format,uint8_t *buffer,uint32_t size){forwarded(0,dso,log,type,format,buffer,size);}
static void _os_log_error_impl(void *dso,os_log_t log,os_log_type_t type,const char *format,uint8_t *buffer,uint32_t size){forwarded(1,dso,log,type,format,buffer,size);}
static void _os_log_fault_impl(void *dso,os_log_t log,os_log_type_t type,const char *format,uint8_t *buffer,uint32_t size){forwarded(2,dso,log,type,format,buffer,size);}
'''
SUFFIX=r'''
static void emit(void *dso,os_log_type_t type){
 uint8_t secret[]="DO_NOT_LOG_SECRET_ARGUMENT";
 expected_dso=dso;expected_log=nil;expected_type=type;expected_format="native failure %{private}@";
 expected_buffer=secret;expected_size=sizeof(secret);
 redfin_cb__os_log_impl(dso,nil,type,expected_format,secret,sizeof(secret));
 redfin_cb__os_log_error_impl(dso,nil,type,expected_format,secret,sizeof(secret));
 redfin_cb__os_log_fault_impl(dso,nil,type,expected_format,secret,sizeof(secret));
 assert(!strcmp((char *)secret,"DO_NOT_LOG_SECRET_ARGUMENT"));
 assert(![transcript containsString:@"DO_NOT_LOG_SECRET_ARGUMENT"]);
}
int main(){@autoreleasepool{
 transcript=[NSMutableString new];memcpy(native_failures_nonce,"12345678abcdef01",17);
 emit((void *)0x12340000,OS_LOG_TYPE_ERROR);assert(transcript.length==0);
 native_failures_enabled=true;
 emit((void *)0x12340000,OS_LOG_TYPE_INFO);assert(transcript.length==0);
 emit((void *)0x56780000,OS_LOG_TYPE_ERROR);assert(transcript.length==0);
 emit((void *)0x12340000,OS_LOG_TYPE_ERROR);
 assert([transcript containsString:@"format=native failure %{private}@"]);
 assert([transcript containsString:@"boot=12345678abcdef01"]);
 for(unsigned i=0;i<16;++i)emit((void *)0x12340000,OS_LOG_TYPE_FAULT);
 NSArray *lines=[transcript componentsSeparatedByString:@"\n"];assert(lines.count==33);
 for(unsigned i=0;i<3;++i)assert(forwards[i]==20);
}return 0;}
'''


@unittest.skipUnless(sys.platform=='darwin','native Foundation runtime required')
class BacklightFailureTests(unittest.TestCase):
    def test_complete_original_messages_forward_while_only_matching_error_formats_are_captured(self):
        actual=(HERE/'backlight-failures.m').read_text().replace('#include "native-image-uuid.h"','')
        with tempfile.TemporaryDirectory(prefix='redfin-native-log-') as directory:
            root=Path(directory);p=root/'native.m';p.write_text(PRELUDE+actual+SUFFIX)
            compiled=subprocess.run(['xcrun','clang','-fobjc-arc','-fblocks','-O2','-Wall','-Wextra','-Werror',
                '-I'+str(HERE),'-framework','Foundation',str(p),'-o',str(root/'native')],capture_output=True,text=True)
            self.assertEqual(compiled.returncode,0,compiled.stderr)
            run=subprocess.run([str(root/'native')],capture_output=True,text=True,timeout=5)
            self.assertEqual(run.returncode,0,run.stderr)


if __name__=='__main__':unittest.main()
