/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_IDLE_SYSTEM_H
#define REDFIN_IDLE_SYSTEM_H
#include <stdbool.h>
#include <stdint.h>
bool redfin_idle_system_begin(uint64_t nonce);
bool redfin_idle_system_end(void);
#endif
