/* SPDX-License-Identifier: MIT
 * Only internal Metal drains use this budget. The native kernel owns the one
 * immutable cold-output deadline and the separate ordinary two-second limit;
 * real short/nonblocking client requests still reach it unchanged.
 */
#include <errno.h>
#include "util/os_time.h"
#if defined(__APPLE__) && defined(GALLIUM_FREEDRENO)
#include <IOKit/IOKitLib.h>
#include <CoreFoundation/CoreFoundation.h>
#endif

#define RF_METAL_COLD_OUTPUT_NS UINT64_C(10000000000)

struct redfin_metal_wait_result {
   uint64_t budget_ns,elapsed_ns;
   int error;
   bool attempted;
};

static void rwa_redfin_native_wait_init(struct rwa_device *device)
{
   device->native_cold_wait=false;
#if defined(__APPLE__) && defined(GALLIUM_FREEDRENO)
   if(device->software || strcmp(device->screen->get_name(device->screen),"FD620"))return;
   io_service_t service=IOServiceGetMatchingService(0,IOServiceMatching("RedwoodGPU"));
   if(!service)return;
   CFTypeRef value=IORegistryEntryCreateCFProperty(service,CFSTR("RedfinColdOutputWaitABI"),NULL,0);
   int32_t version=0;
   if(value && CFGetTypeID(value)==CFNumberGetTypeID() &&
      CFNumberGetValue(value,kCFNumberSInt32Type,&version) && version==1)
      device->native_cold_wait=true;
   if(value)CFRelease(value);
   IOObjectRelease(service);
#endif
}

static uint64_t rwa_redfin_internal_wait_budget(const struct rwa_device *device)
{
   return !device->software && device->native_cold_wait ?
      RF_METAL_COLD_OUTPUT_NS+RWA_FENCE_TIMEOUT_NS : RWA_FENCE_TIMEOUT_NS;
}

static bool rwa_redfin_fence_wait(struct rwa_device *device,struct pipe_fence_handle *fence,
   const char *path,struct redfin_metal_wait_result *result)
{
   result->budget_ns=rwa_redfin_internal_wait_budget(device);
   result->attempted=true;
   int previous_errno=errno;
   uint64_t began=(uint64_t)os_time_get_nano();
   errno=0;
   bool done=device->screen->fence_finish(device->screen,NULL,fence,result->budget_ns);
   result->error=errno; /* Capture the original result before clocks/logging. */
   uint64_t ended=(uint64_t)os_time_get_nano();
   result->elapsed_ns=ended>=began ? ended-began : 0;
   /* A false Gallium result without errno is unknown, never invented ETIMEDOUT.
    * Bound observations process-wide, including across fresh native devices;
    * reserve the first failure independently of the slow-success allowance. */
   static unsigned slow_reports,failed_report;
   bool report=done ? result->elapsed_ns>=UINT64_C(50000000) &&
      __atomic_fetch_add(&slow_reports,1,__ATOMIC_RELAXED)<8 :
      !__atomic_exchange_n(&failed_report,1,__ATOMIC_RELAXED);
   if(report)
      fprintf(stderr,"REDFIN METAL WAIT: path=%s cold-abi=%u budget-ns=%llu elapsed-ns=%llu done=%u errno=%d original=1\n",
         path,(unsigned)(!device->software && device->native_cold_wait),
         (unsigned long long)result->budget_ns,(unsigned long long)result->elapsed_ns,
         (unsigned)done,result->error);
   errno=done ? previous_errno : result->error;
   return done;
}
