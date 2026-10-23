/* SPDX-License-Identifier: MIT
 * Source ingestion wraps the existing native parser/planner without another
 * ELF/bundle parser or an allocation proportional to the firmware size.
 */
#include "wifi_fw_source.h"

static int ops_valid(const struct rf_wifi_fw_source_ops *o)
{ return o && o->check && o->pin && o->unpin && o->sha256; }
static int fail(struct rf_wifi_fw_source *s, int error)
{ s->poisoned = 1; s->stage = RF_WIFI_FW_QUARANTINED; s->error = error; return error; }
static int source_check(struct rf_wifi_fw_source *s, const struct rf_wifi_fw_source_ops *o)
{
    if (o->context != s->operations.context || o->check != s->operations.check ||
        o->pin != s->operations.pin || o->unpin != s->operations.unpin || o->sha256 != s->operations.sha256)
        return RF_WIFI_FW_CHANGED;
    int error = o->check(o->context, &s->blob, &s->layout);
    if (error) s->platform_error = error;
    return error ? RF_WIFI_FW_PLATFORM : RF_WIFI_FW_OK;
}
static int inside(struct redfin_mpss_range outer, struct redfin_mpss_range inner)
{
    return redfin_mpss_valid_range(outer.base, outer.bytes) && redfin_mpss_valid_range(inner.base, inner.bytes) &&
        inner.base >= outer.base && inner.base - outer.base < outer.bytes &&
        inner.bytes <= outer.bytes - (inner.base - outer.base);
}
static int pointer_overlap(const void *a, size_t n, const void *b, size_t m)
{
    uintptr_t x = (uintptr_t)a, y = (uintptr_t)b;
    return x > UINTPTR_MAX - n || y > UINTPTR_MAX - m || (x < y + m && y < x + n);
}

int rf_wifi_fw_layout_valid(const struct rf_wifi_fw_blob *b, const struct rf_wifi_fw_layout *l)
{
    if (!b || !l || !b->boot_id || !b->bytes || b->bytes > REDFIN_MPSS_MAX_BUNDLE ||
        b->bytes > UINT64_MAX - (RF_WIFI_FW_PAGE - 1u) ||
        b->reserved != ((b->bytes + RF_WIFI_FW_PAGE - 1u) & ~(RF_WIFI_FW_PAGE - 1u)) ||
        (b->physical & (RF_WIFI_FW_PAGE - 1u)) ||
        l->ram.base != UINT64_C(0x180000000) || l->ram.bytes != UINT64_C(0x80000000) ||
        !inside(l->ram, (struct redfin_mpss_range){b->physical, b->reserved}) ||
        l->kernel_end <= l->ram.base || l->kernel_end > b->physical ||
        (l->kernel_end & (RF_WIFI_FW_PAGE - 1u)) ||
        l->adt.base != b->physical + b->reserved || !l->adt.bytes || l->adt.bytes > RF_WIFI_FW_MAX_ADT ||
        !inside(l->ram, l->adt) || !inside(l->ram, l->arguments) ||
        l->arguments.bytes != RF_WIFI_FW_BOOT_ARGS_BYTES ||
        l->arguments.base != ((l->adt.base + l->adt.bytes + 15u) & ~UINT64_C(15)) ||
        l->top != ((l->arguments.base + l->arguments.bytes + RF_WIFI_FW_PAGE - 1u) & ~(RF_WIFI_FW_PAGE - 1u)) ||
        l->top > l->ram.base + l->ram.bytes)
        return 0;
    if (l->ramdisk.base || l->ramdisk.bytes) {
        if (!inside(l->ram, l->ramdisk) || l->ramdisk.base < l->kernel_end ||
            l->ramdisk.base + l->ramdisk.bytes > b->physical ||
            ((l->ramdisk.base | l->ramdisk.bytes) & (RF_WIFI_FW_PAGE - 1u))) return 0;
    }
    unsigned digest = 0;
    for (unsigned i = 0; i < 32; ++i) digest |= b->sha256[i];
    return digest != 0;
}

