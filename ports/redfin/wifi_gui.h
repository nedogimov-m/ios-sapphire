/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_WIFI_GUI_H
#define REDFIN_WIFI_GUI_H
#include <stdbool.h>
#ifdef __cplusplus
extern "C" {
#endif
bool redfin_wifi_gui_requested(void);
bool redfin_wifi_gui_ready(void);
bool redfin_wifi_return_held(void);
void redfin_wifi_gui_start(void);
#ifdef __cplusplus
}
#endif
#endif
