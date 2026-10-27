/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_BRIGHTNESS_SYSTEM_H
#define REDFIN_BRIGHTNESS_SYSTEM_H
#include <stdbool.h>
/* Native system brightness transaction, without UIKit's application scene. */
bool redfin_brightness_system_ready(void);
float redfin_brightness_system_get(void);
bool redfin_brightness_system_set(float value);
#endif
