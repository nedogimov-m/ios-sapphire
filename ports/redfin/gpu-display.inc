/* SPDX-License-Identifier: MIT */
/* Internal presentation shares the existing serialized queue, current-thread
 * lease and real native fence checks. No userspace physical import is added. */
#include <arm64/redfin_gui_profile.h>
#include "RedfinDisplayGeometry.h"
#include "RedfinGPUDisplayService.h"
#include "redfin_gpu_display.h"

#define GD_CACHE 8u
struct gd_buffer {
    IOMemoryDescriptor *memory;
    SweetSurface *surface;
    uint8_t *kernel;
    uint64_t address, size, seen;
    bool held;
};
static struct {
    gd_buffer stage, commands, panel, verification, sources[GD_CACHE];
    bool attempted, tested, disabled, uncertain,direct_tested;
    unsigned direct_verified;
    uint64_t frame, calls, elapsed, fallbacks,wc_sources,cached_sources,direct_calls,staged_calls;
} gd;

bool RedfinGPUDisplayWritable(void)
{return !__atomic_load_n(&gd.uncertain, __ATOMIC_ACQUIRE);}

static bool gd_selected(void)
{
    const char *args = PE_boot_args(); unsigned n = 0;
    if (!args) return false;
    while (n < 608 && args[n]) ++n;
    return n < 608 && redfin_gpu_gui_profile(args, n + 1, NULL);
}
static bool gd_drop(gd_buffer *b)
{
    if (!b->memory) return true;
    if (redfin_gpu_release(b->address, b->size)) {
        redfin_gpu_poison("display mapping cannot be released; descriptors retained");
        return false;
    }
    OSSafeReleaseNULL(b->memory); OSSafeReleaseNULL(b->surface); *b = {};
    return true;
}
/* Borrows input references; retains its own before the first page-table
 * change. A failed TLB/unmap leaves those exact objects alive until reset. */
