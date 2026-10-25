/* SPDX-License-Identifier: MIT */
/*
 * Native A620 2D presentation, adapted from Mesa25.0.7 fd6_blitter.cc,
 * fd6_barrier.cc and the a6xx register descriptions.
 * Copyright (C) 2017 Rob Clark; 2018,2023 Google, Inc.
 *
 * The panel's 4320-byte pitch cannot be represented by A6xx's 64-byte
 * pitch fields. Scale into 4352-byte rows, then copy even and odd rows
 * separately with doubled pitches. The odd destination starts 32 bytes
 * before its first row, with x=8. No CPU pixel packing or DPU register
 * change is required.
 */
#ifndef REDFIN_GPU_DISPLAY_H
#define REDFIN_GPU_DISPLAY_H
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#ifndef REDFIN_GPU_RUNTIME_H
#error "Include the native GPU runtime protocol before the display protocol"
#endif

#define RF_GD_PANEL_PHYSICAL UINT64_C(0xa0000000)
#define RF_GD_PANEL_PITCH 4320u
#define RF_GD_PANEL_W 1080u
#define RF_GD_PANEL_H 2340u
#define RF_GD_PANEL_BYTES ((uint64_t)RF_GD_PANEL_PITCH * RF_GD_PANEL_H)
#define RF_GD_PANEL_MAPPED ((RF_GD_PANEL_BYTES + RF_GR_HOST_PAGE - 1) & ~(uint64_t)(RF_GR_HOST_PAGE - 1))
#define RF_GD_STAGE_PITCH 4352u
#define RF_GD_STAGE_IMAGE ((uint64_t)RF_GD_STAGE_PITCH * RF_GD_PANEL_H)
#define RF_GD_CONTROL ((RF_GD_STAGE_IMAGE + RF_GR_HOST_PAGE - 1) & ~(uint64_t)(RF_GR_HOST_PAGE - 1))
#define RF_GD_STAGE_BYTES (RF_GD_CONTROL + RF_GR_HOST_PAGE)
#define RF_GD_WORDS 2048u
#define RF_GD_LAYERS 4u

struct rf_gd_surface {
    uint64_t address, length;
    uint32_t offset, width, height, pitch;
};
struct rf_gd_rect {uint32_t x, y, w, h;};
struct rf_gd_layer {
    struct rf_gd_surface surface;
    struct rf_gd_rect source, destination;
};
struct rf_gd_stream {
    uint32_t *words;
    unsigned used, room;
    bool failed;
    uint64_t control;
};

/* Reserved splash memory is accessible only through the internal display
 * mapping entry point. The ordinary userspace mapper stays RAM-only. */