static int blob_hash(struct rf_wifi_fw_source *s, const struct rf_wifi_fw_source_ops *o)
{
    uint8_t digest[32];
    int error = source_check(s, o);
    if (error) return error;
    error = o->sha256(o->context, s->data, (size_t)s->blob.bytes, digest);
    if (error) { s->platform_error = error; return RF_WIFI_FW_PLATFORM; }
    if (!redfin_mpss_equal(digest, s->blob.sha256, sizeof(digest))) return RF_WIFI_FW_HASH;
    for (uint64_t i = s->blob.bytes; i < s->blob.reserved; ++i)
        if (s->data[(size_t)i]) return RF_WIFI_FW_CHANGED;
    return source_check(s, o);
}

static int workspace_hash(struct rf_wifi_fw_source *s, const struct rf_wifi_fw_source_ops *o, int capture)
{
    uint8_t digest[32];
    int error = source_check(s, o);
    if (error) return error;
    error = o->sha256(o->context, (const uint8_t *)s->workspace, sizeof(*s->workspace), digest);
    if (error) { s->platform_error = error; return RF_WIFI_FW_PLATFORM; }
    if (capture) for (unsigned i = 0; i < 32; ++i) s->workspace_sha256[i] = digest[i];
    else if (!redfin_mpss_equal(digest, s->workspace_sha256, sizeof(digest))) return RF_WIFI_FW_CHANGED;
    return source_check(s, o);
}

int rf_wifi_fw_source_open(struct rf_wifi_fw_source *s, const struct rf_wifi_fw_blob *b,
    const struct rf_wifi_fw_layout *l, const struct redfin_mpss_range *excluded, size_t count,
    struct redfin_mpss_workspace *workspace, const struct rf_wifi_fw_source_ops *o)
{
    if (!s || !b || !l || !workspace || !ops_valid(o) || !excluded || count < 2 ||
        count > REDFIN_MPSS_MAX_EXCLUSIONS) return RF_WIFI_FW_ARGUMENT;
    if (pointer_overlap(workspace, sizeof(*workspace), s, sizeof(*s)) ||
        pointer_overlap(workspace, sizeof(*workspace), b, sizeof(*b)) ||
        pointer_overlap(workspace, sizeof(*workspace), l, sizeof(*l)) ||
        pointer_overlap(workspace, sizeof(*workspace), o, sizeof(*o)) ||
        pointer_overlap(workspace, sizeof(*workspace), excluded, count * sizeof(*excluded))) return RF_WIFI_FW_ARGUMENT;
    if (s->attempted || s->stage != RF_WIFI_FW_IDLE) return RF_WIFI_FW_STATE;
    s->attempted = 1; s->blob = *b; s->layout = *l; s->workspace = workspace; s->operations = *o;
    if (!rf_wifi_fw_layout_valid(b, l)) return fail(s, RF_WIFI_FW_LAYOUT);
    int kernel = 0, framebuffer = 0;
    for (size_t i = 0; i < count; ++i) {
        kernel |= excluded[i].base == l->ram.base && excluded[i].bytes == l->ram.bytes;
        framebuffer |= excluded[i].base == UINT64_C(0xa0000000) && excluded[i].bytes == UINT64_C(0x02300000);
    }
    if (!kernel || !framebuffer) return fail(s, RF_WIFI_FW_LAYOUT);
    int error = source_check(s, o);
    if (!error) {
        error = o->pin(o->context, b->physical, b->reserved, &s->data);
        if (error) { s->platform_error = error; error = RF_WIFI_FW_PLATFORM; }
        else { s->pinned = 1; s->stage = RF_WIFI_FW_PINNED; }
    }
    if (!error && (!s->data || (uintptr_t)s->data > UINTPTR_MAX - b->reserved)) error = RF_WIFI_FW_LAYOUT;
    if (!error && ((uintptr_t)workspace > UINTPTR_MAX - sizeof(*workspace) ||
        ((uintptr_t)workspace < (uintptr_t)s->data + b->reserved &&
         (uintptr_t)s->data < (uintptr_t)workspace + sizeof(*workspace)))) error = RF_WIFI_FW_LAYOUT;
    if (!error) error = blob_hash(s, o);
    if (!error) {
        redfin_mpss_clear(workspace, sizeof(*workspace));
        s->planner_error = redfin_mpss_bundle_open(s->data, (size_t)b->bytes, excluded, count,
            o->sha256, o->context, &workspace->plan, &workspace->image, &workspace->scratch);
        if (s->planner_error) error = RF_WIFI_FW_PLAN;
    }
    if (!error) error = workspace_hash(s, o, 1);
    if (error) {
        if (s->pinned) { o->unpin(o->context); s->pinned = 0; s->data = NULL; }
        return fail(s, error);
    }
    s->stage = RF_WIFI_FW_VERIFIED;
    return RF_WIFI_FW_OK;
}