static bool gd_map(gd_buffer *b, IOMemoryDescriptor *memory, uint8_t *kernel,
    SweetSurface *surface, uint64_t size, bool readonly, bool panel)
{
    if (b->memory || !memory || !kernel || !size || size > RF_GR_BUFFER_MAX ||
        (size & PAGE_MASK) || memory->getLength() < size || !redfin_gpu_ready()) return false;
    uint64_t address = redfin_gpu_address(size); if (!address) return false;
    memory->retain(); if (surface) surface->retain();
    b->memory = memory; b->surface = surface; b->kernel = kernel; b->address = address; b->size = size;
    int error = 0;
    for (uint64_t off = 0; off < size; off += 4096) {
        IOByteCount bytes = 0;
        uint64_t physical = memory->getPhysicalSegment(off, &bytes, kIOMemoryMapperNone);
        if (!physical || bytes < 4096 || (panel && physical != RF_GD_PANEL_PHYSICAL + off)) {
            error = EINVAL; break;
        }
        error = panel ? redfin_gpu_map_display(address + off, physical) :
            redfin_gpu_map(address + off, physical, readonly);
        if (error) break;
    }
    if (!error) error = redfin_gpu_mapped();
    if (error) {
        (void)gd_drop(b);
        IOLog("REDFIN GPU DISPLAY MAP: error=%d panel=%u retained=%u\n", error, panel, b->memory != NULL);
        return false;
    }
    return true;
}
static bool gd_allocate(gd_buffer *b, uint64_t size, bool readonly)
{
    size = (size + PAGE_MASK) & ~(uint64_t)PAGE_MASK;
    IOBufferMemoryDescriptor *memory = IOBufferMemoryDescriptor::inTaskWithOptions(kernel_task,
        kIODirectionInOut | kIOMemoryKernelUserShared | kIOMapWriteCombineCache, size, PAGE_SIZE);
    if (!memory) return false;
    bool ok = gd_map(b, memory, (uint8_t *)memory->getBytesNoCopy(), NULL, size, readonly, false);
    memory->release(); return ok;
}
static uint32_t gd_pattern(uint32_t x, uint32_t y)
{
    if (x < 32 && y < 32) return 0xffe02010u;
    return 0xff000000u | (((5*x + 3*y) & 255u) << 16) |
        (((7*y + x) & 255u) << 8) | (((x >> 2) ^ (y >> 1)) & 255u);
}
static rf_gd_surface gd_stage_surface(void)
{
    return {gd.stage.address, gd.stage.size, 0, RF_GD_PANEL_W, RF_GD_PANEL_H, RF_GD_STAGE_PITCH};
}
struct gd_submit_marks {uint64_t built, published, finished;bool direct;};
static bool gd_submit(const rf_gd_layer *layers, unsigned count,
    uint64_t packed, uint64_t packed_length, bool panel, uint32_t *fence,
    gd_submit_marks *marks = NULL,int route=-1)
{
    rf_gd_surface stage = gd_stage_surface();
    uint32_t *commands = (uint32_t *)gd.commands.kernel;
    bool direct=route>0 || (route<0 && gd.direct_tested && rf_gd_direct_eligible(layers,count));
    unsigned words = direct ? rf_gd_program_direct(commands,RF_GD_WORDS,&stage,packed,packed_length,layers,count) :
        rf_gd_program(commands, RF_GD_WORDS, &stage, packed, packed_length, layers, count);
    if (!words) return false; /* No doorbell or target write occurred. */
    if (marks) {marks->built = gpuNow();marks->direct=direct;}
    redfin_gpu_sync(commands, words * sizeof(uint32_t), false);
    if (marks) marks->published = gpuNow();
    const uint64_t address = gd.commands.address;
    int error = redfin_gpu_submit(&address, &words, 1, fence);
    if (error || !redfin_gpu_done(*fence)) {
        if (panel) __atomic_store_n(&gd.uncertain, true, __ATOMIC_RELEASE);
        IOLog("REDFIN GPU DISPLAY STOP: submit=%d fence=%u panel=%u; DMA objects retained\n", error, *fence, panel);
        return false;
    }
    if (marks) marks->finished = gpuNow();
    if(panel) {
        if(direct)++gd.direct_calls;else ++gd.staged_calls;
        uint64_t n=gd.direct_calls+gd.staged_calls;
        if(n<=4 || !(n%120))
            IOLog("REDFIN GPU DIRECT PRESENT: n=%llu direct=%llu staged=%llu ABI=%u full-image-only=1 CPU-pixel-copy=0\n",
                n,gd.direct_calls,gd.staged_calls,RF_GD_DIRECT_ABI);
    }
    return true;
}
/* Both clear-free fullscreen and exact margin clears use real A620 output
 * before the physical panel is mapped. Poisoning stage/output first excludes
 * a pass based on old pixels; fenced full-frame readback checks all packed
 * rows, the scaled second layer, channel values and prefix/tail guards. */
static bool gd_check_case(const gd_buffer *input, gd_buffer *output, bool full)
{
    memset(gd.stage.kernel, 0x3c, gd.stage.size);
    memset(output->kernel, 0x5a, output->size);
    redfin_gpu_sync(gd.stage.kernel, gd.stage.size, true);
    redfin_gpu_sync(output->kernel, output->size, true);
    rf_gd_surface source = {input->address, input->size, 0, RF_GD_PANEL_W, RF_GD_PANEL_H, RF_GD_STAGE_PITCH};
    rf_gd_rect first = full ? rf_gd_rect{0,0,RF_GD_PANEL_W,RF_GD_PANEL_H} : rf_gd_rect{5,6,1070,2328};
    rf_gd_layer layers[2] = {
        {source, first, first},
        {source, {0,0,16,16}, {64,160,128,128}}
    };
    uint32_t fence = 0;
    bool ok = gd_submit(layers, 2, output->address + 64, RF_GD_PANEL_MAPPED, false, &fence);
    uint64_t mismatch = 0, guards = 0;
    if (ok) {
        redfin_gpu_invalidate(output->kernel, output->size);
        for (uint32_t y = 0; y < RF_GD_PANEL_H; ++y) {
            const uint32_t *row = (const uint32_t *)(output->kernel + 64 + (uint64_t)y * RF_GD_PANEL_PITCH);
            for (uint32_t x = 0; x < RF_GD_PANEL_W; ++x) {
                uint32_t expected = !full && (x < 5 || x >= 1075 || y < 6 || y >= 2334) ? 0xff000000u :
                    x >= 64 && x < 192 && y >= 160 && y < 288 ? 0xffe02010u : gd_pattern(x, y);
                if (row[x] != expected) {
                    if (mismatch < 4) IOLog("REDFIN GPU DISPLAY PIXEL: x=%u y=%u actual=%#x expected=%#x\n",
                        x, y, row[x], expected);
                    ++mismatch;
                }
            }
        }
        for (uint64_t i = 0; i < 64; ++i) guards += output->kernel[i] != 0x5a;
        for (uint64_t i = 64 + RF_GD_PANEL_BYTES; i < output->size; ++i) guards += output->kernel[i] != 0x5a;
        ok = !mismatch && !guards;
    }
    IOLog("REDFIN GPU OUTPUT CHECK: full=%u completed=%u fence=%u pixels=%u mismatches=%llu guard-errors=%llu panel-mapped=0\n",
        full, fence != 0 && redfin_gpu_done(fence), fence, RF_GD_PANEL_W * RF_GD_PANEL_H, mismatch, guards);
    return ok;
}
/* Compare the native fused sampling against the actual already-proved GPU
 * scale+pack program. Full input patterns, every output pixel, all tails,
 * input padding and an untouched intermediate image are checked. Only the
 * small control page may change in the intermediate allocation. A mismatch
 * leaves the existing general output route selected for this boot. */
