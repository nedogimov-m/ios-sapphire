/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_STATUSBAR_GEOMETRY_H
#define REDFIN_STATUSBAR_GEOMETRY_H
#include <stdbool.h>
#include <math.h>

struct redfin_ui_rect { double x,y,w,h; };
static inline bool redfin_ui_rect_valid(struct redfin_ui_rect r)
{
    return isfinite(r.x) && isfinite(r.y) && isfinite(r.w) && isfinite(r.h) &&
        r.w>0 && r.h>0 && fabs(r.x)<32768 && fabs(r.y)<32768 && r.w<32768 && r.h<32768;
}
static inline bool redfin_ui_intersects(struct redfin_ui_rect a,struct redfin_ui_rect b)
{
    return a.x < b.x+b.w && b.x < a.x+a.w && a.y < b.y+b.h && b.y < a.y+a.h;
}
/* Coordinates are supplied by native fixed-screen/window conversions, so
 * this also works when the physical camera lies at the right in landscape.
 * No whole-canvas crop, safe-area change or touch transform is introduced. */
static inline bool redfin_ui_time_shift(struct redfin_ui_rect time,
    struct redfin_ui_rect camera,struct redfin_ui_rect window,double *shift)
{
    if (!shift || !redfin_ui_rect_valid(time) || !redfin_ui_rect_valid(camera) ||
        !redfin_ui_rect_valid(window)) return false;
    *shift=0;
    if (!redfin_ui_intersects(time,camera)) return true;
    double right=camera.x+camera.w+3-time.x;
    double left=camera.x-3-(time.x+time.w);
    bool fits_right=time.x+right>=window.x && time.x+right+time.w<=window.x+window.w;
    bool fits_left=time.x+left>=window.x && time.x+left+time.w<=window.x+window.w;
    if (!fits_right && !fits_left) return false;
    *shift=fits_right && (!fits_left || fabs(right)<=fabs(left)) ? right : left;
    struct redfin_ui_rect after=time; after.x+=*shift;
    return !redfin_ui_intersects(after,camera);
}
#endif
