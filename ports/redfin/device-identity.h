/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_DEVICE_IDENTITY_H
#define REDFIN_DEVICE_IDENTITY_H
#include <stddef.h>
#include <stdbool.h>

/* Boot ADT bytes include exactly one final NUL. Never print the identifier. */
static inline bool redfin_device_serial(const void *data, size_t bytes)
{
    if (!data || bytes < 7 || bytes > 65) return false;
    const unsigned char *s = (const unsigned char *)data;
    if (s[bytes - 1]) return false;
    for (size_t i = 0; i + 1 < bytes; ++i)
        if (!((s[i] >= '0' && s[i] <= '9') || (s[i] >= 'A' && s[i] <= 'Z') ||
              (s[i] >= 'a' && s[i] <= 'z') || s[i] == '-' || s[i] == '_')) return false;
    return true;
}
#endif
