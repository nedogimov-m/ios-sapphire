/* SPDX-License-Identifier: MIT */
/* Explicit native policy: a live GEM handle retains its descriptor until
 * close/real retirement. This grants no CPU access, completion or cache proof. */
#ifndef REDFIN_RETAINED_MEMORY_H
#define REDFIN_RETAINED_MEMORY_H
#include <stdint.h>
#define RF_GM_PARAM UINT32_C(0x52464d31)
#define RF_GM_ABI 1u
enum {RF_GM_CAPABILITY,RF_GM_QUERIES,RF_GM_FAST,RF_GM_FALLBACK,RF_GM_WORDS};
#endif
