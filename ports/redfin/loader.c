/* Bounded SWEETXNU v1 loader. All checks precede destination writes. */
#include "loader.h"
#include "config.h"
#include "watchdog.h"
#include <stddef.h>

#if XNU_PAYLOAD_SIZE
#define PAGE 0x4000ULL
struct segment { uint64_t va, size, offset, bytes; };
struct payload {
    unsigned char magic[8];
    uint32_t version, count;
    uint64_t virt, entry, adt_offset, adt_size, kernel_end, phys, memory;
    char command[608];
    struct segment segments[];
};
struct boot_args {
    uint16_t revision, version;
    uint64_t virt, phys, memory, top, video[6];
    uint32_t machine;
    uint64_t tree;
    uint32_t tree_size;
    char command[608];
    uint64_t flags, actual_memory;
};
struct plan { uint64_t adt, args, top, entry; };
_Static_assert(offsetof(struct payload, segments) == 680, "payload ABI");
_Static_assert(sizeof(struct boot_args) == 736, "boot args ABI");

static uint32_t word(const volatile unsigned char *p, int big)
{
    uint32_t n = 0;
    for (unsigned i = 0; i < 4; i++) n |= (uint32_t)p[i] << (8 * (big ? 3 - i : i));
    return n;
}
static uint64_t quad(const volatile unsigned char *p)
{
    return word(p, 0) | (uint64_t)word(p + 4, 0) << 32;
}
static int same(const volatile unsigned char *p, uint64_t size, const char *s)
{
    for (uint64_t i = 0; i < size; i++) {
        if (p[i] != (unsigned char)s[i]) return 0;
        if (!s[i]) return 1;
    }
    return 0;
}
static int span(uint64_t start, uint64_t size) { return size && size <= UINT64_MAX - start; }
static int overlap(uint64_t a, uint64_t n, uint64_t b, uint64_t m)
{ return n && m && a < b + m && b < a + n; }

/* Parse a bounded ADT, including its shape, boot CPU and RAM properties. */
static int adt_valid(const volatile unsigned char *b, uint64_t size,
    uint64_t mpidr, uint64_t base, uint64_t memory)
{
    uint32_t pending[32], kinds[32];
    unsigned depth = 0, cpus = 0, chosen = 0;
    uint64_t off = 0;
    pending[0] = 1; kinds[0] = 0;
    for (;;) {
        while (!pending[depth]) { if (!depth) return off == size && cpus == 1 && chosen == 1; depth--; }
        pending[depth]--;
        if (depth == 31 || off > size || size - off < 8) return 0;
        uint32_t props = word(b + off, 0), children = word(b + off + 4, 0);
        unsigned kind = 0, seen = 0;
        off += 8;
        if (!props || props > 1024 || children > 1024) return 0;
        for (uint32_t i = 0; i < props; i++) {
            if (size - off < 36) return 0;
            const volatile unsigned char *key = b + off;
            uint32_t len = word(key + 32, 0);
            off += 36;
            uint64_t padded = ((uint64_t)len + 3) & ~3ULL;
            if ((len & 0x80000000U) || padded > size - off) return 0;
            const volatile unsigned char *value = b + off;
            if (!i) {
                if (!same(key, 32, "name")) return 0;
                if (depth == 1 && same(value, len, "cpus")) { if (children != 1) return 0; kind = 1; }
                if (depth == 1 && same(value, len, "chosen")) kind = 2;
                if (depth == 2 && kinds[depth] == 1) {
                    if (!same(value, len, "cpu0")) return 0;
                    kind = 3;
                }
            } else if (kind == 3 && same(key, 32, "reg")) {
                if (len != 4 || word(value, 0) != mpidr) return 0;
                seen |= 1;
            } else if (kind == 2 && same(key, 32, "dram-base")) {
                if (len != 8 || quad(value) != base) return 0;
                seen |= 1;
            } else if (kind == 2 && same(key, 32, "dram-size")) {
                if (len != 8 || quad(value) != memory) return 0;
                seen |= 2;
            }
            off += padded;
        }
        if (kind == 3) { if (seen != 1) return 0; cpus++; }
        if (kind == 2) { if (seen != 3) return 0; chosen++; }
        depth++; pending[depth] = children; kinds[depth] = kind;
    }
}

