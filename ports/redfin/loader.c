/* Bounded SWEETXNU v1 loader. All checks precede destination writes. */
#include "loader.h"
#include "config.h"
#include "watchdog.h"
#include <stddef.h>
#include "gui-profile.h"
#include "wifi-identity.h"

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
struct plan { uint64_t adt, args, top, entry, rmtfs_pool, rmtfs_owned, wlfw_verified, wifi_dma_pool, wifi_dma_owned; };
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
static int adt_valid_up(const volatile unsigned char *b, uint64_t size,
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

/* The optional RMTFS pool is allocated from live free DRAM, outside XNU.
 * Validate the actual ABL source/DTB as well as all inherited reservations.
 * Merely naming a range in an ADT does not grant ownership of its memory. */
static int rmtfs_plan(const struct payload *p, const struct hardware *hw,
    uint64_t image, uint64_t image_bytes, uint64_t dtb, uint64_t dtb_bytes, struct plan *q)
{
    const volatile unsigned char *b = (const volatile unsigned char *)p + p->adt_offset;
    uint32_t pending[32], kinds[32];
    uint64_t pool[2] = {0}, shared[2] = {0}, snapshot[2] = {0}, scratch[2] = {0}, maps[6] = {0}, bytes = 0;
    uint64_t off = 0, owned = 0, wlfw_reg[2] = {0}, wlfw_verified = 0;
    unsigned depth = 0, nodes = 0, map_seen = 0, wlfw_nodes = 0;
    q->rmtfs_pool = q->rmtfs_owned = q->wlfw_verified = 0;
    pending[0] = 1; kinds[0] = 0;
    for (;;) {
        while (!pending[depth]) { if (!depth) goto parsed; --depth; }
        --pending[depth];
        if (depth == 31 || off > p->adt_size || p->adt_size - off < 8) return 0;
        uint32_t props = word(b + off, 0), children = word(b + off + 4, 0), kind = 0, seen = 0;
        off += 8;
        if (!props || props > 1024 || children > 1024) return 0;
        for (uint32_t i = 0; i < props; ++i) {
            if (p->adt_size - off < 36) return 0;
            const volatile unsigned char *key = b + off;
            uint32_t length = word(key + 32, 0);
            off += 36;
            uint64_t padded = ((uint64_t)length + 3) & ~3ULL;
            if ((length & 0x80000000u) || padded > p->adt_size - off) return 0;
            const volatile unsigned char *value = b + off;
            if (!i) {
                if (!same(key, 32, "name")) return 0;
                if (depth == 1 && same(value, length, "redfin-rmtfs")) {
                    if (++nodes != 1 || props != 9 || children) return 0;
                    kind = 1;
                } else if (depth == 1 && same(value, length, "redfin-wifi-wlfw")) {
                    if (++wlfw_nodes != 1 || props != 4 || children) return 0;
                    kind = 4;
                } else if (depth == 1 && same(value, length, "chosen")) kind = 2;
                else if (depth == 2 && kinds[depth] == 2 && same(value, length, "memory-map")) kind = 3;
            } else if (kind == 1) {
                unsigned bit = 0;
                uint64_t *region = NULL;
                if (same(key, 32, "pool-reg")) { bit = 1; region = pool; }
                else if (same(key, 32, "shared-reg")) { bit = 2; region = shared; }
                else if (same(key, 32, "snapshot-reg")) { bit = 4; region = snapshot; }
                else if (same(key, 32, "scratch-reg")) { bit = 8; region = scratch; }
                else if (same(key, 32, "source-contract")) {
                    const uint32_t expected[10] = {1, 14, 1, 0x4003, 512, 4, 0x280000, 3, 15, 6};
                    bit = 16;
                    if (length != sizeof(expected)) return 0;
                    for (unsigned j = 0; j < 10; ++j) if (word(value + 4u * j, 0) != expected[j]) return 0;
                } else if (same(key, 32, "bundle-bytes")) {
                    bit = 32; if (length != 8) return 0; bytes = quad(value);
                } else if (same(key, 32, "bundle-sha256")) {
                    unsigned nonzero = 0; bit = 64;
                    if (length != 32) return 0;
                    for (unsigned j = 0; j < 32; ++j) nonzero |= value[j];
                    if (!nonzero) return 0;
                } else if (same(key, 32, "shim-owned")) {
                    bit = 128; if (length != 4 || word(value, 0)) return 0; owned = off;
                } else return 0;
                if (seen & bit) return 0;
                seen |= bit;
                if (region) { if (length != 16) return 0; region[0] = quad(value); region[1] = quad(value + 8); }
            } else if (kind == 4) {
                unsigned bit = 0;
                if (same(key, 32, "reg")) {
                    bit = 1; if (length != 16) return 0;
                    wlfw_reg[0] = quad(value); wlfw_reg[1] = quad(value + 8);
                } else if (same(key, 32, "source-contract")) {
                    const uint32_t expected[10] = {1, 0x45, 1, 0, 0x4b4e454c, 0, 2, 4096, 0x2d, 0x2e};
                    bit = 2; if (length != sizeof(expected)) return 0;
                    for (unsigned j = 0; j < 10; ++j) if (word(value + 4u * j, 0) != expected[j]) return 0;
                } else if (same(key, 32, "shim-verified")) {
                    bit = 4; if (length != 4 || word(value, 0)) return 0; wlfw_verified = off;
                } else return 0;
                if (seen & bit) return 0;
                seen |= bit;
            } else if (kind == 3) {
                unsigned index = 0, bit = 0;
                if (same(key, 32, "RedfinRMTFSPool")) { index = 0; bit = 1; }
                else if (same(key, 32, "RedfinRMTFSSnapshot")) { index = 2; bit = 2; }
                else if (same(key, 32, "RedfinRMTFSScratch")) { index = 4; bit = 4; }
                if (bit) {
                    if ((map_seen & bit) || length != 16) return 0;
                    map_seen |= bit; maps[index] = quad(value); maps[index + 1] = quad(value + 8);
                }
            }
            off += padded;
        }
        if (kind == 1 && seen != 255) return 0;
        if (kind == 4 && seen != 7) return 0;
        ++depth; pending[depth] = children; kinds[depth] = kind;
    }
parsed:
    if (off != p->adt_size) return 0;
    if (!nodes && !map_seen) return wlfw_nodes ? 0 : 1;
    if (nodes != 1 || map_seen != 7 || !owned || pool[0] != maps[0] || pool[1] != maps[1] ||
        snapshot[0] != maps[2] || snapshot[1] != maps[3] || scratch[0] != maps[4] || scratch[1] != maps[5] ||
        pool[0] < 0x80000000ULL || pool[0] > 0x100000000ULL - 0x288000 || pool[1] != 0x288000 ||
        (pool[0] & (PAGE - 1)) || shared[0] != pool[0] + PAGE || shared[1] != 0x280000 ||
        bytes < 576 || bytes > 12u * 1024u * 1024u || snapshot[1] != ((bytes + PAGE - 1) & ~(PAGE - 1)) ||
        !span(snapshot[0], snapshot[1]) || snapshot[0] < p->phys || (snapshot[0] & (PAGE - 1)) ||
        scratch[0] != snapshot[0] + snapshot[1] || scratch[1] != PAGE ||
        overlap(pool[0], pool[1], p->phys, p->memory) || overlap(pool[0], pool[1], image, image_bytes) ||
        overlap(pool[0], pool[1], dtb, dtb_bytes)) return 0;
    const char *const required[] = {"cpus=1", "rd=md0", "redfinwififw=4", "redfinwifinative=1",
        "redfinwifi=2", "redfinspmi=1", "redfinreturn=1", "modem=0", "wifi=0", "gpu=0", "sweetusb=0"};
    unsigned command_seen = 0;
    for (unsigned at = 0; at < sizeof(p->command) && p->command[at];) {
        if (p->command[at] == ' ') { ++at; continue; }
        unsigned first = at;
        while (at < sizeof(p->command) && p->command[at] && p->command[at] != ' ') ++at;
        for (unsigned i = 0; i < 11; ++i) {
            unsigned j = 0;
            while (j < at - first && required[i][j] && p->command[first + j] == required[i][j]) ++j;
            if (j == at - first && !required[i][j]) {
                if (command_seen & (1u << i)) return 0;
                command_seen |= 1u << i;
            }
        }
    }
    if (command_seen != 2047 && !redfin_wifi_gui_profile(p->command, sizeof(p->command), NULL)) return 0;
    unsigned bank = 0, source = 0, arguments = 0;
    for (unsigned i = 0; i < hw->banks; ++i) if (pool[0] >= hw->memory[i].base &&
        pool[0] + pool[1] <= hw->memory[i].base + hw->memory[i].size) bank = 1;
    if (!bank) return 0;
    for (unsigned i = 0; i < hw->reservations; ++i)
        if (overlap(pool[0], pool[1], hw->reserved[i].base, hw->reserved[i].size)) return 0;
    for (unsigned i = 0; i < p->count; ++i) {
        const struct segment *s = &p->segments[i];
        uint64_t physical = p->phys + s->va - p->virt;
        if (physical == snapshot[0] && s->size == snapshot[1] && s->bytes == bytes) ++source;
        if (physical == scratch[0] && s->size == PAGE && s->bytes == PAGE) {
            const volatile unsigned char *data = (const volatile unsigned char *)p + s->offset;
            for (unsigned j = 0; j < PAGE; ++j) if (data[j]) return 0;
            ++arguments;
        }
    }
    if (source != 1 || arguments != 1) return 0;
    if (wlfw_nodes) {
        unsigned reserved = 0;
        if (!wlfw_verified || wlfw_reg[0] != 0x8ba00000 || wlfw_reg[1] != 0x200000 ||
            overlap(wlfw_reg[0], wlfw_reg[1], p->phys, p->memory) ||
            overlap(wlfw_reg[0], wlfw_reg[1], image, image_bytes) ||
            overlap(wlfw_reg[0], wlfw_reg[1], dtb, dtb_bytes)) return 0;
        for (unsigned i = 0; i < hw->reservations; ++i) {
            struct region r = hw->reserved[i];
            if (r.base == wlfw_reg[0] && r.size == wlfw_reg[1]) ++reserved;
            else if (overlap(r.base, r.size, wlfw_reg[0], wlfw_reg[1])) return 0;
        }
        if (reserved != 1) return 0;
        q->wlfw_verified = wlfw_verified;
    }
    q->rmtfs_pool = pool[0]; q->rmtfs_owned = owned;
    return 1;
}

/* Separate fresh DMA32 allocation; RMTFS memory is never recycled for CE.
 * The exact current ABL Image/DTB and inherited fixed reservations take
 * precedence over the producer's proposed address. All checks precede writes. */
static int wifi_dma_plan(const struct payload *p, const struct hardware *hw,
    uint64_t image, uint64_t image_bytes, uint64_t dtb, uint64_t dtb_bytes, struct plan *q)
{
    const volatile unsigned char *b = (const volatile unsigned char *)p + p->adt_offset;
    uint32_t pending[32], kinds[32];
    uint64_t pool[2] = {0}, buffer[2] = {0}, map[2] = {0}, off = 0, owned = 0;
    unsigned depth = 0, nodes = 0, maps = 0, snoc_nodes = 0, rx_seen = 0;
    q->wifi_dma_pool = q->wifi_dma_owned = 0;
    pending[0] = 1; kinds[0] = 0;
    for (;;) {
        while (!pending[depth]) { if (!depth) goto parsed; --depth; }
        --pending[depth];
        if (depth == 31 || off > p->adt_size || p->adt_size - off < 8) return 0;
        uint32_t props = word(b + off, 0), children = word(b + off + 4, 0), kind = 0, seen = 0;
        off += 8;
        if (!props || props > 1024 || children > 1024) return 0;
        for (unsigned i = 0; i < props; ++i) {
            if (p->adt_size - off < 36) return 0;
            const volatile unsigned char *key = b + off;
            uint32_t length = word(key + 32, 0); off += 36;
            uint64_t padded = ((uint64_t)length + 3) & ~3ULL;
            if ((length & 0x80000000u) || padded > p->adt_size - off) return 0;
            const volatile unsigned char *value = b + off;
            if (!i) {
                if (!same(key, 32, "name")) return 0;
                if (depth == 1 && same(value, length, "redfin-wifi-dma")) {
                    if (++nodes != 1 || props != 5 || children) return 0;
                    kind = 1;
                } else if (depth == 1 && same(value, length, "redfin-wifi-snoc")) {
                    if (++snoc_nodes != 1 || children) return 0;
                    kind = 4;
                } else if (depth == 1 && same(value, length, "chosen")) kind = 2;
                else if (depth == 2 && kinds[depth] == 2 && same(value, length, "memory-map")) kind = 3;
            } else if (kind == 1) {
                unsigned bit = 0;
                if (same(key, 32, "reg") || same(key, 32, "buffer-reg")) {
                    uint64_t *region = same(key, 32, "reg") ? pool : buffer;
                    bit = region == pool ? 1u : 2u;
                    if (length != 16) return 0;
                    region[0] = quad(value); region[1] = quad(value + 8);
                } else if (same(key, 32, "source-contract")) {
                    const uint32_t expected[10] = {1, 0xc0, 1, 0x1000000, 0x4000, 12, 32, 2048, 1, 0};
                    bit = 4; if (length != sizeof(expected)) return 0;
                    for (unsigned j = 0; j < 10; ++j) if (word(value + 4u*j, 0) != expected[j]) return 0;
                } else if (same(key, 32, "shim-owned")) {
                    bit = 8; if (length != 4 || word(value, 0)) return 0; owned = off;
                } else return 0;
                if (seen & bit) return 0;
                seen |= bit;
            } else if (kind == 3 && same(key, 32, "RedfinWiFiDMA")) {
                if (++maps != 1 || length != 16) return 0;
                map[0] = quad(value); map[1] = quad(value + 8);
            } else if (kind == 4) {
                unsigned bit = same(key, 32, "packets-enable") ? 1u :
                    same(key, 32, "ns-context-allocator") ? 2u : same(key, 32, "mission-enable") ? 4u : 0;
                if (bit) {
                    if ((rx_seen & bit) || length != 4 || word(value, 0) != 1) return 0;
                    rx_seen |= bit;
                }
            }
            off += padded;
        }
        if (kind == 1 && seen != 15) return 0;
        ++depth; pending[depth] = children; kinds[depth] = kind;
    }
parsed:
    if (off != p->adt_size) return 0;
    if (!nodes && !maps) return !(rx_seen & 3u);
    if (nodes != 1 || maps != 1 || snoc_nodes != 1 || rx_seen != 7 || !owned ||
        !q->rmtfs_pool || !q->wlfw_verified || pool[0] != map[0] || pool[1] != map[1] ||
        pool[0] < 0x80000000ULL || pool[0] > 0x100000000ULL - 0x1008000 || pool[1] != 0x1008000 ||
        (pool[0] & (PAGE - 1)) || buffer[0] != pool[0] + PAGE || buffer[1] != 0x1000000 ||
        overlap(pool[0], pool[1], p->phys, p->memory) || overlap(pool[0], pool[1], image, image_bytes) ||
        overlap(pool[0], pool[1], dtb, dtb_bytes) || overlap(pool[0], pool[1], q->rmtfs_pool, 0x288000)) return 0;
    unsigned bank = 0;
    for (unsigned i = 0; i < hw->banks; ++i)
        if (pool[0] >= hw->memory[i].base && pool[0] + pool[1] <= hw->memory[i].base + hw->memory[i].size) bank = 1;
    if (!bank) return 0;
    for (unsigned i = 0; i < hw->reservations; ++i)
        if (overlap(pool[0], pool[1], hw->reserved[i].base, hw->reserved[i].size)) return 0;
    q->wifi_dma_pool = pool[0]; q->wifi_dma_owned = owned;
    return 1;
}

static void wifi_dma_initialize(volatile uint64_t *pool)
{
    for (uint64_t i = 0; i < 0x1008000 / 8; ++i)
        pool[i] = i < PAGE / 8 || i >= (PAGE + 0x1000000) / 8 ? 0xd3d3d3d3d3d3d3d3ULL : 0;
}

/* SMP is a separate frozen md0 experiment. Merely asking cpus=2 cannot
 * bypass either compiled shim ownership or the unchanged UP validator. */
#if defined(SHIM_EARLY_RETURN) && SHIM_EARLY_RETURN == 1 && \
    defined(REDFIN_SMP_PROBE) && REDFIN_SMP_PROBE == 1
#define REDFIN_SMP_BUILD_READY 1
#else
#define REDFIN_SMP_BUILD_READY 0
#endif
#ifndef REDFIN_SMP_GUI
#define REDFIN_SMP_GUI 0
#endif
#if defined(SHIM_EARLY_RETURN) && SHIM_EARLY_RETURN == 1 && REDFIN_SMP_GUI == 1 && \
    defined(REDFIN_SMP_CPUS) && REDFIN_SMP_CPUS == 8 && \
    defined(REDFIN_SMP_PROBE) && REDFIN_SMP_PROBE == 0
#define REDFIN_GUI_BUILD_READY 1
#else
#define REDFIN_GUI_BUILD_READY 0
#endif
#ifndef REDFIN_SMP_CPUS
#define REDFIN_SMP_CPUS 2
#endif
#if REDFIN_SMP_CPUS == 8
#define REDFIN_SMP_CPU_TOKEN "cpus=8"
#else
#define REDFIN_SMP_CPU_TOKEN "cpus=2"
#endif

static int smp_token(const char *p, unsigned size, const char *s)
{
    unsigned i = 0;
    while (i < size && s[i] && p[i] == s[i]) i++;
    return i == size && !s[i];
}

static int smp_requested(const char command[608])
{
    unsigned off = 0;
    while (off < 608 && command[off]) {
        while (off < 608 && command[off] && (unsigned char)command[off] <= ' ') off++;
        unsigned first = off;
        while (off < 608 && command[off] && (unsigned char)command[off] > ' ') off++;
        unsigned size = off - first;
        if (size >= 9 && smp_token(command + first, 9, "redfinsmp") &&
            (size == 9 || command[first + 9] == '=')) return 1;
        if (size >= 9 && smp_token(command + first, 9, "redfingui") &&
            (size == 9 || command[first + 9] == '=')) return 1;
    }
    return 0;
}

static int smp_command(const char command[608])
{
    if (REDFIN_GUI_BUILD_READY && redfin_gui_profile(command, 608, NULL)) return 1;
    static const char required[][24] = {
        "debug=0xc", "serial=3", REDFIN_SMP_CPU_TOKEN, "keepsyms=1", "-noprogress", "rd=md0",
        "sweettouch=0", "sweetkeys=0", "sweetusb=0", "sweetcpufreq=0",
        "sweetbattery=0", "modem=0", "wifi=0", "gpu=0", "redfinsmp=1",
        "redfinshim=1", "redfinspmi=0", "redfinreturn=0"
    };
    if (!REDFIN_SMP_BUILD_READY || (REDFIN_SMP_CPUS != 2 && REDFIN_SMP_CPUS != 8)) return 0;
    unsigned off = 0, seen = 0, id_seen = 0;
    const unsigned count = sizeof(required) / sizeof(required[0]);
    while (off < 608 && command[off]) {
        if (command[off] == ' ') { off++; continue; }
        unsigned first = off;
        while (off < 608 && command[off] && command[off] != ' ') {
            if ((unsigned char)command[off] < 33 || (unsigned char)command[off] > 126) return 0;
            off++;
        }
        unsigned size = off - first, matched = 0;
        for (unsigned i = 0; i < count; i++) {
            if (smp_token(command + first, size, required[i])) {
                if (seen & (1U << i)) return 0;
                seen |= 1U << i; matched = 1; break;
            }
        }
        if (matched) continue;
        if (smp_token(command + first, size, "-enable_kprintf_spam")) {
            if (seen & (1U << count)) return 0;
            seen |= 1U << count; continue;
        }
        if (size != 31 || !smp_token(command + first, 15, "redfinbootid=0x") || id_seen) return 0;
        uint64_t id = 0;
        for (unsigned i = 15; i < 31; i++) {
            unsigned c = (unsigned char)command[first + i], digit;
            if (c >= '0' && c <= '9') digit = c - '0';
            else if (c >= 'a' && c <= 'f') digit = c - 'a' + 10;
            else return 0;
            id = (id << 4) | digit;
        }
        if (!id) return 0;
        id_seen = 1;
    }
    if (off == 608 || !id_seen || (seen & ((1U << count) - 1)) != (1U << count) - 1) return 0;
    /* No hidden second command after the terminator in the payload field. */
    while (off < 608) if (command[off++]) return 0;
    return 1;
}

static int smp_string(const volatile unsigned char *p, uint64_t size, const char *s)
{
    unsigned i = 0;
    while (s[i]) { if (i >= size || p[i] != (unsigned char)s[i]) return 0; i++; }
    return size == (uint64_t)i + 1 && !p[i];
}

static int smp_key(const volatile unsigned char *p, const char *s)
{
    unsigned i = 0;
    while (i < 32 && s[i]) { if (p[i] != (unsigned char)s[i]) return 0; i++; }
    if (i == 32) return 0;
    while (i < 32) if (p[i++]) return 0;
    return 1;
}

static int smp_key_well_formed(const volatile unsigned char *p)
{
    unsigned i = 0;
    if (!p[0]) return 0;
    while (i < 32 && p[i]) { if (p[i] < 33 || p[i] > 126) return 0; i++; }
    if (i == 32) return 0;
    while (i < 32) if (p[i++]) return 0;
    return 1;
}

/* GUI-only leaves. A GUI tree is never admitted by the md0 command profile. */
enum { RF_GUI_DISPLAY = 8, RF_GUI_TOUCH, RF_GUI_UFS, RF_GUI_FBCON, RF_GUI_POWER,
    RF_GUI_SENSOR, RF_GUI_CONTROLS };
static int gui_sensor_property(const volatile unsigned char *key,
    const volatile unsigned char *value,uint32_t len,unsigned *seen)
{
    unsigned bit=0;
    if(smp_key(key,"source-path")) {
        bit=1;if(!smp_string(value,len,"/redfin/firmware/native-sensors.bundle"))return 0;
    }else if(smp_key(key,"bundle-bytes")) {
        bit=2;if(len!=8||quad(value)<64||quad(value)>32u*1024u*1024u)return 0;
    }else if(smp_key(key,"bundle-sha256")) {
        bit=4;if(len!=32)return 0;unsigned nonzero=0;
        for(unsigned i=0;i<32;++i)nonzero|=value[i];
        if(!nonzero)return 0;
    }else if(smp_key(key,"live-fdt-verified")) {
        bit=8;if(len!=4||word(value,0)!=1)return 0;
    }else if(smp_key(key,"source-contract")) {
        static const uint32_t expected[10]={1,1,2,443,429,3,0,2,384,384};
        bit=16;if(len!=sizeof(expected))return 0;
        for(unsigned i=0;i<10;++i)if(word(value+4*i,0)!=expected[i])return 0;
    }else if(smp_key(key,"hardware-reg")) {
        static const uint64_t expected[8]={0x89200000,0x2800000,0x80900000,0x200000,0x1f40000,0x20000,0x408000,0x1000};
        bit=32;if(len!=sizeof(expected))return 0;
        for(unsigned i=0;i<8;++i)if(quad(value+8*i)!=expected[i])return 0;
    }else return 0;
    if(*seen&bit)return 0;
    *seen|=bit;return 1;
}
static int gui_power_property(const volatile unsigned char *key,
    const volatile unsigned char *value, unsigned len, unsigned *seen)
{
    unsigned bit;
    if (smp_key(key, "native-contract")) {
        /* The exact native PM7250B/TSENS26xx/standard OSM contract. */
        static const uint32_t contract[] = {1,2,0x4800,0xb100,0x3100,
            0x1000,0x1100,0x1200,0x1300,0x1400,0x1500,
            0x0c222000,0x0c263000,0x0c223000,0x0c265000,
            0x18323000,0x18325800,0x18327800};
        bit = 1;
        if (len != sizeof(contract)) return 0;
        for (unsigned j = 0; j < sizeof(contract)/sizeof(contract[0]); ++j)
            if (word(value + 4*j, 0) != contract[j]) return 0;
    } else if (smp_key(key, "rtc-anchor")) {
        bit = 2;
        if (len != 16) return 0;
        uint64_t counter = quad(value), offset = quad(value + 8);
        if (!counter || counter > UINT32_MAX || offset > UINT32_MAX ||
            counter + offset < 1577836800ULL || counter + offset >= 4102444800ULL) return 0;
    } else return 0;
    if (*seen & bit) return 0;
    *seen |= bit;
    return 1;
}
static int gui_property(unsigned kind, const volatile unsigned char *key,
    const volatile unsigned char *value, unsigned len, unsigned *seen)
{
    unsigned bit = 0;
    uint32_t expected = 0;
    if (kind == RF_GUI_DISPLAY || kind == RF_GUI_FBCON) {
        static const char keys[][24] = { "width", "height", "stride", "canvas-width",
            "canvas-height", "redfin,abl-copy-only", "AAPL,phandle" };
        uint32_t values[] = {1080, 2340, 4320, 1125, 2436, 1, 0x102};
        unsigned n = 0, count = kind == RF_GUI_FBCON ? 3 : 7;
        for (; n < count; n++) if (smp_key(key, keys[n])) break;
        if (n < count) { bit = 1U << n; expected = values[n]; goto scalar; }
        if (smp_key(key, kind == RF_GUI_FBCON ? "reg" : "redfin,framebuffer")) {
            bit = 1U << 7;
            if (len != 16 || quad(value) != 0xa0000000ULL || quad(value + 8) != 0x02300000ULL) return 0;
        } else if (kind == RF_GUI_DISPLAY && smp_key(key, "device_type")) {
            bit = 1U << 8; if (!smp_string(value, len, "display-subsystem")) return 0;
        } else if (kind == RF_GUI_DISPLAY && smp_key(key, "compatible")) {
            bit = 1U << 9; if (!smp_string(value, len, "sweet,display")) return 0;
        } else if (kind == RF_GUI_DISPLAY && smp_key(key, "pixel-format")) {
            bit = 1U << 10; if (!smp_string(value, len, "BGRA")) return 0;
        } else if (kind == RF_GUI_DISPLAY && smp_key(key, "redfin,panel-mode")) {
            static const uint32_t panel[] = {1,1080,2340,554000000,0x0af00000,
                0x0ae94000,0x0ae6b800,0x0f50a000,10,0x80152853,0x80153853};
            bit = 1U << 11;
            if (len != sizeof(panel)) return 0;
            for (unsigned j = 0; j < sizeof(panel)/sizeof(panel[0]); ++j)
                if (word(value + 4*j, 0) != panel[j]) return 0;
        } else if (kind == RF_GUI_DISPLAY && smp_key(key, "redfin,panel-controls")) {
            static const uint32_t controls[] = {1,0x0af00000,0x0ae94000,1080,2340,4,1023,8,500};
            bit = 1U << 12;
            if (len != sizeof(controls)) return 0;
            for (unsigned j = 0; j < sizeof(controls)/sizeof(controls[0]); ++j)
                if (word(value + 4*j, 0) != controls[j]) return 0;
        } else return 0;
    } else if (kind == RF_GUI_CONTROLS) {
        static const uint32_t keys[] = {1,0x0c440000,0x0c40a000,0x0e600000,0,0x008,0x4c4,0x0810,0xc410,15};
        if (!smp_key(key, "keys-contract") || len != sizeof(keys)) return 0;
        for (unsigned j = 0; j < sizeof(keys)/sizeof(keys[0]); ++j)
            if (word(value + 4*j, 0) != keys[j]) return 0;
        bit = 1;
    } else if (kind == RF_GUI_UFS) {
        if (!smp_key(key, "reg") || len != 16 || quad(value) != 0x01d84000ULL || quad(value + 8) != 0x3000) return 0;
        bit = 1;
    } else if (kind == RF_GUI_TOUCH) {
        if (smp_key(key, "compatible")) {
            bit = 1; if (!smp_string(value, len, "redfin,sec-touch")) return 0;
        } else if (smp_key(key, "reg")) {
            uint64_t values[] = {0x100000, 0x1f0000, 0x880000, 0x4000, 0xf000000, 0x1000000};
            bit = 2; if (len != sizeof(values)) return 0;
            for (unsigned i = 0; i < 6; i++) if (quad(value + 8 * i) != values[i]) return 0;
        } else if (smp_key(key, "spi-mode")) { bit = 4; expected = 3; goto scalar;
        } else if (smp_key(key, "chip-select")) { bit = 8; expected = 0; goto scalar;
        } else if (smp_key(key, "spi-max-frequency")) { bit = 16; expected = 10000000; goto scalar;
        } else if (smp_key(key, "touch-gpios")) {
            bit = 32; if (len != 12 || word(value, 0) != 8 || word(value + 4, 0) != 9 || word(value + 8, 0) != 35) return 0;
        } else if (smp_key(key, "touch-size")) {
            bit = 64; if (len != 8 || word(value, 0) != 1080 || word(value + 4, 0) != 2340) return 0;
        } else return 0;
    } else return 0;
    goto finish;
scalar:
    if (len != 4 || word(value, 0) != expected) return 0;
finish:
    if (*seen & bit) return 0;
    *seen |= bit; return 1;
}

static int adt_valid_smp_mode_sensors(const volatile unsigned char *b, uint64_t size, int gui,unsigned *sensor_present)
{
    enum { ROOT = 1, CHOSEN, CPUS, CPU, ARMIO, GIC, LEAF };
    static const char root_names[][24] = {
        "chosen", "cpus", "arm-io", "defaults", "product", "redfin-spmi",
        "redfin-return", "redfin-log", "redfin-watchdog", "pram",
        "redfin-touch", "redfin-ufs", "sweet-fbcon",
        "redfin-wifi", "redfin-wifi-native", "redfin-wifi-power", "redfin-wifi-start",
        "redfin-wifi-glink", "redfin-wifi-wlfw", "redfin-wifi-wlan", "redfin-wifi-snoc",
        "redfin-rmtfs", "redfin-wifi-dma", "redfin-wifi-assets", "redfin-wifi-fw",
        "redfin-gpu", "redfin-gpu-power", "redfin-gmu", "redfin-gpu-smmu", "redfin-gpu-command",
        "redfin-power", "redfin-sensors", "redfin-controls"
    };
    static const char cpu_u32[][24] = {
        "reg", "cpu-id", "cluster-id", "cluster-type", "die-cluster-id",
        "cluster-core-id", "l2-cache-id", "l3-cache-id", "l2-cache-size",
        "l3-cache-size", "timebase-frequency", "fixed-frequency"
    };
    static const unsigned char cpu_compatible[] = "qcom,kryo475\0qcom,kryo470\0ARM,v8";
    uint32_t pending[32], kinds[32], handles[8] = {0};
    unsigned depth = 0, cpus = 0, chosen_children = 0, arm_seen = 0;
    uint64_t root_seen = 0;
    unsigned display_controls = 0, wifi_identity_seen = 0;
    uint64_t off = 0;
    pending[0] = 1; kinds[0] = 0;
    for (;;) {
        while (!pending[depth]) {
            if (!depth) {
                if (REDFIN_SMP_CPUS != 2 && REDFIN_SMP_CPUS != 8) return 0;
                for (unsigned i = 0; i < REDFIN_SMP_CPUS; i++)
                    for (unsigned j = 0; j < i; j++) if (handles[i] == handles[j]) return 0;
                int valid=off == size && cpus == REDFIN_SMP_CPUS && (root_seen & 15) == 15 &&
                    (!gui || (gui == 3 ?
                        (root_seen & ((1U << 30) - 1)) == (1U << 30) - 1 :
                        root_seen == (1U << (gui == 2 ? 25 : 13)) - 1)) &&
                    arm_seen == (gui ? 3U : 1U) &&
                    (chosen_children & 1) && chosen_children <= 3 &&
                    (display_controls ? ((root_seen & (1ULL << 32)) && (root_seen & (1ULL << 30))) :
                        !(root_seen & (1ULL << 32)));
                if(valid&&sensor_present)*sensor_present=(unsigned)((root_seen>>31)&1);
                return valid;
            }
            depth--;
        }
        pending[depth]--;
        if (depth == 31 || off > size || size - off < 8) return 0;
        uint32_t props = word(b + off, 0), children = word(b + off + 4, 0);
        unsigned kind = 0, seen = 0, cpu = 8;
        off += 8;
        if (!props || props > 1024 || children > 1024) return 0;
        for (uint32_t i = 0; i < props; i++) {
            if (size - off < 36) return 0;
            const volatile unsigned char *key = b + off;
            uint32_t len = word(key + 32, 0);
            off += 36;
            uint64_t padded = ((uint64_t)len + 3) & ~3ULL;
            if ((len & 0x80000000U) || padded > size - off || !smp_key_well_formed(key)) return 0;
            const volatile unsigned char *value = b + off;
            if (!i) {
                if (!smp_key(key, "name")) return 0;
                if (!depth) {
                    if (!smp_string(value, len, "device-tree")) return 0;
                    kind = ROOT;
                } else if (depth == 1 && kinds[depth] == ROOT) {
                    unsigned n = 0;
                    unsigned count = gui == 3 ? 33 : gui == 2 ? 25 : gui ? 13 : 10;
                    for (; n < count; n++)
                        if (smp_string(value, len, root_names[n])) break;
                    if (n == count || (root_seen & (1ULL << n))) return 0;
                    root_seen |= 1ULL << n;
                    kind = n == 0 ? CHOSEN : n == 1 ? CPUS : n == 2 ? ARMIO : LEAF;
                    if (gui && n >= 10 && n < 13) kind = n == 10 ? RF_GUI_TOUCH : n == 11 ? RF_GUI_UFS : RF_GUI_FBCON;
                    if (gui == 3 && n == 30) kind = RF_GUI_POWER;
                    if (gui == 3 && n == 31) kind = RF_GUI_SENSOR;
                    if (gui == 3 && n == 32) kind = RF_GUI_CONTROLS;
                } else if (depth == 2 && kinds[depth] == CPUS) {
                    char name[5] = {'c', 'p', 'u', (char)('0' + cpus), 0};
                    if (cpus >= REDFIN_SMP_CPUS || !smp_string(value, len, name)) return 0;
                    cpu = cpus;
                    kind = CPU;
                } else if (depth == 2 && kinds[depth] == ARMIO && smp_string(value, len, "gic")) kind = GIC;
                else if (gui && depth == 2 && kinds[depth] == ARMIO && smp_string(value, len, "disp0")) kind = RF_GUI_DISPLAY;
                else if (depth == 2 && kinds[depth] == CHOSEN) {
                    unsigned bit;
                    if (smp_string(value, len, "memory-map")) bit = 1;
                    else if (smp_string(value, len, "asmb")) bit = 2;
                    else return 0;
                    if (chosen_children & bit) return 0;
                    chosen_children |= bit; kind = LEAF;
                } else return 0;
                if (kind == GIC || kind == RF_GUI_DISPLAY) {
                    unsigned bit = kind == GIC ? 1 : 2;
                    if (arm_seen & bit) return 0;
                    arm_seen |= bit;
                }
                if ((kind == CPUS && children != REDFIN_SMP_CPUS) || (kind == ARMIO && children != (gui ? 2U : 1U)) ||
                    (kind == CHOSEN && (children < 1 || children > 2)) ||
                    ((kind == CPU || kind == GIC || kind == LEAF || kind >= RF_GUI_DISPLAY) && children)) return 0;
            } else {
                if (smp_key(key, "name")) return 0;
                if (kind == RF_GUI_POWER) {
                    if (!gui_power_property(key, value, len, &seen)) return 0;
                } else if(kind==RF_GUI_SENSOR) {
                    if(!gui_sensor_property(key,value,len,&seen))return 0;
                } else if (kind >= RF_GUI_DISPLAY) {
                    if (!gui_property(kind, key, value, len, &seen)) return 0;
                } else if (kind == CPU) {
                    unsigned n = 0;
                    uint32_t physical = REDFIN_SMP_CPUS == 8 ? cpu << 8 : (cpu ? 0x600U : 0U);
                    uint32_t values[] = { physical, cpu, 0, 0, 0, cpu, cpu, 0, 0, 0, 19200000, 19200000 };
                    for (; n < sizeof(cpu_u32) / sizeof(cpu_u32[0]); n++)
                        if (smp_key(key, cpu_u32[n])) break;
                    if (n < sizeof(cpu_u32) / sizeof(cpu_u32[0])) {
                        if (len != 4 || word(value, 0) != values[n]) return 0;
                    } else if (smp_key(key, "device_type")) {
                        n = 12; if (!smp_string(value, len, "cpu")) return 0;
                    } else if (smp_key(key, "compatible")) {
                        n = 13;
                        if (len != sizeof(cpu_compatible)) return 0;
                        for (unsigned j = 0; j < len; j++) if (value[j] != cpu_compatible[j]) return 0;
                    } else if (smp_key(key, "state")) {
                        n = 14; if (!smp_string(value, len, cpu ? "stopped" : "running")) return 0;
                    } else if (smp_key(key, "AAPL,phandle")) {
                        n = 15; if (len != 4 || !word(value, 0)) return 0;
                        handles[cpu] = word(value, 0);
                    } else return 0;
                    if (seen & (1U << n)) return 0;
                    seen |= 1U << n;
                } else if (kind == CPUS) {
                    unsigned bit, expected;
                    if (smp_key(key, "#address-cells")) { bit = 1; expected = 1; }
                    else if (smp_key(key, "#size-cells")) { bit = 2; expected = 0; }
                    else if (smp_key(key, "AAPL,phandle")) { bit = 4; if (len != 4) return 0; expected = word(value, 0); if (!expected) return 0; }
                    else return 0;
                    if (len != 4 || word(value, 0) != expected || (seen & bit)) return 0;
                    seen |= bit;
                } else if(kind==CHOSEN&&smp_key(key,RF_WIFI_IDENTITY_PROPERTY)) {
                    if(gui!=3||wifi_identity_seen++||!rf_wifi_identity_decode(value,len,0))return 0;
                } else if (kind == CHOSEN && (smp_key(key, "dram-base") || smp_key(key, "dram-size"))) {
                    unsigned bit = smp_key(key, "dram-base") ? 1 : 2;
                    if (len != 8 || quad(value) != (bit == 1 ? 0x180000000ULL : 0x80000000ULL) || (seen & bit)) return 0;
                    seen |= bit;
                }
            }
            off += padded;
        }
        if ((kind == CPU && seen != 0xffff) || (kind == CPUS && seen != 7) || (kind == CHOSEN && seen != 3)) return 0;
        if ((kind == RF_GUI_DISPLAY && seen != 0x7ff &&
                !(gui == 3 && (seen == 0xfff || seen == 0x17ff || seen == 0x1fff))) || (kind == RF_GUI_TOUCH && seen != 127) ||
            (kind == RF_GUI_UFS && seen != 1) || (kind == RF_GUI_FBCON && seen != 0x87)) return 0;
        if (kind == RF_GUI_POWER && seen != 1 && seen != 3) return 0;
        if(kind==RF_GUI_SENSOR&&seen!=63)return 0;
        if(kind==RF_GUI_CONTROLS&&seen!=1)return 0;
        if(kind==RF_GUI_DISPLAY)display_controls=(seen>>12)&1;
        if (kind == CPU) cpus++;
        depth++; pending[depth] = children; kinds[depth] = kind;
    }
}
static int adt_valid_smp_mode(const volatile unsigned char *b,uint64_t size,int gui)
{return adt_valid_smp_mode_sensors(b,size,gui,NULL);}

static int adt_valid_smp(const volatile unsigned char *b, uint64_t size)
{ return adt_valid_smp_mode(b, size, 0); }

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
    int smp = smp_requested(p->command);
    if (smp && (!smp_command(p->command) || mpidr || p->phys != 0x180000000ULL ||
        p->memory != 0x80000000ULL)) return "SMP command or RAM profile";
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
    const volatile unsigned char *tree = (const volatile unsigned char *)data + p->adt_offset;
    int gui = REDFIN_GUI_BUILD_READY && redfin_gui_profile(p->command, sizeof(p->command), NULL);
    int wifi_gui = gui && redfin_wifi_gui_profile(p->command, sizeof(p->command), NULL);
    int gpu_gui = gui && redfin_gpu_gui_profile(p->command, sizeof(p->command), NULL);
    unsigned sensors=0;
    if (!(smp ? (gui ? adt_valid_smp_mode_sensors(tree, p->adt_size, gpu_gui ? 3 : wifi_gui ? 2 : 1,&sensors) : adt_valid_smp(tree, p->adt_size)) :
        adt_valid_up(tree, p->adt_size, mpidr, p->phys, p->memory))) return "ADT CPU or RAM mismatch";
    if(sensors) {
        unsigned found=0,in_ram=0;
        for(unsigned i=0;i<hw->banks;++i)if(hw->memory[i].base<=0x89200000ULL&&
            hw->memory[i].base+hw->memory[i].size>=0x8ba00000ULL)in_ram++;
        for(unsigned i=0;i<hw->reservations;++i) {
            struct region r=hw->reserved[i];
            if(r.base==0x89200000ULL&&r.size==0x2800000ULL)found++;
            else if(overlap(r.base,r.size,0x89200000ULL,0x2800000ULL))return "ADSP reservation alias";
        }
        if(found!=1||in_ram!=1||overlap(0x89200000ULL,0x2800000ULL,image,image_end-image)||
            overlap(0x89200000ULL,0x2800000ULL,dtb,dtb_size))return "ADSP native reservation/source overlap";
    }
    if (!rmtfs_plan(p, hw, image, image_end - image, dtb, dtb_size, q)) return "RMTFS RAM ownership";
    if (!wifi_dma_plan(p, hw, image, image_end - image, dtb, dtb_size, q)) return "WLAN DMA RAM ownership";
    return NULL;
}

