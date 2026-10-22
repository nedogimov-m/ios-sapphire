/*
 * Redfin CPU presentation and inverse digitizer geometry. No display/HID ABI
 * change: Apple's iPhone X canvas remains 1125x2436.
 *
 * Scaling policy reviewed against oosexgang/hackios-xnu-kernel commit
 * 8e61187098f2c26c5daee8f9f72b6416aa64b9ab, MiniIOMobileFramebuffer.cpp
 * drawLayer/drawRows/sample_at. This implementation checks the existing
 * SweetSurface allocation instead of importing that driver's private ABI.
 *
 * Camera exclusion: Google's device/google/redfin commit
 * 62df7438508565dfc05fab923e84f0704f5a0f07, redfin/overlay/frameworks/base/
 * core/res/res/values/config.xml:209-225 (Apache-2.0 resource). The conservative
 * Android cutout rectangle is [0,145)x[0,136), enclosing the radius-40 circle
 * centered at (81,77). Mode 2 excludes its complete top 136 rows.
 */
#ifndef REDFIN_DISPLAY_GEOMETRY_H
#define REDFIN_DISPLAY_GEOMETRY_H
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#define REDFIN_DISPLAY_MAX_SOURCE 16384u
#define REDFIN_DISPLAY_BGRA 0x42475241u
#define REDFIN_DISPLAY_TOP_EXCLUSION 136u

struct redfin_display_geometry {
	uint32_t mode, panel_w, panel_h, logical_w, logical_h;
	uint32_t x, y, w, h;
};

/* Heap-owned AppleCLCD member, never a 70-KiB kernel stack allocation. */
struct redfin_display_workspace {
	uint32_t column[1080];
	uint16_t weight[1080];
	uint32_t row[REDFIN_DISPLAY_MAX_SOURCE];
};

struct redfin_display_surface {
	const uint8_t *pixels;
	uint64_t length, offset;
	uint32_t width, height, stride, format;
};

static inline bool
redfin_display_geometry_make(uint32_t mode, uint32_t pw, uint32_t ph,
    uint32_t cw, uint32_t ch, struct redfin_display_geometry *out)
{
	if (!out || (mode != 1 && mode != 2) || pw != 1080 || ph != 2340 ||
	    cw != 1125 || ch != 2436) return false;
	uint32_t top = mode == 2 ? REDFIN_DISPLAY_TOP_EXCLUSION : 0;
	uint32_t aw = pw, ah = ph - top, w, h;
	if ((uint64_t)aw * ch <= (uint64_t)ah * cw) {
		w = aw; h = (uint32_t)((uint64_t)aw * ch / cw);
	} else {
		h = ah; w = (uint32_t)((uint64_t)ah * cw / ch);
	}
	out->mode = mode; out->panel_w = pw; out->panel_h = ph;
	out->logical_w = cw; out->logical_h = ch;
	out->x = (aw - w) / 2; out->y = top + (ah - h) / 2;
	out->w = w; out->h = h;
	return true;
}

static inline bool
redfin_display_geometry_valid(const struct redfin_display_geometry *g)
{
	struct redfin_display_geometry expected;
	return g && redfin_display_geometry_make(g->mode, g->panel_w, g->panel_h,
	    g->logical_w, g->logical_h, &expected) && g->x == expected.x &&
	    g->y == expected.y && g->w == expected.w && g->h == expected.h;
}

static inline bool
redfin_display_target_valid(const struct redfin_display_geometry *g,
    const uint8_t *pixels, uint64_t length, uint32_t stride)
{
	uint64_t bytes = (uint64_t)4320 * 2340;
	return redfin_display_geometry_valid(g) && pixels &&
	    !((uintptr_t)pixels & 3) && stride == 4320 && length >= bytes &&
	    (uintptr_t)pixels <= UINTPTR_MAX - bytes;
}

