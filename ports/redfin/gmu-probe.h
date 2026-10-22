/* SPDX-License-Identifier: MIT */
/* Synchronous Redfin reset-held GMU probe; no standalone power authority. */
#ifndef REDFIN_GMU_PROBE_H
#define REDFIN_GMU_PROBE_H

#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

typedef bool (*redfin_gmu_parent_valid_fn)(void *);

/* bytes includes the NUL; every word and the nonzero boot nonce is unique. */
static inline bool
redfin_gmu_args_valid(const char *args, unsigned bytes)
{
    static const char *const required[] = {
        "debug=0xc", "serial=3", "cpus=1", "keepsyms=1", "-noprogress", "rd=md0",
        "sweettouch=0", "sweetkeys=0", "sweetusb=0", "sweetcpufreq=0", "sweetbattery=0",
        "modem=0", "wifi=0", "gpu=0", "redfingpu=2", "redfingpupower=1",
        "redfinrpmh=1", "redfinspmi=1", "redfinreturn=1", "redfingmu=1"
    };
    uint32_t seen = 0;
    bool nonce_seen = false, trace_seen = false;
    unsigned at = 0;
    if (!args || !bytes || bytes > 608 || args[bytes - 1])
        return false;
    while (at < bytes - 1) {
        unsigned first, n, i;
        bool known = false;
        if (args[at] == ' ') { at++; continue; }
        first = at;
        while (at < bytes - 1 && args[at] != ' ') {
            if ((unsigned char)args[at] < 33 || (unsigned char)args[at] > 126)
                return false;
            at++;
        }
        n = at - first;
        for (i = 0; i < sizeof(required) / sizeof(required[0]); i++) {
            unsigned length = 0;
            while (required[i][length]) length++;
            if (length != n) continue;
            unsigned j;
            for (j = 0; j < n && args[first + j] == required[i][j]; j++) {}
            if (j != n) continue;
            if (seen & (1u << i)) return false;
            seen |= 1u << i;
            known = true;
            break;
        }
        if (known) continue;
        static const char trace[] = "-enable_kprintf_spam";
        if (n == sizeof(trace) - 1) {
            for (i = 0; i < n && args[first + i] == trace[i]; i++) {}
            if (i == n) {
                if (trace_seen) return false;
                trace_seen = true;
                continue;
            }
        }
        static const char prefix[] = "redfinbootid=0x";
        if (n == 31) {
            for (i = 0; i < sizeof(prefix) - 1 && args[first + i] == prefix[i]; i++) {}
            if (i == sizeof(prefix) - 1) {
                uint64_t nonce = 0;
                if (nonce_seen) return false;
                for (; i < n; i++) {
                    unsigned digit = (unsigned)(args[first + i] - '0');
                    if (digit > 9) {
                        if (args[first + i] < 'a' || args[first + i] > 'f') return false;
                        digit = (unsigned)(args[first + i] - 'a' + 10);
                    }
                    nonce = (nonce << 4) | digit;
                }
                if (!nonce) return false;
                nonce_seen = true;
                continue;
            }
        }
        return false;
    }
    return seen == (1u << (sizeof(required) / sizeof(required[0]))) - 1 && nonce_seen;
}

#ifdef __cplusplus
extern "C" {
#endif

/* Read-only DT/argument validation, safe before the parent's first power write. */
int redfin_gmu_probe_contract(const char *frozen_args, unsigned args_bytes);

/*
 * Call only after successful RF_GP_OK/parent_held/cx_on in the same exact mode.
 * The parent's callback must revalidate that owned result and its original
 * frozen argument/context lifetime. No callback or argument is retained after
 * this synchronous function returns. It never releases the parent's ARC vote.
 */
int redfin_gmu_probe(const char *frozen_args, unsigned args_bytes,
    void *held_cx_context, redfin_gmu_parent_valid_fn held_cx_valid);

#ifdef __cplusplus
}
#endif

#endif /* REDFIN_GMU_PROBE_H */