#ifdef REDFIN_LOADER_TEST
const char *redfin_validate(const void *data, uint64_t size, uint64_t image,
    uint64_t image_end, uint64_t dtb, const struct hardware *hw, uint64_t mpidr)
{ struct plan q; return validate(data, size, image, image_end, dtb, hw, mpidr, &q); }
void redfin_wifi_dma_initialize(void *pool) { wifi_dma_initialize((volatile uint64_t *)pool); }
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
    if (q.rmtfs_pool) {
        volatile uint64_t *pool = (void *)(uintptr_t)q.rmtfs_pool;
        for (uint64_t i = 0; i < 0x288000 / 8; ++i)
            pool[i] = i < PAGE / 8 || i >= (PAGE + 0x280000) / 8 ? 0xa7a7a7a7a7a7a7a7ULL : 0;
    }
    if (q.wifi_dma_pool) wifi_dma_initialize((volatile uint64_t *)(uintptr_t)q.wifi_dma_pool);
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
    if (q.rmtfs_pool) *(volatile uint32_t *)(tree + q.rmtfs_owned) = 1;
    if (q.wlfw_verified) *(volatile uint32_t *)(tree + q.wlfw_verified) = 1;
    if (q.wifi_dma_pool) *(volatile uint32_t *)(tree + q.wifi_dma_owned) = 1;
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
