/* SPDX-License-Identifier: MIT */
#include <dlfcn.h>
#include <dispatch/dispatch.h>
#include <mach-o/loader.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
#include "brightness-system.h"

static float (*system_get)(void);
static void (*system_set)(float);
static bool system_ready;

static bool brightness_native_uuid(const void *function)
{
    Dl_info info={0};
    if(!function||!dladdr(function,&info)||!info.dli_fbase)return false;
    const struct mach_header_64 *header=info.dli_fbase;
    if(header->magic!=MH_MAGIC_64||header->ncmds>256||header->sizeofcmds>65536)return false;
    const uint8_t expected[]={REDFIN_BKS_UUID_BYTES};
    _Static_assert(sizeof(expected)==16,"native BackBoardServices UUID must be exactly16bytes");
    const unsigned char *at=(const unsigned char *)(header+1),*end=at+header->sizeofcmds;
    for(unsigned i=0;i<header->ncmds;++i) {
        if((size_t)(end-at)<sizeof(struct load_command))return false;
        const struct load_command *command=(const void *)at;
        if(command->cmdsize<sizeof(*command)||command->cmdsize>(size_t)(end-at))return false;
        if(command->cmd==LC_UUID)return command->cmdsize==sizeof(struct uuid_command)&&
            !memcmp(((const struct uuid_command *)command)->uuid,expected,sizeof(expected));
        at+=command->cmdsize;
    }
    return false;
}

bool redfin_brightness_system_ready(void)
{
    static dispatch_once_t once;
    dispatch_once(&once,^{
        void *library=dlopen("/System/Library/PrivateFrameworks/BackBoardServices.framework/BackBoardServices",RTLD_NOW|RTLD_LOCAL);
        if(!library)return;
        void *get=dlsym(library,"BKSDisplayBrightnessGetCurrent");
        void *set=dlsym(library,"BKSDisplayBrightnessSetWithImplicitTransaction");
        if(brightness_native_uuid(get)&&brightness_native_uuid(set)) {
            system_get=(float (*)(void))get;system_set=(void (*)(float))set;system_ready=true;
        }
        /* Keep the exact native image loaded for the process lifetime. */
    });
    return system_ready;
}

float redfin_brightness_system_get(void)
{
    if(!redfin_brightness_system_ready())return NAN;
    float value=system_get();return isfinite(value)&&value>=0&&value<=1?value:NAN;
}

bool redfin_brightness_system_set(float value)
{
    if(!isfinite(value)||value<0||value>1||!redfin_brightness_system_ready())return false;
    system_set(value);return true; /* Issued, not proof of hardware completion. */
}
