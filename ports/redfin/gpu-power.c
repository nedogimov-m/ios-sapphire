/* Sole md0/UP CX-power owner. The inherited A610 backend stays disabled. */
#include <pexpert/arm64/board_config.h>
#if defined(ARM64_BOARD_CONFIG_SWEET)
#include <sys/param.h>
#include <sys/systm.h>
#include <sys/errno.h>
#include <kern/clock.h>
#include <pexpert/pexpert.h>
#include <pexpert/device_tree.h>
#include <machine/machine_routines.h>
#include "redfin_gpu_power.h"
extern int redfin_spmi_return_ready(void);
extern vm_offset_t ml_io_map(vm_offset_t,vm_size_t);
extern vm_offset_t ml_io_map_wcomb(vm_offset_t,vm_size_t);
int redfin_gpu_power_probe(void);
static bool gp_attempted;
struct gp_context {vm_offset_t base[4],db;char args[608];unsigned bytes;};
static struct gp_context gp;
static struct rf_gp_report gp_report;
static bool gp_word(const char *p,unsigned n,const char *s)
{return strlen(s)==n && !memcmp(p,s,n);}
static bool gp_flags(const char *args,unsigned bytes)
{
 static const char *words[]={"debug=0xc","serial=3","cpus=1","keepsyms=1","-noprogress","rd=md0",
  "sweettouch=0","sweetkeys=0","sweetusb=0","sweetcpufreq=0","sweetbattery=0","modem=0","wifi=0","gpu=0",
  "redfingpu=2","redfingpupower=1","redfinrpmh=1","redfinspmi=1","redfinreturn=1"};
 unsigned seen=0;bool nonce_seen=false,trace_seen=false;
 if(!args || !bytes || bytes>608 || args[bytes-1]) return false;
 for(unsigned at=0;at<bytes-1;) {
  if(args[at]==' ') {at++;continue;}
  unsigned first=at;while(at<bytes-1 && args[at]!=' ') {if((unsigned char)args[at]<33 || (unsigned char)args[at]>126)return false;at++;}
  unsigned n=at-first;bool known=false;
  for(unsigned i=0;i<sizeof(words)/sizeof(words[0]);i++) if(gp_word(args+first,n,words[i])) {
   if(seen&(1u<<i)) return false;
   seen|=1u<<i;known=true;break;
  }
  if(known)continue;
  if(gp_word(args+first,n,"-enable_kprintf_spam")) {if(trace_seen)return false;trace_seen=true;continue;}
  if(n==31 && !memcmp(args+first,"redfinbootid=0x",15)) {
   if(nonce_seen)return false;uint64_t nonce=0;
   for(unsigned i=15;i<31;i++) {unsigned d=(unsigned)(args[first+i]-'0');
    if(d>9) {if(args[first+i]<'a'||args[first+i]>'f')return false;d=(unsigned)(args[first+i]-'a'+10);}
    nonce=(nonce<<4)|d;
   }
   if(!nonce)return false;nonce_seen=true;continue;
  }
  return false;
 }
 return seen==((1u<<(sizeof(words)/sizeof(words[0])))-1) && nonce_seen;
}
static bool gp_valid(void *context)
{
 struct gp_context *c=context;const char *args=PE_boot_args();
 return c==&gp && c->bytes && args && !memcmp(args,c->args,c->bytes) &&
  __builtin_arm_rsr64("CurrentEL")==4 && !(__builtin_arm_rsr64("MPIDR_EL1")&0xff00ffffffULL) &&
  redfin_spmi_return_ready()==1;
}
static uint32_t gp_read(void *context,unsigned unit,unsigned at)
{
 struct gp_context *c=context;
 uint32_t v=*(volatile const uint32_t *)(c->base[unit]+at);
 __asm__ volatile("dmb oshld" ::: "memory");return v;
}
static void gp_write(void *context,unsigned unit,unsigned at,uint32_t v)
{
 struct gp_context *c=context;
 __asm__ volatile("dmb oshst" ::: "memory");
 *(volatile uint32_t *)(c->base[unit]+at)=v;
 __asm__ volatile("dsb osh" ::: "memory");
}
static void gp_delay(void *context,unsigned us) {(void)context;delay(us);}
static bool gp_table(void *context)
{
 struct gp_context *c=context;struct rf_cmddb_resource resource;
 const uint8_t key[8]="cx.lvl";
 return gp_valid(c) && rf_cmddb_lookup((volatile const uint8_t *)c->db,RF_CMDDB_BYTES,key,RF_CMDDB_ARC,&resource)==RF_CMDDB_OK &&
  rf_gp_table(&resource);
}
static bool gp_prop(const char *path,const char *key,const void *expected,unsigned n)
{
 DTEntry node;const void *raw=NULL;unsigned bytes=0;
 return SecureDTLookupEntry(NULL,path,&node)==kSuccess && SecureDTGetProperty(node,key,&raw,&bytes)==kSuccess &&
  raw && bytes==n && !memcmp(raw,expected,n);
}
int redfin_gpu_power_probe(void)
{
 if(__atomic_exchange_n(&gp_attempted,true,__ATOMIC_ACQ_REL))return EBUSY;
 const char *args=PE_boot_args();unsigned bytes=0;
 if(!args)return EINVAL;
 while(bytes<sizeof(gp.args) && args[bytes])bytes++;
 if(bytes==sizeof(gp.args) || !gp_flags(args,bytes+1))return ENOTSUP;
 memcpy(gp.args,args,bytes+1);gp.bytes=bytes+1;
 const uint64_t memory_base=0x180000000ULL,memory_size=0x80000000ULL;
 const uint64_t ranges[]={0x03d9106c,4,0x03d91540,4,0x18220000,0x10000,0x80860000,0x20000};
 const uint32_t parent[]={0x30000,64,65535,7,416},chip=0x06020001;
 if(!gp_valid(&gp) || !gp_prop("/chosen","dram-base",&memory_base,8) || !gp_prop("/chosen","dram-size",&memory_size,8) ||
    !gp_prop("/redfin-gpu-power","reg",ranges,sizeof(ranges)) || !gp_prop("/redfin-gpu-power","cx-parent",parent,sizeof(parent)) ||
    !gp_prop("/redfin-gpu-power","chip-id",&chip,4))return ENXIO;
 gp.base[RF_GP_GCC]=ml_io_map(0x100000,0x1f0000);
 if(!gp.base[RF_GP_GCC])return ENOMEM;
 uint32_t cfg=gp_read(&gp,RF_GP_GCC,0x71004);
 if((cfg&0x80000001u)!=1)return EAGAIN;
 gp.base[RF_GP_GPUCC]=ml_io_map(0x3d90000,0x9000);
 gp.base[RF_GP_RSC]=ml_io_map(0x18220000,0x10000);
 gp.base[RF_GP_GIC]=ml_io_map(0x17a00000,0x4000);
 gp.db=ml_io_map_wcomb(0x80860000,RF_CMDDB_BYTES);
 if(!gp.base[RF_GP_GPUCC] || !gp.base[RF_GP_RSC] || !gp.base[RF_GP_GIC] || !gp.db)return ENOMEM;
 const struct rf_gp_ops ops={&gp,gp_valid,gp_read,gp_write,gp_delay,gp_table};
 int result=rf_gp_run(&ops,&gp_report);
 printf("REDFIN GPU POWER: result=%d stage=%u ARC-selector=%u corner=%u held=%u writes=%u polls=%u IRQ=%#x CMD=%#x CX=%#x/%#x HW=%#x on=%u; GX/GMU/SMMU/DMA untouched\n",
  result,gp_report.stage,gp_report.selector,gp_report.corner,gp_report.parent_held,gp_report.write_issued,
  gp_report.polls,gp_report.irq,gp_report.status,gp_report.cx_before,gp_report.cx_after,gp_report.cx_hw,gp_report.cx_on);
 return result?EIO:0;
}
#endif
