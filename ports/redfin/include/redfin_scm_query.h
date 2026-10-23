/* SPDX-License-Identifier: MIT */
/* Read-only Qualcomm SCM queries. Native protocol reference: Google msm
 * 500b3a2059c1eec0fec08ec56add06320ea901a8, drivers/soc/qcom/scm.c:
 * is_scm_armv8(), __scm_call_armv8_64(), scm_is_call_available().
 * No metadata pointer, PAS init/auth/reset/shutdown or memory assignment. */
#ifndef REDFIN_SCM_QUERY_H
#define REDFIN_SCM_QUERY_H
#include <stdbool.h>
#include <stdint.h>
#include <sys/errno.h>

enum { RF_SQ_DETECT=1, RF_SQ_AVAILABLE, RF_SQ_PAS_SUPPORTED };
struct rf_sq_regs { uint64_t x[8]; };
struct rf_sq_ops {
 void *context;
 bool (*valid)(void *);
 int (*invoke)(void *,struct rf_sq_regs *);
 void (*delay_us)(void *,unsigned);
 uint64_t (*time_ns)(void *);
};
struct rf_sq_report {
 uint32_t convention,kind,argument,calls,resumes,busy_retries;
 uint64_t function,value[3],elapsed_ns;
 int64_t status;
 bool completed;
};
static inline bool rf_sq_target(uint32_t function)
{
 return function==0x02000201 || function==0x02000202 ||
  function==0x02000205 || function==0x02000206 || function==0x02000207;
}
static inline bool rf_sq_request(unsigned convention,unsigned kind,uint32_t argument,
 struct rf_sq_regs *registers)
{
 if(!registers || (convention!=32 && convention!=64))return false;
 const uint32_t width=convention==64?0x40000000u:0;
 *registers=(struct rf_sq_regs){{0}};
 if(kind==RF_SQ_DETECT && !argument) {
  registers->x[0]=0x82000601u|width;
  registers->x[2]=0x82000601u; /* Native legacy-SCM convention detection. */
 } else if(kind==RF_SQ_AVAILABLE && rf_sq_target(argument)) {
  registers->x[0]=0x02000601u|width;registers->x[2]=argument;
 } else if(kind==RF_SQ_PAS_SUPPORTED && (argument==4 || argument==13)) {
  registers->x[0]=0x02000207u|width;registers->x[2]=argument;
 } else return false;
 registers->x[1]=1;
 return true;
}
static inline int rf_sq_run(const struct rf_sq_ops *ops,unsigned convention,
 unsigned kind,uint32_t argument,struct rf_sq_report *report)
{
 struct rf_sq_regs request,live;
 if(!ops || !report || !ops->valid || !ops->invoke || !ops->delay_us || !ops->time_ns ||
    !rf_sq_request(convention,kind,argument,&request))return EINVAL;
 *report=(struct rf_sq_report){0};
 report->convention=convention;report->kind=kind;report->argument=argument;
 report->function=request.x[0];
 if(!ops->valid(ops->context))return ECANCELED;
 uint64_t start=ops->time_ns(ops->context);
 live=request;
 for(;;) {
  if(!ops->valid(ops->context))return ECANCELED;
  uint64_t now=ops->time_ns(ops->context);
  if(now<start || now-start>200000000ULL)return ETIMEDOUT;
  report->elapsed_ns=now-start;
  /* Only the exact initial query or its interrupted continuation can enter. */
  if(live.x[0]!=request.x[0] && live.x[0]!=1)return EINVAL;
  live.x[7]=0;
  int error=ops->invoke(ops->context,&live);
  report->calls++;
  if(error)return error;
  if(!ops->valid(ops->context))return ECANCELED;
  now=ops->time_ns(ops->context);
  if(now<start || now-start>200000000ULL)return ETIMEDOUT;
  report->elapsed_ns=now-start;
  report->status=convention==32?(int64_t)(int32_t)(uint32_t)live.x[0]:(int64_t)live.x[0];
  for(unsigned i=0;i<3;i++)report->value[i]=convention==32?(uint32_t)live.x[i+1]:live.x[i+1];
  if(report->status==1) {
   if(++report->resumes>16)return ETIMEDOUT;
   continue; /* Preserve returned x1..x6 including the native resume cookie. */
  }
  if(report->status==-12) {
   if(report->busy_retries>=3)return EBUSY;
   report->busy_retries++;
   if(!ops->valid(ops->context))return ECANCELED;
   ops->delay_us(ops->context,30000);
   live=request;
   continue;
  }
  report->completed=true;
  return report->status?EIO:0;
 }
}
#endif /* REDFIN_SCM_QUERY_H */
