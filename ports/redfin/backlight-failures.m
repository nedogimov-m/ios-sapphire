/* SPDX-License-Identifier: MIT */
/* Capture only native CoreBrightness error format strings for one explicit
 * boot. Forward the complete original encoded message untouched. Arguments,
 * private values and the encoded message buffer are never inspected or logged. */
#include <os/log.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include "native-image-uuid.h"
#include "display-benchmark.h"

static bool native_failures_enabled;
static unsigned native_failures_count;
static char native_failures_nonce[17];

void redfin_backlight_failures_prepare(const char *nonce)
{
    if(!nonce||strlen(nonce)!=16)return;
    char *end=NULL;uint64_t boot=strtoull(nonce,&end,16);
    if(!boot||end!=nonce+16)return;
    int fd=open(REDFIN_DISPLAY_PROBE_REQUEST,O_RDONLY|O_NOFOLLOW);
    if(fd<0)return;
    struct stat state={0};char request[128]={0};ssize_t bytes=-1;
    if(!fstat(fd,&state)&&S_ISREG(state.st_mode)&&state.st_uid==0&&!(state.st_mode&022)&&
       state.st_size>0&&state.st_size<(off_t)sizeof(request))bytes=read(fd,request,sizeof(request));
    close(fd);
    if(bytes<=0||redfin_display_probe_request(request,(size_t)bytes,boot)!=RF_DISPLAY_PROBE_CONTROLS_CHECKED)return;
    memcpy(native_failures_nonce,nonce,16);
    __atomic_store_n(&native_failures_enabled,true,__ATOMIC_RELEASE);
}
static void backlight_failure_format(void *dso,os_log_type_t type,const char *format)
{
    if(!__atomic_load_n(&native_failures_enabled,__ATOMIC_ACQUIRE)||!format||
       (type!=OS_LOG_TYPE_ERROR&&type!=OS_LOG_TYPE_FAULT))return;
    const uint8_t expected[16]={REDFIN_CB_UUID_BYTES};
    if(!redfin_native_header_uuid(dso,expected)||
       __atomic_fetch_add(&native_failures_count,1,__ATOMIC_RELAXED)>=32)return;
    char line[768];int count=snprintf(line,sizeof(line),
        "REDFIN NATIVE CB FAILURE: boot=%s type=%u format=%.512s\n",native_failures_nonce,(unsigned)type,format);
    if(count<0||(size_t)count>=sizeof(line))return;
    int fd=open("/private/var/mobile/Library/Logs/redfin-refresh.log",O_WRONLY|O_APPEND|O_CREAT|O_NOFOLLOW,0600);
    if(fd>=0){(void)write(fd,line,(size_t)count);close(fd);}
}
/* dyld leaves this defining image's own bindings on the original function. */
#define REDFIN_CB_LOG_FORWARD(name) \
static void redfin_cb_##name(void *dso,os_log_t log,os_log_type_t type,const char *format,uint8_t *buffer,uint32_t size) \
{backlight_failure_format(dso,type,format);name(dso,log,type,format,buffer,size);} \
__attribute__((used,section("__DATA,__interpose"))) \
static const struct {void (*replacement)(void *,os_log_t,os_log_type_t,const char *,uint8_t *,uint32_t); \
    void (*original)(void *,os_log_t,os_log_type_t,const char *,uint8_t *,uint32_t);} \
    redfin_cb_interpose_##name={redfin_cb_##name,name};
REDFIN_CB_LOG_FORWARD(_os_log_impl)
REDFIN_CB_LOG_FORWARD(_os_log_error_impl)
REDFIN_CB_LOG_FORWARD(_os_log_fault_impl)
