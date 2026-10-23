/* SPDX-License-Identifier: MIT
 * Optional md0-only prerequisite observer. redfinwifipower=1 selects a separate
 * native retained ARC/AOP lease. Neither path starts MPSS or writes media.
 */
#ifndef REDFIN_WIFI_NATIVE_PROBE_H
#define REDFIN_WIFI_NATIVE_PROBE_H
#include "gui-profile.h"
#ifdef __cplusplus
extern "C" {
#endif
void redfin_wifi_native_observe(void);
#ifdef __cplusplus
}
#endif
#endif
