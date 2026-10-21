#include "fdt.h"
#include <stddef.h>

static uint32_t be32(const unsigned char *p)
{
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 |
           (uint32_t)p[2] << 8 | p[3];
}

static int equal(const unsigned char *p, size_t n, const char *s)
{
    size_t i = 0;
    while (i < n && s[i] && p[i] == (unsigned char)s[i]) i++;
    return i < n && !p[i] && !s[i];
}

static int compatible(const unsigned char *p, size_t n, const char *s)
{
    for (size_t i = 0; i < n;) {
        if (equal(p + i, n - i, s)) return 1;
        while (i < n && p[i]) i++;
        i++;
    }
    return 0;
}

static uint64_t cells(const unsigned char *p, unsigned count)
{
    uint64_t n = 0;
    for (unsigned i = 0; i < count; i++) n = n << 32 | be32(p + 4 * i);
    return n;
}

int redfin_fdt(const void *blob, struct hardware *hw)
{
    const unsigned char *b = blob;
    /* Do not let a freestanding compiler introduce a libc memset call. */
    for (size_t i = 0; i < sizeof(*hw); i++) ((volatile unsigned char *)hw)[i] = 0;
    if (!b || be32(b) != 0xd00dfeed) return -1;
    uint32_t total = be32(b + 4), so = be32(b + 8), no = be32(b + 12);
    uint32_t ns = be32(b + 32), ss = be32(b + 36);
    if (total < 40 || total > 2 * 1024 * 1024 || so < 40 || no < 40 ||
        so > total || ss > total - so || no > total || ns > total - no ||
        (so & 3) || be32(b + 20) < 17 || be32(b + 24) > 17) return -1;
    uint32_t ro = be32(b + 16);
    if (ro < 40 || ro > total || (ro & 7)) return -1;
    for (;;) {
        if (total - ro < 16) return -1;
        struct region r = {cells(b + ro, 2), cells(b + ro + 8, 2)};
        ro += 16;
        if (!r.base && !r.size) break;
        if (!r.size || r.size > UINT64_MAX - r.base || hw->reservations == MAX_RESERVED) return -1;
        hw->reserved[hw->reservations++] = r;
    }
    const unsigned char *p = b + so, *end = p + ss;
    unsigned ac = 2, sc = 2, rac = 2, rsc = 2;
    const unsigned char *watchdog_reg[33];
    uint32_t watchdog_len[33];
    unsigned char watchdog_compatible[33];
    int depth = 0, reserved = 0, memory = 0, splash = 0, psci = 0, method_smc = 0;
    while (end - p >= 4) {
        uint32_t token = be32(p); p += 4;
        if (token == 1) {
            const unsigned char *name = p;
            while (p < end && *p) p++;
            if (p == end || ++depth > 32) return -1;
            watchdog_reg[depth] = 0;
            watchdog_len[depth] = 0;
            watchdog_compatible[depth] = 0;
            size_t len = (size_t)(p - name) + 1;
            if (depth == 2) {
                memory = equal(name, len, "memory") || (len > 7 &&
                    name[0]=='m' && name[1]=='e' && name[2]=='m' &&
                    name[3]=='o' && name[4]=='r' && name[5]=='y' && name[6]=='@');
                reserved = equal(name, len, "reserved-memory");
                rac = ac; rsc = sc;
            }
            if (depth == 3 && reserved)
                splash = equal(name, len, "cont_splash_region");
            size_t skip = (len + 3) & ~(size_t)3;
            if (skip > (size_t)(end - name)) return -1;
            p = name + skip;
        } else if (token == 2) {
            if (depth <= 0) return -1;
            if (watchdog_compatible[depth]) {
                unsigned count = watchdog_len[depth] == 8 ? 1 : 2;
                if (!watchdog_reg[depth] || (watchdog_len[depth] != 8 &&
                    watchdog_len[depth] != 16) || hw->watchdog.size) return -1;
                hw->watchdog.base = cells(watchdog_reg[depth], count);
                hw->watchdog.size = cells(watchdog_reg[depth] + count * 4, count);
                if (!hw->watchdog.size || hw->watchdog.size >
                    UINT64_MAX - hw->watchdog.base) return -1;
            }
            if (depth == 3) splash = 0;
            if (depth == 2) {
                if (psci && method_smc) hw->psci_smc = 1;
                memory = reserved = psci = method_smc = 0;
            }
            depth--;
        } else if (token == 3) {
            if (end - p < 8 || !depth) return -1;
            uint32_t len = be32(p), off = be32(p + 4); p += 8;
            if (len > (size_t)(end - p) || off >= ns) return -1;
            const unsigned char *name = b + no + off;
            size_t name_len = 0;
            while (name_len < ns - off && name[name_len]) name_len++;
            if (name_len == ns - off) return -1;
            name_len++;
            if (equal(name, name_len, "compatible"))
                watchdog_compatible[depth] = compatible(p, len, "qcom,msm-watchdog");
            if (equal(name, name_len, "reg")) {
                watchdog_reg[depth] = p;
                watchdog_len[depth] = len;
            }
            if (depth == 1 && equal(name, name_len, "compatible"))
                hw->redfin = compatible(p, len, "google,redfin") ||
                    compatible(p, len, "google,redfin-sm7250");
            if (len == 4 && (depth == 1 || (depth == 2 && reserved))) {
                unsigned *a = depth == 1 ? &ac : &rac;
                unsigned *s = depth == 1 ? &sc : &rsc;
                if (equal(name, name_len, "#address-cells")) *a = be32(p);
                if (equal(name, name_len, "#size-cells")) *s = be32(p);
            }
            if (depth == 2 && equal(name, name_len, "compatible") &&
                (compatible(p, len, "arm,psci-1.0") || compatible(p, len, "arm,psci-0.2"))) psci = 1;
            if (depth == 2 && equal(name, name_len, "method"))
                method_smc = equal(p, len, "smc");
            if (depth == 2 && reserved && equal(name, name_len, "ranges") && len) return -1;
            int fixed_reservation = depth == 3 && reserved;
            if (equal(name, name_len, "reg") && ((depth == 2 && memory) || fixed_reservation)) {
                unsigned a = fixed_reservation ? rac : ac, s = fixed_reservation ? rsc : sc;
                if (!a || a > 2 || !s || s > 2 || len % (4 * (a + s))) return -1;
                for (unsigned i = 0; i < len; i += 4 * (a + s)) {
                    struct region r = {cells(p + i, a), cells(p + i + 4 * a, s)};
                    if (!r.size || r.size > UINT64_MAX - r.base) return -1;
                    if (fixed_reservation) {
                        if (splash) hw->splash = r;
                        if (hw->reservations == MAX_RESERVED) return -1;
                        hw->reserved[hw->reservations++] = r;
                    } else {
                        if (hw->banks == MAX_BANKS) return -1;
                        hw->memory[hw->banks++] = r;
                    }
                }
            }
            size_t skip = ((size_t)len + 3) & ~(size_t)3;
            if (skip > (size_t)(end - p)) return -1;
            p += skip;
        } else if (token == 9) return depth ? -1 : 0;
        else if (token != 4) return -1;
    }
    return -1;
}