static const char *validate(const void *data, uint64_t size, uint64_t image,
    uint64_t image_end, uint64_t dtb, const struct hardware *hw, uint64_t mpidr, struct plan *q)
{
    const struct payload *p = data;
    if (!hw || !hw->redfin || !hw->psci_smc || !hw->banks || hw->banks > MAX_BANKS ||
        hw->reservations > MAX_RESERVED) return "invalid redfin hardware";
    if (!data || size < 680 || !span((uintptr_t)data, size) || image >= image_end ||
        (uintptr_t)data < image || (uintptr_t)data > image_end || size > image_end - (uintptr_t)data) return "payload bounds";
    if ((uintptr_t)data & (PAGE - 1)) return "payload alignment";
    for (unsigned i = 0; i < 8; i++) if (p->magic[i] != (unsigned char)"SWEETXNU"[i]) return "payload magic";
    if (p->version != 1 || !p->count || p->count > 64 || 680 + 32ULL * p->count > size) return "payload header";
    uint64_t table = 680 + 32ULL * p->count;
    if (!span(p->phys, p->memory) || !p->phys || (p->phys | p->memory | p->virt | p->kernel_end) & (PAGE - 1) ||
        p->phys + p->memory > (1ULL << 36) || p->memory > UINT64_MAX - p->virt) return "RAM window";
    int bank = 0;
    for (unsigned i = 0; i < hw->banks; i++) {
        struct region r = hw->memory[i];
        if (!span(r.base, r.size)) return "RAM bank overflow";
        if (p->phys >= r.base && p->phys + p->memory <= r.base + r.size) bank = 1;
    }
    if (!bank || overlap(p->phys, p->memory, image, image_end - image)) return "RAM outside bank or overlaps Image";
    for (unsigned i = 0; i < hw->reservations; i++) {
        struct region r = hw->reserved[i];
        if (!span(r.base, r.size) || overlap(p->phys, p->memory, r.base, r.size)) return "RAM overlaps reservation";
    }
    if (!dtb || (dtb & 7) || !span(dtb, 40)) return "DTB address";
    const volatile unsigned char *fdt = (const void *)(uintptr_t)dtb;
    uint32_t dtb_size = word(fdt + 4, 1);
    if (word(fdt, 1) != 0xd00dfeed || dtb_size < 40 || dtb_size > 0x200000 || !span(dtb, dtb_size) ||
        overlap(p->phys, p->memory, dtb, dtb_size)) return "RAM overlaps DTB or bad DTB";
    unsigned nul = 0, entry = 0;
    for (unsigned i = 0; i < sizeof(p->command); i++) if (!p->command[i]) nul = 1;
    if (!nul || mpidr > 0x700 || (mpidr & 0xff)) return "command or CPU affinity";
    if ((p->adt_offset & 15) || (p->adt_size & 3) || p->adt_size < 8 || p->adt_size > UINT32_MAX ||
        p->adt_offset < table || p->adt_offset > size || p->adt_size > size - p->adt_offset) return "ADT bounds";
    uint64_t last = p->virt;
    for (unsigned i = 0; i < p->count; i++) {
        const struct segment *s = &p->segments[i];
        if (!span(s->va, s->size) || (s->va | s->size) & (PAGE - 1) || s->va < p->virt ||
            s->va - p->virt > p->memory || s->size > p->memory - (s->va - p->virt) ||
            s->bytes > s->size || (s->offset & 7) || s->offset < table ||
            s->offset > size || s->bytes > size - s->offset ||
            overlap(s->offset, s->bytes, p->adt_offset, p->adt_size)) return "segment bounds";
        for (unsigned j = 0; j < i; j++) {
            const struct segment *t = &p->segments[j];
            if (overlap(s->va, s->size, t->va, t->size) || overlap(s->offset, s->bytes, t->offset, t->bytes)) return "segments overlap";
        }
        if (s->va + s->size > last) last = s->va + s->size;
        if (p->entry >= s->va && p->entry - s->va < s->bytes) entry = 1;
    }
    if (!entry || (p->entry & 3) || p->kernel_end != last || p->kernel_end < p->virt ||
        p->kernel_end - p->virt > p->memory) return "kernel end or entry";
    q->adt = p->phys + (p->kernel_end - p->virt);
    if (p->adt_size > p->memory - (q->adt - p->phys) || !span(q->adt, p->adt_size + 15)) return "ADT destination";
    q->args = (q->adt + p->adt_size + 15) & ~15ULL;
    if (!span(q->args, sizeof(struct boot_args) + PAGE - 1)) return "boot args overflow";
    q->top = (q->args + sizeof(struct boot_args) + PAGE - 1) & ~(PAGE - 1);
    if (q->top > p->phys + p->memory) return "boot args outside RAM";
    q->entry = p->phys + (p->entry - p->virt);
    if (!adt_valid((const volatile unsigned char *)data + p->adt_offset, p->adt_size, mpidr, p->phys, p->memory)) return "ADT CPU or RAM mismatch";
    return NULL;
}