static inline bool
redfin_display_surface_valid(const struct redfin_display_surface *s)
{
	if (!s || !s->pixels || ((uintptr_t)s->pixels & 3) ||
	    s->format != REDFIN_DISPLAY_BGRA || !s->width || !s->height ||
	    s->width > REDFIN_DISPLAY_MAX_SOURCE || s->height > REDFIN_DISPLAY_MAX_SOURCE ||
	    (s->stride & 3) || s->stride < (uint64_t)s->width * 4 ||
	    (s->offset & 3) || s->offset > s->length) return false;
	uint64_t extent = (uint64_t)(s->height - 1) * s->stride + (uint64_t)s->width * 4;
	return extent <= SIZE_MAX && extent <= s->length - s->offset && s->offset <= SIZE_MAX - extent &&
	    (uintptr_t)s->pixels <= UINTPTR_MAX - (s->offset + extent);
}

/* Paint only margins; source surfaces and the content viewport are untouched. */
static inline bool
redfin_display_clear_margins(const struct redfin_display_geometry *g,
    uint8_t *pixels, uint64_t length, uint32_t stride)
{
	if (!redfin_display_target_valid(g, pixels, length, stride)) return false;
	for (uint32_t y = 0; y < g->panel_h; y++) {
		uint32_t *row = (uint32_t *)(pixels + (uint64_t)y * stride);
		if (y < g->y || y >= g->y + g->h) {
			for (uint32_t x = 0; x < g->panel_w; x++) row[x] = 0xff000000u;
		} else {
			for (uint32_t x = 0; x < g->x; x++) row[x] = 0xff000000u;
			for (uint32_t x = g->x + g->w; x < g->panel_w; x++) row[x] = 0xff000000u;
		}
	}
	return true;
}

/* Signed floor keeps adjacent destination rectangles on the same pixel grid. */
static inline int64_t
redfin_display_project(int64_t coordinate, uint32_t panel, uint32_t logical)
{
	int64_t product = coordinate * panel;
	return product >= 0 ? product / logical : -((-product + logical - 1) / logical);
}

static inline uint32_t
redfin_display_sample(uint64_t pixel, uint32_t source, uint64_t destination)
{
	/* Planner bounds destination to differences of projected int32 rectangles,
	 * and source to 16384, so the signed numerator cannot overflow. */
	int64_t at = ((int64_t)(2 * pixel + 1) * source - (int64_t)destination) * 128 /
	    (int64_t)destination;
	int64_t last = (int64_t)(source - 1) * 256;
	return (uint32_t)(at < 0 ? 0 : at > last ? last : at);
}

static inline uint32_t
redfin_display_blend(uint32_t first, uint32_t second, uint32_t weight)
{
	uint32_t low = (((first & 0x00ff00ffu) * (256 - weight) +
	    (second & 0x00ff00ffu) * weight) >> 8) & 0x00ff00ffu;
	uint32_t high = ((((first >> 8) & 0x00ff00ffu) * (256 - weight) +
	    ((second >> 8) & 0x00ff00ffu) * weight) & 0xff00ff00u);
	return low | high;
}

/* No allocation, source mutation, hardware access, or unchecked pixel read.
 * The caller serializes presentation and owns the heap-resident workspace.
 * source/destination rectangles use the existing swap-record ABI. */