static bool gd_check_direct(void)
{
    static const uint32_t geometry[4][3]={{1080,2340,4352},{1125,2436,4608},
                                      {1125,2435,4608},{80,61,320}};
    gd_buffer input={},reference={},output={};
    bool ok=gd_allocate(&input,UINT64_C(4608)*2436+PAGE_SIZE,true) &&
        gd_allocate(&reference,RF_GD_PANEL_MAPPED+PAGE_SIZE,false) &&
        gd_allocate(&output,RF_GD_PANEL_MAPPED+PAGE_SIZE,false);
    uint64_t pixels=0,mismatches=0,guards=0,stage_writes=0,exact_pixels=0;
    unsigned passed=0,maximum=0;
    for(unsigned c=0;ok && c<4;++c) {
        uint32_t w=geometry[c][0],h=geometry[c][1],pitch=geometry[c][2];
        memset(input.kernel,0xa7,input.size);
        for(unsigned y=0;y<h;++y) {
            uint32_t *row=(uint32_t *)(input.kernel+(uint64_t)y*pitch);
            for(unsigned x=0;x<w;++x)row[x]=gd_pattern(x+3*c,y+5*c);
        }
        memset(reference.kernel,0x5a,reference.size);memset(output.kernel,0x5a,output.size);
        redfin_gpu_sync(input.kernel,input.size,true);
        redfin_gpu_sync(reference.kernel,reference.size,true);redfin_gpu_sync(output.kernel,output.size,true);
        rf_gd_layer layer={{input.address,input.size,0,w,h,pitch},
            {0,0,w,h},{0,0,RF_GD_PANEL_W,RF_GD_PANEL_H}};
        uint32_t ref_fence=0,fence=0;
        ok=gd_submit(&layer,1,reference.address+64,RF_GD_PANEL_MAPPED,false,&ref_fence,NULL,0);
        if(!ok)break;
        memset(gd.stage.kernel,0x3c,RF_GD_CONTROL);redfin_gpu_sync(gd.stage.kernel,RF_GD_CONTROL,true);
        ok=gd_submit(&layer,1,output.address+64,RF_GD_PANEL_MAPPED,false,&fence,NULL,1);
        if(!ok)break;
        redfin_gpu_invalidate(reference.kernel,reference.size);redfin_gpu_invalidate(output.kernel,output.size);
        redfin_gpu_invalidate(input.kernel,input.size);redfin_gpu_invalidate(gd.stage.kernel,RF_GD_CONTROL);
        bool scaled=w!=RF_GD_PANEL_W || h!=RF_GD_PANEL_H;
        unsigned case_maximum=0,over_one=0;uint64_t case_bad=0;
        uint64_t before_guards=guards,before_stage=stage_writes;
        for(unsigned y=0;y<RF_GD_PANEL_H;++y) {
            const uint32_t *gold=(const uint32_t *)(reference.kernel+64+(uint64_t)y*RF_GD_PANEL_PITCH);
            const uint32_t *actual=(const uint32_t *)(output.kernel+64+(uint64_t)y*RF_GD_PANEL_PITCH);
            for(unsigned x=0;x<RF_GD_PANEL_W;++x) {
                unsigned error=0;
                bool match=rf_gd_direct_pixel(actual[x],gold[x],scaled,&error);
                if(error>case_maximum)case_maximum=error;
                if(error>1)++over_one;
                if(!match) {
                    if(mismatches<4)IOLog("REDFIN GPU DIRECT PIXEL: case=%u x=%u y=%u actual=%#x expected=%#x\n",c,x,y,actual[x],gold[x]);
                    ++mismatches;++case_bad;
                }
                ++pixels;
                if(!scaled)++exact_pixels;
            }
        }
        for(uint64_t at=0;at<output.size;++at)
            if(at<64 || at>=64+RF_GD_PANEL_BYTES)guards+=output.kernel[at]!=0x5a || reference.kernel[at]!=0x5a;
        for(unsigned y=0;y<h;++y) {
            const uint32_t *row=(const uint32_t *)(input.kernel+(uint64_t)y*pitch);
            for(unsigned x=0;x<w;++x)guards+=row[x]!=gd_pattern(x+3*c,y+5*c);
            for(unsigned at=w*4;at<pitch;++at)guards+=input.kernel[(uint64_t)y*pitch+at]!=0xa7;
        }
        for(uint64_t at=(uint64_t)h*pitch;at<input.size;++at)guards+=input.kernel[at]!=0xa7;
        for(uint64_t at=0;at<RF_GD_CONTROL;++at)stage_writes+=gd.stage.kernel[at]!=0x3c;
        if(case_maximum>maximum)maximum=case_maximum;
        bool case_pass=!case_bad && guards==before_guards && stage_writes==before_stage;
        IOLog("REDFIN GPU DIRECT CASE: ABI=%u c=%u w=%u h=%u pixels=%u max=%u over1=%u bad=%llu guards=%llu stage=%llu limit=%u done=%u\n",
            RF_GD_DIRECT_ABI,c,w,h,RF_GD_PANEL_W*RF_GD_PANEL_H,case_maximum,over_one,
            case_bad,guards-before_guards,stage_writes-before_stage,
            scaled?RF_GD_DIRECT_COLOR_TOLERANCE:0,case_pass);
        if(case_pass)++passed;
        /* A colour mismatch is a failed admission, not uncertain DMA. Report
         * all four bounded geometries in this same boot. Memory/transport
         * errors still stop immediately; no failed hardware job is retried. */
        ok=!guards && !stage_writes;
    }
    bool complete=ok && !mismatches && passed==4 && pixels==UINT64_C(4)*RF_GD_PANEL_W*RF_GD_PANEL_H;
    IOLog("REDFIN GPU DIRECT CHECK: ABI=%u cases=%u pixels=%llu mismatches=%llu guard-errors=%llu stage-writes=%llu completed=%u tolerance=2 exact-pixels=%llu alpha-exact=1 max-error=%u\n",
        RF_GD_DIRECT_ABI,passed,pixels,mismatches,guards,stage_writes,complete,exact_pixels,maximum);
    /* Retain one bounded private target for the first four real panel
     * readbacks. It is never a source for ordinary presentation. */
    if(complete){gd.verification=reference;reference={};}
    bool dropped_input=gd_drop(&input),dropped_reference=gd_drop(&reference),dropped_output=gd_drop(&output);
    bool dropped=dropped_input && dropped_reference && dropped_output;
    return complete && dropped;
}
static bool gd_check(void)
{
    gd_buffer input = {}, output = {};
    bool allocated = gd_allocate(&input, RF_GD_STAGE_IMAGE, true) &&
        gd_allocate(&output, RF_GD_PANEL_MAPPED + PAGE_SIZE, false);
    if (!allocated) {
        (void)gd_drop(&input); (void)gd_drop(&output); return false;
    }
    for (uint32_t y = 0; y < RF_GD_PANEL_H; ++y) {
        uint32_t *row = (uint32_t *)(input.kernel + (uint64_t)y * RF_GD_STAGE_PITCH);
        for (uint32_t x = 0; x < RF_GD_PANEL_W; ++x) row[x] = gd_pattern(x, y);
    }
    redfin_gpu_sync(input.kernel, input.size, false);
    bool full = gd_check_case(&input, &output, true);
    bool margins = full && gd_check_case(&input, &output, false);
    IOLog("REDFIN GPU DISPLAY CHECK: completed=%u full=%u margins=%u pixels-per-case=%u panel-mapped=0\n",
        full && margins, full, margins, RF_GD_PANEL_W * RF_GD_PANEL_H);
    if(full && margins)gd.direct_tested=gd_check_direct();
    bool dropped_input = gd_drop(&input), dropped_output = gd_drop(&output);
    return full && margins && dropped_input && dropped_output;
}
static bool gd_initialize(SweetSurface *panel)
{
    gd.attempted = true;
    if (!panel || !panel->memory || panel->wrapped || panel->offset ||
        panel->width != RF_GD_PANEL_W || panel->height != RF_GD_PANEL_H ||
        panel->bytesPerRow != RF_GD_PANEL_PITCH || panel->pixelFormat != REDFIN_DISPLAY_BGRA ||
        panel->allocSize != RF_GD_PANEL_MAPPED || panel->memory->getLength() != RF_GD_PANEL_MAPPED ||
        !gd_allocate(&gd.stage, RF_GD_STAGE_BYTES, false) ||
        !gd_allocate(&gd.commands, PAGE_SIZE, true)) return false;
    if (!gd_check()) return false;
    gd.tested = true;
    if (!gd_map(&gd.panel, panel->memory, (uint8_t *)panel->kernelAddress(), panel,
        RF_GD_PANEL_MAPPED, false, true)) return false;
    IOLog("REDFIN GPU DISPLAY START: A620-2D scale=%u packed-pitch=%u GPU-row-pack=2 CPU-pixel-copy=0\n",
        RF_GD_STAGE_PITCH, RF_GD_PANEL_PITCH);
    return true;
}
static gd_buffer *gd_source(SweetSurface *s)
{
    for (unsigned i = 0; i < GD_CACHE; ++i) {
        gd_buffer *b = &gd.sources[i];
        if (b->surface == s && b->memory == s->memory && b->size == s->allocSize) {
            b->seen = gd.frame; return b;
        }
    }
    unsigned slot = GD_CACHE;
    for (unsigned i = 0; i < GD_CACHE; ++i)
        if (!gd.sources[i].memory) {slot = i; break;}
    if (slot == GD_CACHE)
        for (unsigned i = 0; i < GD_CACHE; ++i)
            if (gd.sources[i].seen != gd.frame) {slot = i; break;}
    if (slot == GD_CACHE || !gd_drop(&gd.sources[slot])) return NULL;
    gd_buffer *b = &gd.sources[slot];
    if (!gd_map(b, s->memory, (uint8_t *)s->kernelAddress(), s, s->allocSize, true, false)) return NULL;
    b->seen = gd.frame; return b;
}
static uint32_t gd_u32(const uint8_t *bytes)
{uint32_t value; memcpy(&value, bytes, sizeof(value)); return value;}
static bool gd_layer(SweetSurface *s, const redfin_display_geometry *g,
    const uint8_t *a, const uint8_t *b, rf_gd_layer *out)
{
    if (!s || s->wrapped || !s->memory || !s->kernelAddress() || s->planeCount ||
        s->pixelFormat != REDFIN_DISPLAY_BGRA || s->bytesPerElement != 4 ||
        s->elementWidth != 1 || s->elementHeight != 1 || (s->bytesPerRow & 63u) ||
        (s->offset & 63u) || (s->allocSize & PAGE_MASK) || s->allocSize > RF_GR_BUFFER_MAX) return false;
    int64_t sx = (int32_t)gd_u32(a), sy = (int32_t)gd_u32(a+4);
    int64_t sw = (int32_t)gd_u32(a+8), sh = (int32_t)gd_u32(a+12);
    int64_t dx = (int32_t)gd_u32(b), dy = (int32_t)gd_u32(b+4);
    int64_t dw = (int32_t)gd_u32(b+8), dh = (int32_t)gd_u32(b+12);
    if (sw <= 0 || sh <= 0) {sx = sy = 0; sw = s->width; sh = s->height;}
    if (dw <= 0 || dh <= 0) {dx = dy = 0; dw = g->logical_w; dh = g->logical_h;}
    /* Retain the exact existing clipping behavior through the CPU path for
     * unsupported cropped/negative destinations; never approximate it. */
    if (sx < 0 || sy < 0 || sx + sw > s->width || sy + sh > s->height ||
        dx < 0 || dy < 0 || dx + dw > g->logical_w || dy + dh > g->logical_h) return false;
    uint32_t x0 = g->x + (uint32_t)redfin_display_project(dx, g->w, g->logical_w);
    uint32_t y0 = g->y + (uint32_t)redfin_display_project(dy, g->h, g->logical_h);
    uint32_t x1 = g->x + (uint32_t)redfin_display_project(dx+dw, g->w, g->logical_w);
    uint32_t y1 = g->y + (uint32_t)redfin_display_project(dy+dh, g->h, g->logical_h);
    gd_buffer *buffer = gd_source(s); if (!buffer) return false;
    out->surface = {buffer->address, buffer->size, s->offset, s->width, s->height, s->bytesPerRow};
    out->source = {(uint32_t)sx, (uint32_t)sy, (uint32_t)sw, (uint32_t)sh};
    out->destination = {x0, y0, x1-x0, y1-y0};
    rf_gd_surface stage = gd_stage_surface();
    return rf_gd_rect_valid(&out->surface, &out->source) && rf_gd_rect_valid(&stage, &out->destination);
}
static void gd_hold_uncertain(void)
{
    for (unsigned i = 0; i < GD_CACHE; ++i) {
        gd_buffer *b = &gd.sources[i];
        if (b->surface && b->seen == gd.frame && !b->held) {
            OSAddAtomic64(1, (volatile SInt64 *)((uint8_t *)b->surface->state->getBytesNoCopy() + 0x18));
            b->held = true;
        }
    }
}
static bool gd_panel_readback(uint32_t fence,const rf_gd_layer *layers,unsigned count,bool direct)
{
    if (direct?gd.direct_verified>=4:gd.calls>=4) return true;
    uint32_t reference_fence=0;
    const gd_buffer *reference=&gd.stage;uint32_t pitch=RF_GD_STAGE_PITCH;uint64_t offset=0;
    if(direct) {
        /* The source is still retained by this serialized kernel queue job;
         * no later render can execute between these two completed outputs.
         * Reuse the exact fused coordinates/format in private memory, then
         * compare physical mapping samples bit for bit. The independent
         * full golden tests above already establish filter correctness. */
        if(!gd.verification.memory || !gd_submit(layers,count,gd.verification.address+64,
            RF_GD_PANEL_MAPPED,false,&reference_fence,NULL,1)) {
            __atomic_store_n(&gd.uncertain,true,__ATOMIC_RELEASE);return false;
        }
        reference=&gd.verification;pitch=RF_GD_PANEL_PITCH;offset=64;
    }
    redfin_gpu_invalidate(reference->kernel,reference->size);
    redfin_gpu_invalidate(gd.panel.kernel,gd.panel.size);
    __asm__ volatile("dsb sy" ::: "memory");
    unsigned mismatches = 0;
    for (unsigned y = 0; y < 8; ++y) for (unsigned x = 0; x < 8; ++x) {
        /* Both parities, both margins and the full content extent. */
        uint32_t px = x * (RF_GD_PANEL_W - 1) / 7;
        uint32_t py = y * (RF_GD_PANEL_H - 2) / 7 + (x & 1);
        const volatile uint32_t *from = (const volatile uint32_t *)(reference->kernel + offset +
            (uint64_t)py * pitch + (uint64_t)px * 4);
        const volatile uint32_t *shown = (const volatile uint32_t *)(gd.panel.kernel +
            (uint64_t)py * RF_GD_PANEL_PITCH + (uint64_t)px * 4);
        if (*from != *shown) ++mismatches;
    }
    IOLog("REDFIN GPU DISPLAY PANEL: fence=%u samples=64 mismatches=%u CPU-pixel-copy=0\n", fence, mismatches);
    if(direct) {
        IOLog("REDFIN GPU DIRECT PANEL: n=%u fence=%u reference-fence=%u samples=64 mismatches=%u exact=1 stage-reference=0\n",
            gd.direct_verified+1,fence,reference_fence,mismatches);
        if(!mismatches)++gd.direct_verified;
    }
    return !mismatches;
}
static int gd_present_locked(SweetSurface *panel, const redfin_display_geometry *g, const uint8_t *record)
{
    if (!RedfinGPUDisplayWritable()) return -1;
    if (!gLock || !redfin_gpu_ready() || !gd_selected() || !record ||
        !redfin_display_geometry_valid(g)) return 0;
    if (!RedfinGPUDisplayWritable()) return -1;
    if (!redfin_gpu_ready() || gd.disabled) return 0;
    if (!gd.attempted && !gd_initialize(panel)) {
        gd.disabled = true;
        IOLog("REDFIN GPU DISPLAY: initialization refused; existing CPU path retained\n");
        return 0;
    }
    if (!gd.tested || gd.panel.surface != panel || gd.frame == UINT64_MAX) return 0;
    ++gd.frame;
    uint64_t began = gpuNow();
    uint32_t mask = gd_u32(record+0x104); if (!mask || (mask & ~15u)) return 0;
    rf_gd_layer layers[RF_GD_LAYERS]; unsigned count = 0;
    bool full = false, ok = true;
    for (unsigned i = 0; i < RF_GD_LAYERS; ++i) {
        uint32_t id = gd_u32(record+0x54+4*i);
        if (!(mask & (1u << i)) || !id) continue;
        SweetSurface *s = sweet_surface_copy(id);
        bool layer_ok = s && s != panel && gd_layer(s, g, record+0x64+16*i, record+0xc4+16*i, &layers[count]);
        OSSafeReleaseNULL(s);
        if (!layer_ok) {ok = false; break;}
        const rf_gd_rect *r = &layers[count].destination;
        if (!count) full = r->x == g->x && r->y == g->y && r->w == g->w && r->h == g->h;
        ++count;
    }
    if (!ok || !count || !full) {++gd.fallbacks; return 0;}
    uint64_t prepared = gpuNow();
    /* Surface BOs may also have native CPU writers. Push their actual pages;
     * this is cache maintenance, with no CPU scaling or pixel copy. */
    for (unsigned i = 0; i < GD_CACHE; ++i) {
        gd_buffer *b = &gd.sources[i];
        if (!b->memory || b->seen != gd.frame) continue;
        if (redfin_surface_write_combined(b->surface,b->memory,b->size)) ++gd.wc_sources;
        else {redfin_gpu_sync(b->kernel,b->size,false);++gd.cached_sources;}
    }
    redfin_surface_cache_barrier();
    uint64_t synced = gpuNow();
    uint32_t fence = 0; gd_submit_marks marks = {};
    if (!gd_submit(layers, count, gd.panel.address, gd.panel.size, true, &fence, &marks)) {
        gd.disabled = true;
        if (!RedfinGPUDisplayWritable()) {gd_hold_uncertain(); return -1;}
        return 0;
    }
    if (!gd_panel_readback(fence,layers,count,marks.direct)) {
        gd.disabled = true;
        if(!RedfinGPUDisplayWritable()){gd_hold_uncertain();return -1;}
        IOLog("REDFIN GPU DISPLAY: completed panel readback differs; CPU fallback restored\n");
        return 0;
    }
    uint64_t checked = gpuNow();
    ++gd.calls; gd.elapsed += checked - synced;
    if (gd.calls <= 4 || !(gd.calls % 120)) {
        IOLog("REDFIN GPU DISPLAY PRESENT: calls=%llu fence=%u layers=%u average-us=%llu CPU-pixel-copy=0 fallbacks=%llu\n",
            gd.calls, fence, count, gd.elapsed / 1000 / gd.calls, gd.fallbacks);
        /* Adjacent host scopes in us: prepare, source sync, build, command
         * sync, native submit/wait, readback, total. All values fit one line
         * even at their type maxima. No extra pixel readback is introduced. */
        IOLog("REDFIN GPU OUTPUT CACHE: f=%llu WC=%llu cached=%llu actual-owned-mappings=1\n",
            gd.calls,gd.wc_sources,gd.cached_sources);
        uint32_t cleared = RF_GD_PANEL_W * RF_GD_PANEL_H -
            layers[0].destination.w * layers[0].destination.h;
        IOLog("REDFIN GPU OUTPUT: f=%llu n=%u clear=%u us=%llu,%llu,%llu,%llu,%llu,%llu,%llu scope=1\n",
            gd.calls, count, cleared, (prepared-began)/1000, (synced-prepared)/1000,
            (marks.built-synced)/1000, (marks.published-marks.built)/1000,
            (marks.finished-marks.published)/1000, (checked-marks.finished)/1000,
            (checked-began)/1000);
    }
    return 1;
}

#include "RedfinGPUQueuedPresent.inc"
