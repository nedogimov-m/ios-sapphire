/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_DISPLAY_CONTENT_H
#define REDFIN_DISPLAY_CONTENT_H
#include <stdint.h>
#ifdef __OBJC__
@class UIWindow,CALayer;
UIWindow *redfin_display_content_window(UIWindow *fallback);
CALayer *redfin_display_content_layer(UIWindow *window);
uint32_t redfin_display_content_context(UIWindow *window,CALayer *layer);
void redfin_display_content_trace(uint64_t nonce,void (*output)(uint64_t,const char *,...));
#endif
#endif