static inline bool rf_gd_panel_page(uint64_t physical)
{
    return !(physical & 4095u) && physical >= RF_GD_PANEL_PHYSICAL &&
        physical - RF_GD_PANEL_PHYSICAL <= RF_GD_PANEL_MAPPED - 4096;
}
static inline bool rf_gd_surface_valid(const struct rf_gd_surface *s)
{
    if (!s || !s->address || (s->address & 63u) || !s->length ||
        s->length > RF_GR_BUFFER_MAX || (s->offset & 63u) ||
        s->offset >= s->length || !s->width || !s->height ||
        s->width > 16384 || s->height > 16384 || (s->pitch & 63u) ||
        s->pitch < (uint64_t)s->width * 4 || s->pitch > (0x7fffu << 6) ||
        s->address > UINT64_MAX - s->length) return false;
    uint64_t extent = (uint64_t)(s->height - 1) * s->pitch + (uint64_t)s->width * 4;
    return extent <= s->length - s->offset;
}
static inline bool rf_gd_rect_valid(const struct rf_gd_surface *s, const struct rf_gd_rect *r)
{
    return rf_gd_surface_valid(s) && r && r->w && r->h && r->x < s->width &&
        r->y < s->height && r->w <= s->width - r->x && r->h <= s->height - r->y;
}
static inline void rf_gd_word(struct rf_gd_stream *s, uint32_t word)
{
    if (s->used >= s->room) {s->failed = true; return;}
    s->words[s->used++] = word;
}
static inline uint32_t rf_gd_type4(unsigned at, unsigned count)
{
    return 0x40000000u | (at << 8) | (rf_gr_parity(at) << 27) |
        count | (rf_gr_parity(count) << 7);
}
static inline void rf_gd_reg(struct rf_gd_stream *s, unsigned at, uint32_t value)
{rf_gd_word(s, rf_gd_type4(at, 1)); rf_gd_word(s, value);}
static inline void rf_gd_packet(struct rf_gd_stream *s, unsigned op, uint32_t value)
{rf_gd_word(s, rf_gr_type7(op, 1)); rf_gd_word(s, value);}
static inline void rf_gd_idle(struct rf_gd_stream *s)
{rf_gd_word(s, rf_gr_type7(0x26, 0));}
static inline void rf_gd_event(struct rf_gd_stream *s, unsigned event, bool timestamp)
{
    rf_gd_word(s, rf_gr_type7(0x46, timestamp ? 4 : 1));
    rf_gd_word(s, event | (timestamp ? 1u << 30 : 0));
    if (timestamp) {
        rf_gd_word(s, (uint32_t)s->control);
        rf_gd_word(s, (uint32_t)(s->control >> 32));
        rf_gd_word(s, 1);
    }
}
static inline void rf_gd_publish_color(struct rf_gd_stream *s)
{
    rf_gd_event(s, 29, true); /* CCU clean color, with its actual RAM marker. */
    rf_gd_idle(s);
    rf_gd_event(s, 49, false); /* Invalidate UCHE before reading the new image. */
    rf_gd_idle(s);
}
static inline void rf_gd_dst(struct rf_gd_stream *s, const struct rf_gd_surface *dst)
{
    uint64_t at = dst->address + dst->offset;
    rf_gd_word(s, rf_gd_type4(0x8c17, 4));
    rf_gd_word(s, 0x30u | (1u << 10)); /* linear BGRA8 / WXYZ */
    rf_gd_word(s, (uint32_t)at); rf_gd_word(s, (uint32_t)(at >> 32));
    rf_gd_word(s, dst->pitch >> 6);
}
static inline void rf_gd_blit(struct rf_gd_stream *s,
    const struct rf_gd_surface *src, const struct rf_gd_rect *from,
    const struct rf_gd_surface *dst, const struct rf_gd_rect *to,
    bool linear, bool clear)
{
    uint32_t ctl = (0xfu << 20) | (0x30u << 8) | (0x10u << 24) | (clear ? 1u << 7 : 0);
    rf_gd_reg(s, 0x8c00, ctl); rf_gd_reg(s, 0x8400, ctl);
    rf_gd_reg(s, 0xacc0, (0x30u << 3) | (0xfu << 12));
    rf_gd_reg(s, 0x8c01, 0);
    rf_gd_word(s, rf_gd_type4(0x8401, 6));
    rf_gd_word(s, clear ? 0 : from->x << 8);
    rf_gd_word(s, clear ? 0 : (from->x + from->w - 1) << 8);
    rf_gd_word(s, clear ? 0 : from->y << 8);
    rf_gd_word(s, clear ? 0 : (from->y + from->h - 1) << 8);
    rf_gd_word(s, to->x | (to->y << 16));
    rf_gd_word(s, (to->x + to->w - 1) | ((to->y + to->h - 1) << 16));
    rf_gd_word(s, rf_gd_type4(0xb4c0, 5));
    if (clear) {
        for (unsigned i = 0; i < 5; ++i) rf_gd_word(s, 0);
        rf_gd_word(s, rf_gd_type4(0x8c2c, 4));
        rf_gd_word(s, 0); rf_gd_word(s, 0); rf_gd_word(s, 0); rf_gd_word(s, 255);
    } else {
        uint64_t at = src->address + src->offset;
        rf_gd_word(s, 0x30u | (1u << 10) | (1u << 20) | (1u << 22) | (linear ? 1u << 16 : 0));
        rf_gd_word(s, src->width | (src->height << 15));
        rf_gd_word(s, (uint32_t)at); rf_gd_word(s, (uint32_t)(at >> 32));
        rf_gd_word(s, (src->pitch >> 6) << 9);
    }
    rf_gd_dst(s, dst);
    rf_gd_event(s, 63, false); rf_gd_idle(s);
    rf_gd_reg(s, 0x8e04, 0x04100000u); /* A620's actual blit ECO value. */
    rf_gd_packet(s, 0x2c, 3); rf_gd_idle(s);
    rf_gd_reg(s, 0x8e04, 0);
}

/* All geometry and complete BO extents are checked before the first word.
 * Caller must retain/map these exact descriptors and use the native queue's
 * completion/fault checks. An emitted command stream is never a completion. */
