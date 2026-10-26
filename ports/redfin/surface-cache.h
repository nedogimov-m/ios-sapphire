/* SPDX-License-Identifier: MIT */
/* Include after SweetSurface and IOBufferMemoryDescriptor declarations.
 * Only the allocator may publish redfinWriteCombined, before the surface
 * becomes visible. All kernel, IOSurface and GPU-client CPU mappings of
 * those exact owned pages use the same actual Write Combine attribute.
 * Wrapped, parent, explicit-cache and physical scanout memory keep their
 * original cache ownership protocol, including unseeded CPU writers.
 */
#ifndef REDFIN_SURFACE_CACHE_H
#define REDFIN_SURFACE_CACHE_H
#include <stdint.h>

#define RF_GS_ABI 1u

static inline void redfin_surface_cache_barrier(void)
{
#if defined(__arm64__) || defined(__aarch64__)
    __asm__ volatile("dsb sy" ::: "memory");
#else
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
#endif
}

static inline bool redfin_surface_write_combined(const SweetSurface *surface,
    IOMemoryDescriptor *memory, uint64_t bytes)
{
    return surface && memory && bytes && surface->redfinWriteCombined &&
        surface->memory == memory && surface->allocSize == bytes &&
        memory->getLength() == bytes &&
        OSDynamicCast(IOBufferMemoryDescriptor, memory) &&
        surface->mapCache == kIOMapWriteCombineCache && !surface->cacheMode &&
        surface->redfinRenderExtent && !surface->wrapped && !surface->wrapDelta &&
        !surface->parentID && !surface->scanoutPhys && surface->scanoutSlot < 0;
}
#endif
