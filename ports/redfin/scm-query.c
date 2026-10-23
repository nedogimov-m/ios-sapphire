/* SPDX-License-Identifier: MIT */
/* Included once by the board's diagnostic translation unit. No init hook here. */
#include <pexpert/arm64/board_config.h>
#if defined(ARM64_BOARD_CONFIG_SWEET)
#include <sys/param.h>
#include <sys/systm.h>
#include <sys/errno.h>
#include <kern/clock.h>
#include <pexpert/pexpert.h>
#include <pexpert/device_tree.h>
#include "redfin_scm_query.h"

extern int redfin_spmi_return_ready(void);
int redfin_scm_query_probe(void);
static bool sq_attempted;
static struct { char args[608]; unsigned bytes; } sq_context;
static const uint32_t sq_targets[]={0x02000201,0x02000202,0x02000205,0x02000206,0x02000207};
static bool sq_word(const char *p,unsigned bytes,const char *word)
{ return strlen(word)==bytes && !memcmp(p,word,bytes); }
static bool sq_flags(const char *args,unsigned bytes)
{
 static const char *const words[]={"debug=0xc","serial=3","cpus=1","keepsyms=1","-noprogress","rd=md0",
  "sweettouch=0","sweetkeys=0","sweetusb=0","sweetcpufreq=0","sweetbattery=0","modem=0","wifi=0","gpu=0",
  "redfingpu=3","redfinscm=1","redfinspmi=1","redfinreturn=1"};
 if(!args || !bytes || bytes>608 || args[bytes-1])return false;
 uint32_t seen=0;bool nonce_seen=false,trace=false;
 for(unsigned at=0;at<bytes-1;) {
  if(args[at]==' '){at++;continue;}
  unsigned first=at;while(at<bytes-1 && args[at]!=' ') {
   if((unsigned char)args[at]<33 || (unsigned char)args[at]>126)return false;at++;
  }
  unsigned n=at-first;bool known=false;
  for(unsigned i=0;i<sizeof(words)/sizeof(words[0]);i++)if(sq_word(args+first,n,words[i])) {
   if(seen&(1u<<i))return false;seen|=1u<<i;known=true;break;
  }
  if(known)continue;
  if(sq_word(args+first,n,"-enable_kprintf_spam")){if(trace)return false;trace=true;continue;}
  if(n==31 && !memcmp(args+first,"redfinbootid=0x",15)) {
   if(nonce_seen)return false;uint64_t value=0;
   for(unsigned i=15;i<31;i++) {
    unsigned digit=(unsigned)(args[first+i]-'0');
    if(digit>9){if(args[first+i]<'a'||args[first+i]>'f')return false;digit=(unsigned)(args[first+i]-'a'+10);}
    value=(value<<4)|digit;
   }
   if(!value)return false;nonce_seen=true;continue;
  }
  return false;
 }
 return nonce_seen && seen==((1u<<(sizeof(words)/sizeof(words[0])))-1);
}
static bool sq_property(const char *path,const char *key,const void *value,unsigned bytes)
{
 DTEntry node;const void *actual=NULL;unsigned length=0;
 return SecureDTLookupEntry(NULL,path,&node)==kSuccess &&
  SecureDTGetProperty(node,key,&actual,&length)==kSuccess && actual &&
  bytes==length && !memcmp(actual,value,bytes);
}
static bool sq_contract(void)
{
 const uint32_t schema=1,pas[]={4,13};const uint64_t base=0x180000000ULL,bytes=0x80000000ULL;
 return sq_property("/chosen","dram-base",&base,8) && sq_property("/chosen","dram-size",&bytes,8) &&
  sq_property("/redfin-scm-query","query-only",&schema,4) &&
  sq_property("/redfin-scm-query","pas-ids",pas,sizeof(pas)) &&
  sq_property("/redfin-scm-query","functions",sq_targets,sizeof(sq_targets));
}
static bool sq_valid(void *context)
{
 const char *live=PE_boot_args();
 return context==&sq_context && live && sq_context.bytes &&
  !memcmp(live,sq_context.args,sq_context.bytes) &&
  __builtin_arm_rsr64("CurrentEL")==4 && !(__builtin_arm_rsr64("MPIDR_EL1")&0xff00ffffffULL) &&
  redfin_spmi_return_ready()==1 && sq_contract();
}
static int sq_invoke(void *context,struct rf_sq_regs *r)
{
 if(!sq_valid(context) || !r)return ECANCELED;
 register uint64_t x0 __asm__("x0")=r->x[0],x1 __asm__("x1")=r->x[1],x2 __asm__("x2")=r->x[2],
  x3 __asm__("x3")=r->x[3],x4 __asm__("x4")=r->x[4],x5 __asm__("x5")=r->x[5],
  x6 __asm__("x6")=r->x[6],x7 __asm__("x7")=0;
 __asm__ volatile("smc #0" : "+r"(x0),"+r"(x1),"+r"(x2),"+r"(x3),"+r"(x4),"+r"(x5),"+r"(x6),"+r"(x7)
  : : "x8","x9","x10","x11","x12","x13","x14","x15","x16","x17","cc","memory");
 r->x[0]=x0;r->x[1]=x1;r->x[2]=x2;r->x[3]=x3;r->x[4]=x4;r->x[5]=x5;r->x[6]=x6;r->x[7]=x7;
 return 0;
}
static void sq_delay(void *context,unsigned us){(void)context;delay(us);}
static uint64_t sq_time(void *context)
{ (void)context;uint64_t ns=0;absolutetime_to_nanoseconds(mach_absolute_time(),&ns);return ns; }
static int sq_query(const struct rf_sq_ops *ops,unsigned width,unsigned kind,uint32_t arg,struct rf_sq_report *report)
{
 int result=rf_sq_run(ops,width,kind,arg,report);
 printf("REDFIN SCM QUERY: kind=%u arg=%#x width=%u fn=%#llx result=%d status=%lld value=%#llx/%#llx/%#llx calls=%u resumes=%u busy=%u complete=%u\n",
  kind,arg,width,report->function,result,report->status,report->value[0],report->value[1],report->value[2],
  report->calls,report->resumes,report->busy_retries,report->completed);
 return result;
}
int redfin_scm_query_probe(void)
{
 if(__atomic_exchange_n(&sq_attempted,true,__ATOMIC_ACQ_REL))return EBUSY;
 const char *args=PE_boot_args();unsigned length=0;
 if(!args)return EINVAL;
 while(length<sizeof(sq_context.args) && args[length])length++;
 if(length==sizeof(sq_context.args) || !sq_flags(args,length+1))return ENOTSUP;
 memcpy(sq_context.args,args,length+1);sq_context.bytes=length+1;
 if(!sq_valid(&sq_context))return ENXIO;
 const struct rf_sq_ops ops={&sq_context,sq_valid,sq_invoke,sq_delay,sq_time};
 struct rf_sq_report report;unsigned width=64;
 int result=sq_query(&ops,width,RF_SQ_DETECT,0,&report);
 if(result || !report.value[0]) {
  width=32;result=sq_query(&ops,width,RF_SQ_DETECT,0,&report);
 }
 if(result || !report.value[0])return ENOTSUP;
 bool pas_supported_query=false;
 for(unsigned i=0;i<sizeof(sq_targets)/sizeof(sq_targets[0]);i++) {
  result=sq_query(&ops,width,RF_SQ_AVAILABLE,sq_targets[i],&report);
  if(!sq_valid(&sq_context))return ECANCELED;
  if(sq_targets[i]==0x02000207)pas_supported_query=!result && report.value[0]!=0;
 }
 if(pas_supported_query)for(unsigned i=0;i<2;i++) {
  result=sq_query(&ops,width,RF_SQ_PAS_SUPPORTED,i?13:4,&report);
  if(!sq_valid(&sq_context))return ECANCELED;
 }
 printf("REDFIN SCM QUERY: finished query-only ABI/call/PAS capability audit; no init/auth/reset/shutdown/assignment\n");
 return 0;
}
#endif /* ARM64_BOARD_CONFIG_SWEET */