static inline unsigned rf_gd_program(uint32_t *words, unsigned room,
    const struct rf_gd_surface *stage, uint64_t packed, uint64_t packed_length,
    const struct rf_gd_layer *layers, unsigned count)
{
    if (!words || room < RF_GD_WORDS || !rf_gd_surface_valid(stage) ||
        stage->width != RF_GD_PANEL_W || stage->height != RF_GD_PANEL_H ||
        stage->pitch != RF_GD_STAGE_PITCH || stage->offset ||
        stage->length < RF_GD_STAGE_BYTES || !packed || (packed & 63u) ||
        packed_length < RF_GD_PANEL_MAPPED || packed_length > RF_GR_BUFFER_MAX ||
        packed > UINT64_MAX - packed_length ||
        (packed < stage->address + stage->length && stage->address < packed + packed_length) ||
        !layers || !count || count > RF_GD_LAYERS) return 0;
    for (unsigned i = 0; i < count; ++i)
        if (!rf_gd_rect_valid(&layers[i].surface, &layers[i].source) ||
            !rf_gd_rect_valid(stage, &layers[i].destination) ||
            (layers[i].surface.address < stage->address + stage->length &&
             stage->address < layers[i].surface.address + layers[i].surface.length) ||
            (layers[i].surface.address < packed + packed_length &&
             packed < layers[i].surface.address + layers[i].surface.length)) return 0;
    struct rf_gd_surface even_src = {stage->address, stage->length, 0,
        RF_GD_PANEL_W, RF_GD_PANEL_H / 2, 2 * RF_GD_STAGE_PITCH};
    struct rf_gd_surface odd_src = {stage->address + RF_GD_STAGE_PITCH,
        stage->length - RF_GD_STAGE_PITCH, 0, RF_GD_PANEL_W, RF_GD_PANEL_H / 2, 2 * RF_GD_STAGE_PITCH};
    struct rf_gd_surface even_dst = {packed, packed_length, 0,
        RF_GD_PANEL_W, RF_GD_PANEL_H / 2, 2 * RF_GD_PANEL_PITCH};
    struct rf_gd_surface odd_dst = {packed + RF_GD_PANEL_PITCH - 32,
        packed_length - (RF_GD_PANEL_PITCH - 32), 0, RF_GD_PANEL_W + 8,
        RF_GD_PANEL_H / 2, 2 * RF_GD_PANEL_PITCH};
    struct rf_gd_rect full = {0, 0, RF_GD_PANEL_W, RF_GD_PANEL_H};
    struct rf_gd_rect half = {0, 0, RF_GD_PANEL_W, RF_GD_PANEL_H / 2};
    struct rf_gd_rect odd = {8, 0, RF_GD_PANEL_W, RF_GD_PANEL_H / 2};
    if (!rf_gd_rect_valid(&even_src, &half) || !rf_gd_rect_valid(&odd_src, &half) ||
        !rf_gd_rect_valid(&even_dst, &half) || !rf_gd_rect_valid(&odd_dst, &odd)) return 0;
    struct rf_gd_stream s = {words, 0, room, false, stage->address + RF_GD_CONTROL};
    rf_gd_event(&s, 29, true); rf_gd_event(&s, 28, true);
    rf_gd_idle(&s); rf_gd_event(&s, 25, false); rf_gd_event(&s, 24, false);
    rf_gd_event(&s, 49, false); rf_gd_idle(&s);
    /* A620 has one CCU, 8KiB depth and color caches, no GMEM fast clear.
     * Same sysmem CCU configuration as the installed Mesa/A620 driver. */
    rf_gd_reg(&s, 0x8e07, 0x01000001u);
    rf_gd_packet(&s, 0x65, 0xcu);
    rf_gd_blit(&s, NULL, NULL, stage, &full, false, true);
    for (unsigned i = 0; i < count; ++i)
        rf_gd_blit(&s, &layers[i].surface, &layers[i].source, stage, &layers[i].destination, true, false);
    rf_gd_publish_color(&s);
    rf_gd_blit(&s, &even_src, &half, &even_dst, &half, false, false);
    rf_gd_blit(&s, &odd_src, &half, &odd_dst, &odd, false, false);
    rf_gd_publish_color(&s);
    rf_gd_packet(&s, 0x65, 1); /* Return the marker to direct rendering. */
    rf_gd_reg(&s, 0x8e04, 0x04100000u);
    return s.failed ? 0 : s.used;
}
#endif
