/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_DISPLAY_CONTENT_H
#define REDFIN_DISPLAY_CONTENT_H
#include <stdint.h>
#include <stdbool.h>
struct redfin_content_state {uint32_t context,display,commit;};
#ifdef __OBJC__
@class UIWindow,CALayer;
UIWindow *redfin_display_content_window(UIWindow *fallback);
CALayer *redfin_display_content_layer(UIWindow *window);
uint32_t redfin_display_content_context(UIWindow *window,CALayer *layer);
bool redfin_display_content_snapshot(UIWindow *window,CALayer *layer,struct redfin_content_state *state);
void redfin_display_content_trace(uint64_t nonce,void (*output)(uint64_t,const char *,...));
#endif
#endif