static int copy_valid(struct rf_wifi_fw_source *s, const struct rf_wifi_fw_source_ops *o,
    const struct rf_wifi_fw_copy_ops *c, uint8_t *readback, size_t bytes)
{
    if (!s || !ops_valid(o) || !c || !c->check || !c->write || !c->zero || !c->read || !c->sync ||
        !readback || bytes != REDFIN_MPSS_COPY_CHUNK || (uintptr_t)readback > UINTPTR_MAX - bytes)
        return RF_WIFI_FW_ARGUMENT;
    if (!s->pinned || !s->data || !s->workspace || s->poisoned) return RF_WIFI_FW_STATE;
    uintptr_t start = (uintptr_t)readback, source = (uintptr_t)s->data, workspace = (uintptr_t)s->workspace;
    if ((start < source + s->blob.reserved && source < start + bytes) ||
        (start < workspace + sizeof(*s->workspace) && workspace < start + bytes) ||
        pointer_overlap(readback, bytes, s, sizeof(*s)) || pointer_overlap(readback, bytes, o, sizeof(*o)) ||
        pointer_overlap(readback, bytes, c, sizeof(*c))) return RF_WIFI_FW_ARGUMENT;
    return workspace_hash(s, o, 0);
}
static int copy_check(struct rf_wifi_fw_source *s, const struct rf_wifi_fw_source_ops *o,
    const struct rf_wifi_fw_copy_ops *c, unsigned phase)
{
    int error = source_check(s, o);
    if (error) return error;
    error = c->check(c->context, &s->workspace->plan, phase);
    if (error) { s->platform_error = error; return RF_WIFI_FW_PLATFORM; }
    return RF_WIFI_FW_OK;
}

static int copy_chunk(struct rf_wifi_fw_source *s, const struct rf_wifi_fw_source_ops *o,
    const struct rf_wifi_fw_copy_ops *c, unsigned phase, uint64_t physical,
    const uint8_t *data, uint32_t bytes, uint8_t *readback)
{
    int error = workspace_hash(s, o, 0);
    if (!error) error = copy_check(s, o, c, phase);
    if (!error) {
        int platform = data ? c->write(c->context, physical, data, bytes) : c->zero(c->context, physical, bytes);
        if (platform) { s->platform_error = platform; error = RF_WIFI_FW_PLATFORM; }
    }
    if (!error) error = copy_check(s, o, c, phase);
    if (!error) {
        int platform = c->read(c->context, physical, readback, bytes);
        if (platform) { s->platform_error = platform; error = RF_WIFI_FW_PLATFORM; }
    }
    if (!error) {
        if (data) {
            if (!redfin_mpss_equal(data, readback, bytes)) error = RF_WIFI_FW_READBACK;
        } else for (uint32_t i = 0; i < bytes; ++i) if (readback[i]) { error = RF_WIFI_FW_READBACK; break; }
    }
    if (!error) error = copy_check(s, o, c, phase);
    if (!error) s->readback_bytes += bytes;
    return error;
}
static int copy_sync(struct rf_wifi_fw_source *s, const struct rf_wifi_fw_source_ops *o,
    const struct rf_wifi_fw_copy_ops *c, unsigned phase, uint64_t physical, uint64_t bytes)
{
    int error = copy_check(s, o, c, phase);
    if (!error) {
        int platform = c->sync(c->context, physical, bytes);
        if (platform) { s->platform_error = platform; error = RF_WIFI_FW_PLATFORM; }
    }
    if (!error) error = copy_check(s, o, c, phase);
    return error;
}