#ifdef REDFIN_LOADER_TEST
const char *redfin_validate(const void *data, uint64_t size, uint64_t image,
    uint64_t image_end, uint64_t dtb, const struct hardware *hw, uint64_t mpidr)
{ struct plan q; return validate(data, size, image, image_end, dtb, hw, mpidr, &q); }
#else
extern unsigned char _head[], _end[];
#define MRS(reg) ({ uint64_t v; __asm__ volatile("mrs %0, " #reg : "=r"(v)); v; })
const char *redfin_boot(uint64_t dtb, const struct hardware *hw)
{
    uint64_t granule = (MRS(id_aa64mmfr0_el1) >> 20) & 15;
    if (MRS(CurrentEL) != 4 || (MRS(sctlr_el1) & 5) || (granule != 1 && granule != 2)) return "EL1/MMU/Dcache/16K precondition";
    uint64_t start = (uintptr_t)_head, end = (uintptr_t)_end;
    if (!span(end, PAGE - 1)) return "Image overflow";
    uint64_t source = (end + PAGE - 1) & ~(PAGE - 1);
    if (!span(source, XNU_PAYLOAD_SIZE) || start >= end || source + XNU_PAYLOAD_SIZE - start != quad(_head + 16)) return "Image size mismatch";
    const struct payload *p = (const void *)(uintptr_t)source;
    struct plan q;
    const char *error = validate(p, XNU_PAYLOAD_SIZE, start, source + XNU_PAYLOAD_SIZE, dtb, hw, MRS(mpidr_el1) & 0xffffff, &q);
    if (error) return error;
    __asm__ volatile("msr daifset, #15" ::: "memory");
    for (unsigned i = 0; i < p->count; i++) {
        const struct segment *s = &p->segments[i];
        volatile unsigned char *dst = (void *)(uintptr_t)(p->phys + (s->va - p->virt));
        const volatile unsigned char *src = (const void *)(uintptr_t)(source + s->offset);
        uint64_t j = 0;
        for (; j + 8 <= s->bytes; j += 8)
            *(volatile uint64_t *)(dst + j) = *(const volatile uint64_t *)(src + j);
        for (; j < s->bytes; j++) dst[j] = src[j];
        for (; j & 7; j++) dst[j] = 0;
        for (; j < s->size; j += 8) *(volatile uint64_t *)(dst + j) = 0;
    }
    volatile unsigned char *tree = (void *)(uintptr_t)q.adt;
    const volatile unsigned char *adt = (const void *)(uintptr_t)(source + p->adt_offset);
    for (uint64_t i = 0; i < p->adt_size; i += 4)
        *(volatile uint32_t *)(tree + i) = *(const volatile uint32_t *)(adt + i);
    volatile struct boot_args *args = (void *)(uintptr_t)q.args;
    for (unsigned i = 0; i < sizeof(*args); i += 8)
        *(volatile uint64_t *)((volatile unsigned char *)args + i) = 0;
    args->revision = args->version = 2; args->virt = p->virt; args->phys = p->phys;
    args->memory = args->actual_memory = p->memory; args->top = q.top;
    args->tree = p->virt + (q.adt - p->phys); args->tree_size = (uint32_t)p->adt_size;
    for (unsigned i = 0; i < sizeof(args->command); i++) args->command[i] = p->command[i];
    /* Start the reset deadline after potentially slow uncached relocation. */
    if (redfin_watchdog(hw, WATCHDOG_SECONDS) != 0) return "watchdog arm failed";
    __asm__ volatile("dsb sy\nic iallu\ndsb sy\nisb" ::: "memory");
    ((void (*)(uint64_t))(uintptr_t)q.entry)(q.args);
    return "XNU returned";
}
#endif
#else
const char *redfin_boot(uint64_t dtb, const struct hardware *hw)
{ (void)dtb; (void)hw; return "no XNU payload"; }
#endif
