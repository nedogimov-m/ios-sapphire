/* SPDX-License-Identifier: MIT
 * Own-task accounting only. TASK_VM_INFO is supplied by the native kernel;
 * this observer neither changes a memory limit nor needs a jetsam entitlement.
 */
#ifndef REDFIN_GRAPHICS_MEMORY_REPORT_H
#define REDFIN_GRAPHICS_MEMORY_REPORT_H
#include <mach/mach.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/sysctl.h>
#include <unistd.h>
#include "gui-profile.h"

static inline void redfin_graphics_memory_report(const char *phase,unsigned ordinal)
{
    char args[608]={0};size_t bytes=sizeof(args);uint64_t nonce=0;
    if(sysctlbyname("kern.bootargs",args,&bytes,NULL,0) || bytes>sizeof(args) ||
       !redfin_gpu_gui_profile(args,(unsigned)bytes,&nonce))return;
    task_vm_info_data_t info={0};
    mach_msg_type_number_t count=TASK_VM_INFO_REV4_COUNT;
    kern_return_t status=task_info(mach_task_self(),TASK_VM_INFO,(task_info_t)&info,&count);
    int footprint_valid=status==KERN_SUCCESS && count>=TASK_VM_INFO_REV1_COUNT;
    /* 8796 returns zero remaining bytes for every !isApp daemon, including
     * backboardd and our checker. Field presence alone cannot establish a
     * usable process limit. A zero also cannot distinguish an exhausted app.
     */
    int limit_valid=footprint_valid && count>=TASK_VM_INFO_REV4_COUNT &&
        info.limit_bytes_remaining!=0;
    uint64_t footprint=footprint_valid?info.phys_footprint:0;
    uint64_t remaining=limit_valid?info.limit_bytes_remaining:0;
    uint64_t limit=limit_valid && remaining<=UINT64_MAX-footprint?footprint+remaining:0;
    dprintf(2,"REDFIN GRAPHICS MEMORY: boot=%016llx pid=%d phase=%s ordinal=%u status=%d words=%u footprint-valid=%d footprint-KiB=%llu resident-KiB=%llu limit-valid=%d remaining-KiB=%llu effective-limit-KiB=%llu\n",
        (unsigned long long)nonce,getpid(),phase,ordinal,status,count,footprint_valid,
        (unsigned long long)(footprint/1024),
        (unsigned long long)(status==KERN_SUCCESS?info.resident_size/1024:0),limit_valid,
        (unsigned long long)(remaining/1024),(unsigned long long)(limit/1024));
}
#endif
