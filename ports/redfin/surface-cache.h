/* SPDX-License-Identifier: MIT */
/* Include after SweetSurface and IOBufferMemoryDescriptor declarations.
 * Only the allocator may publish redfinWriteCombined, before the surface
 * becomes visible. All kernel, IOSurface and GPU-client CPU mappings of
 * those exact owned pages use the same actual Write Combine attribute.
 * Wrapped and physical scanout memory keep the original cache protocol.
 * A parent ID alone is metadata: only a fresh allocation can receive this
 * attribute. No existing parent descriptor or image view can inherit it.
 */
#ifndef REDFIN_SURFACE_CACHE_H
#define REDFIN_SURFACE_CACHE_H
#include <stdint.h>

#define RF_GS_ABI 1u
#define RF_GS_POLICY 2u
#define RF_GS_PAGE_BYTES UINT64_C(16384)
#define RF_GS_MAX_BYTES (UINT64_C(128) * 1024 * 1024)

static inline bool redfin_surface_wc_hint(uint32_t hint)
{
    /* Actual20H392 CoreAnimation display buffers request0x700. Redfin uses
     * its proven normal non-cacheable WC mapping for Apple's realtime mode;
     * every CPU alias and actual GPU/CPU handoff still follows this policy. */
    return !hint || hint == kIOMapWriteCombineCache || hint == kIOMapRealTimeCache;
}

/* Cache attributes describe allocated pages, independently of GMEM image
 * padding. Explicit WC/realtime requests use the IOSurface/IOKit shifted
 * values. Other explicit requests keep the existing cached path. */
static inline bool redfin_surface_wc_allocation(const SweetSurface *surface, bool selected)
{
    return selected && surface && !surface->memory && !surface->wrapped &&
        !surface->wrapDelta && !surface->scanoutPhys && surface->scanoutSlot < 0 &&
        surface->allocSize && surface->allocSize <= RF_GS_MAX_BYTES &&
        !(surface->allocSize & (RF_GS_PAGE_BYTES - 1)) &&
        surface->width && surface->height && !surface->planeCount &&
        surface->pixelFormat == UINT32_C(0x42475241) &&
        surface->bytesPerElement == 4 && surface->elementWidth == 1 &&
        surface->elementHeight == 1 && redfin_surface_wc_hint(surface->cacheMode);
}

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
        surface->mapCache == kIOMapWriteCombineCache && redfin_surface_wc_hint(surface->cacheMode) &&
        !surface->wrapped && !surface->wrapDelta &&
        !surface->scanoutPhys && surface->scanoutSlot < 0;
}
#endif
