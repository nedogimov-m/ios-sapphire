/* SPDX-License-Identifier: APSL-2.0
 * Adapted from preferred hackios-xnu-kernel 8e611870 kern_minimac.c's
 * AMFI request0x5a ABI (Copyright2026 OOSEX GANG). Unlike that global
 * allow-all policy, this handler admits only backboardd in the exact GUI3.
 * All other callers/requests retain the previous ENOPOLICY result.
 * This file contains Modifications of Original Code subject to the Apple
 * Public Source License Version2.0; provided AS IS, WITHOUT WARRANTY.
 */
#include <pexpert/pexpert.h>
#include <arm64/redfin_gui_profile.h>
#include <sys/errno.h>

static int
redfin_graphics_amfi_syscall(struct proc *process,int call,user_addr_t address)
{
    if(call!=0x5a)return ENOPOLICY;
    const char *args=PE_boot_args();
    unsigned length=0;uint64_t nonce=0;
    if(!args)return ENOPOLICY;
    while(length<608 && args[length])length++;
    if(length==608 || !redfin_gpu_gui_profile(args,length+1,&nonce))return ENOPOLICY;
    char name[32]={0};
    proc_name(proc_pid(process),name,sizeof(name));
    if(strcmp(name,"backboardd"))return ENOPOLICY;
    struct {uint64_t input_flags;user_addr_t output_flags;} query;
    int error=copyin(address,&query,sizeof(query));
    if(error)return error;
    const uint64_t flags=0xff; /* preferred native dyld allow-path/env/insert/interpose ABI */
    error=copyout(&flags,query.output_flags,sizeof(flags));
    if(!error)printf("REDFIN GPU DYLD: boot=%016llx backboardd pid=%d GUI3 insertion permitted\n",
                    (unsigned long long)nonce,proc_pid(process));
    return error;
}
static const struct mac_policy_ops redfin_graphics_amfi_ops={
    .mpo_policy_syscall=redfin_graphics_amfi_syscall,
};
static struct mac_policy_conf redfin_graphics_amfi_conf={
    .mpc_name="AMFI",
    .mpc_fullname="Redfin GUI3 backboardd dyld adapter",
    .mpc_ops=&redfin_graphics_amfi_ops,
};
static mac_policy_handle_t redfin_graphics_amfi_handle;
static void redfin_graphics_amfi_register(void)
{
    int error=mac_policy_register(&redfin_graphics_amfi_conf,&redfin_graphics_amfi_handle,NULL);
    printf("REDFIN GPU DYLD: scoped AMFI policy %s (%d)\n",error?"NOT registered":"registered",error);
}