int rf_wifi_fw_copy_metadata_to(struct rf_wifi_fw_source *s, const struct rf_wifi_fw_source_ops *o,
    const struct rf_wifi_fw_copy_ops *c, uint64_t physical, uint8_t *readback, size_t bytes)
{
    if (!s || !redfin_mpss_valid_range(physical, RF_WIFI_FW_PAGE) || (physical & (RF_WIFI_FW_PAGE - 1u)))
        return RF_WIFI_FW_ARGUMENT;
    int error = copy_valid(s, o, c, readback, bytes);
    if (error) return error == RF_WIFI_FW_ARGUMENT || error == RF_WIFI_FW_STATE ? error : fail(s, error);
    if (s->stage != RF_WIFI_FW_VERIFIED) return RF_WIFI_FW_STATE;
    error = blob_hash(s, o);
    if (!error) error = copy_chunk(s, o, c, RF_WIFI_FW_METADATA, physical,
        s->workspace->image.asset[0].data, s->workspace->image.asset[0].bytes, readback);
    if (!error) error = copy_sync(s, o, c, RF_WIFI_FW_METADATA, physical,
        s->workspace->image.asset[0].bytes);
    if (error) return fail(s, error);
    s->metadata_written = s->workspace->image.asset[0].bytes; s->stage = RF_WIFI_FW_METADATA;
    return RF_WIFI_FW_OK;
}

int rf_wifi_fw_copy_metadata(struct rf_wifi_fw_source *s, const struct rf_wifi_fw_source_ops *o,
    const struct rf_wifi_fw_copy_ops *c, uint8_t *readback, size_t bytes)
{
    if (!s || !s->workspace) return RF_WIFI_FW_ARGUMENT;
    return rf_wifi_fw_copy_metadata_to(s, o, c, s->workspace->plan.physical_base, readback, bytes);
}

int rf_wifi_fw_copy_segments(struct rf_wifi_fw_source *s, const struct rf_wifi_fw_source_ops *o,
    const struct rf_wifi_fw_copy_ops *c, uint8_t *readback, size_t bytes)
{
    int error = copy_valid(s, o, c, readback, bytes);
    if (error) return error == RF_WIFI_FW_ARGUMENT || error == RF_WIFI_FW_STATE ? error : fail(s, error);
    if (s->stage != RF_WIFI_FW_METADATA) return RF_WIFI_FW_STATE;
    error = blob_hash(s, o);
    uint32_t asset = 1;
    for (uint32_t i = 0; i < s->workspace->plan.segments && !error; ++i) {
        const struct redfin_mpss_segment *segment = &s->workspace->plan.segment[i];
        const uint8_t *data = segment->file_bytes ? s->workspace->image.asset[asset++].data : NULL;
        uint32_t offset = 0;
        while (offset < segment->memory_bytes && !error) {
            uint32_t limit = offset < segment->file_bytes ? segment->file_bytes : segment->memory_bytes;
            uint32_t take = limit - offset;
            if (take > REDFIN_MPSS_COPY_CHUNK) take = REDFIN_MPSS_COPY_CHUNK;
            int file = offset < segment->file_bytes;
            error = copy_chunk(s, o, c, RF_WIFI_FW_SEGMENTS, segment->physical_address + offset,
                file ? data + offset : NULL, take, readback);
            if (!error) { if (file) s->copied_bytes += take; else s->zeroed_bytes += take; offset += take; }
        }
    }
    if (!error) error = copy_sync(s, o, c, RF_WIFI_FW_SEGMENTS, s->workspace->plan.physical_base,
        s->workspace->plan.memory_bytes);
    if (error) return fail(s, error);
    s->stage = RF_WIFI_FW_SEGMENTS;
    return RF_WIFI_FW_OK;
}

void rf_wifi_fw_source_close(struct rf_wifi_fw_source *s, const struct rf_wifi_fw_source_ops *o)
{
    (void)o;
    if (!s) return;
    if (s->pinned && s->operations.unpin) {
        s->operations.unpin(s->operations.context); s->pinned = 0; s->data = NULL;
    }
    if (s->attempted) s->stage = RF_WIFI_FW_CLOSED;
}
