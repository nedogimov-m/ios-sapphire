/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_NATIVE_IMAGE_UUID_H
#define REDFIN_NATIVE_IMAGE_UUID_H
#include <dlfcn.h>
#include <mach-o/loader.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

static inline bool redfin_native_header_uuid(const struct mach_header_64 *header,const uint8_t expected[16])
{
    if(!header||!expected||header->magic!=MH_MAGIC_64||header->ncmds>4096||header->sizeofcmds>1048576)return false;
    const unsigned char *at=(const unsigned char *)(header+1),*end=at+header->sizeofcmds;
    for(unsigned i=0;i<header->ncmds;++i) {
        if((size_t)(end-at)<sizeof(struct load_command))return false;
        const struct load_command *command=(const void *)at;
        if(command->cmdsize<sizeof(*command)||command->cmdsize>(size_t)(end-at))return false;
        if(command->cmd==LC_UUID)return command->cmdsize==sizeof(struct uuid_command)&&
            !memcmp(((const struct uuid_command *)command)->uuid,expected,16);
        at+=command->cmdsize;
    }
    return false;
}
static inline bool redfin_native_image_uuid(const void *function,const uint8_t expected[16])
{
    Dl_info info={0};
    return function&&dladdr(function,&info)&&info.dli_fbase&&redfin_native_header_uuid(info.dli_fbase,expected);
}
#endif
