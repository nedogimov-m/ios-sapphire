/* SPDX-License-Identifier: MIT */
/* Mesa25.0.7 fd6_layout.c reserves a16x4 transfer footprint for linear
 * images. Only newly allocated, single-plane kernel-owned BGRA images may
 * reserve that extra storage. An actual kernel query attests the extent;
 * wrapped memory and image subviews never acquire permission from BO slack. */
#ifndef REDFIN_SURFACE_PADDING_H
#define REDFIN_SURFACE_PADDING_H
#include <stdint.h>
#include <stdbool.h>

#define RF_GP_INFO_RENDER_EXTENT UINT32_C(0x52465031)
#define RF_GP_ABI 1u
#define RF_GP_PAGE_BYTES UINT64_C(16384)
#define RF_GP_MAX_BYTES (UINT64_C(128) * 1024 * 1024)
#define RF_GP_BGRA UINT32_C(0x42475241)

struct rf_gp_image {
    uint32_t width, height, pitch, offset, format, planes;
    uint32_t bytes_per_element, element_width, element_height;
};
struct rf_gp_plan {uint64_t allocation, extent;};
struct rf_gp_import {struct rf_gp_image image; uint64_t extent;};
struct rf_gp_view {
    uint32_t width, height, pitch, offset, cpp, levels, layers, samples;
};

/* Pure geometry only: the allocator/query must independently prove actual
 * IOBuffer ownership, no parent/wrap/physical scanout and the full descriptor.
 * Failure leaves the output and original allocation unchanged. */
static inline bool rf_gp_storage_plan(const struct rf_gp_image *s,
    uint64_t allocation, struct rf_gp_plan *out)
{
    if (!s || !out || !allocation || allocation > RF_GP_MAX_BYTES ||
        (allocation & (RF_GP_PAGE_BYTES - 1)) || !s->width || !s->height ||
        s->width > 16384 || s->height > 16384 || s->offset || s->planes ||
        s->format != RF_GP_BGRA || s->bytes_per_element != 4 ||
        s->element_width != 1 || s->element_height != 1 ||
        !s->pitch || (s->pitch & 63u) || s->pitch < (uint64_t)s->width * 4)
        return false;
    uint64_t visible = (uint64_t)s->pitch * s->height;
    uint64_t extent = (uint64_t)s->pitch * (((uint64_t)s->height + 3) & ~UINT64_C(3));
    if (visible > allocation || extent > RF_GP_MAX_BYTES) return false;
    uint64_t needed = (extent + RF_GP_PAGE_BYTES - 1) & ~(RF_GP_PAGE_BYTES - 1);
    struct rf_gp_plan value = {allocation > needed ? allocation : needed, extent};
    *out = value;
    return true;
}

/* The permission covers exactly the declared full image. It cannot migrate
 * to a smaller texture, byte-offset/buffer alias, mip, array or MSAA image.
 * The unchanged native GMEM bounds check still sees the checked extent. */
static inline uint64_t rf_gp_full_image_extent(const struct rf_gp_import *owner,
    const struct rf_gp_view *view, uint64_t allocation)
{
    if (!owner || !view || !owner->extent ||
        view->width != owner->image.width || view->height != owner->image.height ||
        view->pitch != owner->image.pitch || view->offset != owner->image.offset ||
        view->cpp != 4 || view->levels != 1 || view->layers != 1 || view->samples > 1)
        return 0;
    struct rf_gp_plan plan = {0, 0};
    if (!rf_gp_storage_plan(&owner->image, allocation, &plan) ||
        plan.allocation != allocation || plan.extent != owner->extent)
        return 0;
    return plan.extent;
}
#endif