static inline bool
redfin_display_draw(const struct redfin_display_geometry *g,
    struct redfin_display_workspace *work, uint8_t *pixels, uint64_t length,
    uint32_t stride, const struct redfin_display_surface *s,
    const int32_t source[4], const int32_t destination[4], uint64_t *copied)
{
	if (copied) *copied = 0;
	if (!work || !source || !destination ||
	    !redfin_display_target_valid(g, pixels, length, stride) ||
	    !redfin_display_surface_valid(s)) return false;
	int64_t sx = source[0], sy = source[1], sw = source[2], sh = source[3];
	int64_t dx = destination[0], dy = destination[1];
	int64_t dw = destination[2], dh = destination[3];
	if (sw <= 0 || sh <= 0) { sx = sy = 0; sw = s->width; sh = s->height; }
	if (dw <= 0 || dh <= 0) { dx = dy = 0; dw = g->logical_w; dh = g->logical_h; }
	if (sx < 0 || sy < 0 || sx + sw > s->width || sy + sh > s->height) return false;
	int64_t px0 = g->x + redfin_display_project(dx, g->w, g->logical_w);
	int64_t py0 = g->y + redfin_display_project(dy, g->h, g->logical_h);
	int64_t px1 = g->x + redfin_display_project(dx + dw, g->w, g->logical_w);
	int64_t py1 = g->y + redfin_display_project(dy + dh, g->h, g->logical_h);
	int64_t x0 = px0 < g->x ? g->x : px0;
	int64_t y0 = py0 < g->y ? g->y : py0;
	int64_t x1 = px1 > g->x + g->w ? g->x + g->w : px1;
	int64_t y1 = py1 > g->y + g->h ? g->y + g->h : py1;
	if (px1 <= px0 || py1 <= py0 || x1 <= x0 || y1 <= y0) return false;
	for (int64_t x = x0; x < x1; x++) {
		uint32_t at = redfin_display_sample((uint64_t)(x - px0), (uint32_t)sw,
		    (uint64_t)(px1 - px0));
		work->column[x] = at >> 8;
		work->weight[x] = work->column[x] + 1 < (uint32_t)sw ? (uint16_t)(at & 255) : 0;
	}
	for (int64_t y = y0; y < y1; y++) {
		uint32_t at = redfin_display_sample((uint64_t)(y - py0), (uint32_t)sh,
		    (uint64_t)(py1 - py0));
		uint32_t row = at >> 8, weight = row + 1 < (uint32_t)sh ? at & 255 : 0;
		const uint32_t *upper = (const uint32_t *)(s->pixels + s->offset +
		    (uint64_t)(sy + row) * s->stride) + sx;
		const uint32_t *from = upper;
		if (weight) {
			const uint32_t *lower = (const uint32_t *)((const uint8_t *)upper + s->stride);
			uint32_t first = work->column[x0];
			uint32_t last = work->column[x1 - 1] + (work->weight[x1 - 1] != 0);
			for (uint32_t c = first; c <= last; c++)
				work->row[c] = upper[c] == lower[c] ? upper[c] :
				    redfin_display_blend(upper[c], lower[c], weight);
			from = work->row;
		}
		uint32_t *to = (uint32_t *)(pixels + (uint64_t)y * stride);
		for (int64_t x = x0; x < x1; x++) {
			uint32_t c = work->column[x], w = work->weight[x];
			to[x] = !w || from[c] == from[c + 1] ? from[c] :
			    redfin_display_blend(from[c], from[c + 1], w);
		}
	}
	if (copied) *copied = (uint64_t)(x1 - x0) * (uint64_t)(y1 - y0) * 4;
	return true;
}

/* Ignore contacts beginning in margins until UP. Contacts already delivered
 * keep their release and clamp at the viewport edge when dragged outside. */
static inline bool
redfin_display_touch_map(const struct redfin_display_geometry *g,
    bool down, bool was_down, bool *ignored, int x, int y,
    int32_t *nx, int32_t *ny, bool *edge)
{
	if (!redfin_display_geometry_valid(g) || !ignored || !nx || !ny || !edge) return false;
	if (*ignored) { if (!down) *ignored = false; return false; }
	int64_t vx = (int64_t)x - g->x, vy = (int64_t)y - g->y;
	bool inside = vx >= 0 && vy >= 0 && vx < (int)g->w && vy < (int)g->h;
	if (down && !was_down && !inside) { *ignored = true; return false; }
	vx = vx < 0 ? 0 : vx >= (int)g->w ? (int)g->w - 1 : vx;
	vy = vy < 0 ? 0 : vy >= (int)g->h ? (int)g->h - 1 : vy;
	*nx = (int32_t)(((int64_t)vx << 16) / g->w);
	*ny = (int32_t)(((int64_t)vy << 16) / g->h);
	*edge = vx < 48 || vx > (int)g->w - 1 - 48 || vy < 48 || vy > (int)g->h - 1 - 48;
	return true;
}
#endif
