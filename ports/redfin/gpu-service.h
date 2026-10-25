/* SPDX-License-Identifier: MIT */
/* Private kernel boundary. Startup is CPU0; runtime callers hold the GPU
 * mutex and its current-thread lease on a proved coherent GUI processor. */
#ifndef REDFIN_GPU_SERVICE_H
#define REDFIN_GPU_SERVICE_H
#include <stdbool.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
bool redfin_gpu_ready(void);
bool redfin_gpu_runtime_caller(void);
void *redfin_gpu_bind(void);
void redfin_gpu_unbind(void *previous);
int redfin_gpu_audit(void);
uint64_t redfin_gpu_address(uint64_t size);
int redfin_gpu_map(uint64_t address,uint64_t physical,bool read_only);
int redfin_gpu_map_display(uint64_t address,uint64_t physical);
int redfin_gpu_mapped(void);
int redfin_gpu_release(uint64_t address,uint64_t size);
int redfin_gpu_submit(const uint64_t *addresses,const uint32_t *words,unsigned count,uint32_t *fence);
bool redfin_gpu_done(uint32_t fence);
uint32_t redfin_gpu_last(void);
void redfin_gpu_sync(void *address,uint64_t size,bool invalidate);
void redfin_gpu_invalidate(void *address,uint64_t size);
void redfin_gpu_poison(const char *reason);
void redfin_gpu_stop(void);
void redfin_gpu_gui_start(void);
void RedfinGPUStart(void);
void RedfinGPUStop(void);
#ifdef __cplusplus
}
#endif
#endif
