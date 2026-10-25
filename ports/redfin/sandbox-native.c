/* SPDX-License-Identifier: MIT
 * Native20H392 libsystem_sandbox issue5/consume6/release7 ABI. Actual TCC makes
 * the authorization decision. This adapter supplies its missing opaque,
 * scoped extension transport; no TCC answer, grant, DB or entitlement is edited.
 */
#include <sys/param.h>
#include <sys/systm.h>
#include <sys/proc_internal.h>
#include <sys/codesign.h>
#include <sys/vnode.h>
#include <sys/kauth.h>
#include <sys/random.h>
#include <kern/locks.h>
#include <kern/kalloc.h>
#include <corecrypto/cchmac.h>
#include <corecrypto/ccsha2.h>
#include "sandbox-capabilities.h"
#include "sandbox-native.h"
struct rf_native_issue {uint64_t class_name,kind,resource,flags,output;int64_t pid;uint64_t version;};
struct rf_native_consume {uint64_t token,bytes,output;};
struct rf_native_release {uint64_t handle,reserved[2];};
_Static_assert(sizeof(struct rf_native_issue)==56,"native Sandbox issue ABI");
_Static_assert(sizeof(struct rf_native_consume)==24,"native Sandbox consume ABI");
_Static_assert(sizeof(struct rf_native_release)==24,"native Sandbox release ABI");
static LCK_GRP_DECLARE(rf_sandbox_group,"redfin-sandbox-extension");
static LCK_MTX_DECLARE(rf_sandbox_lock,&rf_sandbox_group);
static struct rf_sbx_registry registry;
static uint8_t boot_key[32];
static bool key_ready;
static unsigned trace_count;
static unsigned manager_trace_count;
static void lock_registry(void *p __unused){lck_mtx_lock(&rf_sandbox_lock);}
static void unlock_registry(void *p __unused){lck_mtx_unlock(&rf_sandbox_lock);}
static int entropy(void *p __unused,uint8_t *out,size_t bytes)
{if(!out||(bytes!=8&&bytes!=32))return EINVAL;read_random(out,(u_int)bytes);return 0;}
static int authenticate(void *p __unused,const uint8_t *data,size_t bytes,uint8_t out[32])
{
    if(!data||bytes>2048||!out)return EINVAL;
    lck_mtx_lock(&rf_sandbox_lock);
    if(!key_ready){read_random(boot_key,sizeof(boot_key));key_ready=true;}
    cchmac(ccsha256_di(),sizeof(boot_key),boot_key,bytes,data,out);
    lck_mtx_unlock(&rf_sandbox_lock);return 0;
}
static const struct rf_sbx_ops operations={NULL,entropy,authenticate,lock_registry,unlock_registry};
static struct rf_sbx_actor current_actor(proc_t p)
{
    struct rf_sbx_actor a={(uint32_t)proc_pid(p),(uint32_t)proc_pidversion(p),0,0};
    a.uid=kauth_cred_getuid(proc_ucred(p));return a;
}
static bool is_native_tcc_manager(proc_t p)
{
    const char *identity=csproc_get_identity(p);char path[MAXPATHLEN];int bytes=sizeof(path);
    if(!identity||strcmp(identity,"com.apple.tccd")||!csproc_get_platform_binary(p)||
        !(proc_getcsflags(p)&CS_VALID)||!p->p_textvp||vn_getpath(p->p_textvp,path,&bytes)||
        bytes<=0||bytes>(int)sizeof(path)||path[bytes-1])return false;
    return !strcmp(path,"/System/Library/PrivateFrameworks/TCC.framework/Support/tccd");
}
static void trace(proc_t p,unsigned operation,unsigned kind,unsigned flags,const char *name,int error)
{
    unsigned count=name?__atomic_fetch_add(&manager_trace_count,1,__ATOMIC_RELAXED):
        __atomic_fetch_add(&trace_count,1,__ATOMIC_RELAXED);
    if(count<48)
        printf("REDFIN SANDBOX EXTENSION: pid=%d operation=%u kind=%u flags=%#x class=%.159s result=%d native-policy-preserved=1 token-not-logged=1\n",
            proc_pid(p),operation,kind,flags,name?name:"(opaque)",error);
}
static int issue(proc_t p,user_addr_t address)
{
    struct rf_native_issue args;int error=copyin(address,&args,sizeof(args));if(error)return error;
    struct rf_sbx_actor owner=current_actor(p);owner.issuer=is_native_tcc_manager(p);
    if(!owner.issuer){trace(p,5,(unsigned)args.kind,(unsigned)args.flags,NULL,EACCES);return EACCES;}
    if(args.kind>UINT32_MAX||args.flags>UINT32_MAX||args.pid<0||args.pid>INT32_MAX||args.version>UINT32_MAX||
        !args.class_name||!args.output)return EINVAL;
    struct rf_sbx_request *q=kalloc_type(struct rf_sbx_request,Z_WAITOK|Z_ZERO);if(!q)return ENOMEM;
    q->kind=(uint32_t)args.kind;q->flags=(uint32_t)args.flags;q->target_pid=(uint32_t)args.pid;q->target_version=(uint32_t)args.version;
    size_t copied=0;error=copyinstr(args.class_name,q->class_name,sizeof(q->class_name),&copied);
    if(!error&&args.resource)error=copyinstr(args.resource,q->resource,sizeof(q->resource),&copied);
    if(!error&&(q->flags&RF_SBX_TARGET_PID)) {
        proc_t target=proc_find((int)q->target_pid);
        if(target==PROC_NULL)error=ESRCH;
        else {
            uint32_t version=(uint32_t)proc_pidversion(target);
            if((q->flags&RF_SBX_TARGET_VERSION)&&version!=q->target_version)error=ESRCH;
            else {q->target_version=version;q->flags|=RF_SBX_TARGET_VERSION;}
            proc_rele(target);
        }
    }
    char token[RF_SBX_TOKEN_BYTES];
    if(!error)error=rf_sbx_issue(&registry,&operations,&owner,q,token);
    if(!error)error=copyout(token,args.output,strlen(token)+1);
    trace(p,5,q->kind,q->flags,q->class_name,error);
    memset(token,0,sizeof(token));kfree_type(struct rf_sbx_request,q);return error;
}
static int consume(proc_t p,user_addr_t address)
{
    struct rf_native_consume args;int error=copyin(address,&args,sizeof(args));if(error)return error;
    if(!args.token||!args.output||!args.bytes||args.bytes>RF_SBX_TOKEN_BYTES)return EINVAL;
    char token[RF_SBX_TOKEN_BYTES];size_t bytes=0;
    error=copyinstr(args.token,token,(size_t)args.bytes,&bytes);if(error)return error;
    if(bytes!=args.bytes)return EINVAL;
    struct rf_sbx_actor owner=current_actor(p);uint64_t handle=0;
    error=rf_sbx_consume(&registry,&operations,&owner,token,bytes,&handle);
    if(!error) {
        error=copyout(&handle,args.output,sizeof(handle));
        if(error)(void)rf_sbx_release(&registry,&operations,&owner,handle);
    }
    trace(p,6,0,0,NULL,error);memset(token,0,sizeof(token));return error;
}
int redfin_sandbox_extension_call(proc_t p,int call,user_addr_t address)
{
    if(!p||p==kernproc||proc_is64bit(p)==0)return EINVAL;
    if(call==5)return issue(p,address);
    if(call==6)return consume(p,address);
    if(call==7) {
        struct rf_native_release args;int error=copyin(address,&args,sizeof(args));if(error)return error;
        if(!args.handle||args.reserved[0]||args.reserved[1])return EINVAL;
        struct rf_sbx_actor owner=current_actor(p);return rf_sbx_release(&registry,&operations,&owner,args.handle);
    }
    return ENOTSUP;
}
void redfin_sandbox_extension_exit(proc_t p)
{
    if(!p||p==kernproc)return;
    struct rf_sbx_actor owner={(uint32_t)proc_pid(p),(uint32_t)proc_pidversion(p),0,0};
    rf_sbx_exit(&registry,&operations,&owner);
}
