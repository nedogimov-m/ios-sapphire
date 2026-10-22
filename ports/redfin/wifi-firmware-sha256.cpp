/* SPDX-License-Identifier: MIT
 * Kernel digest adapter for redfin_wifi_firmware.h. No startup hook or I/O.
 * SWEET's SHA256 uses ccsha256_ltc_di directly; no corecrypto kext is needed.
 */
#include "redfin_wifi_firmware.h"
#include <libkern/crypto/sha2.h>

extern "C" int
redfin_mpss_kernel_sha256(void *context, const uint8_t *data, size_t bytes,
    uint8_t digest[32])
{
    (void)context;
    if (!data || !digest || !bytes || bytes > REDFIN_MPSS_MAX_BUNDLE) return -1;
    SHA256_CTX state;
    SHA256_Init(&state);
    SHA256_Update(&state, data, bytes);
    SHA256_Final(digest, &state);
    return 0;
}
