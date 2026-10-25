/*
 * Slicer: bottom knobs edit the selected slice, top-right zooms. Original 1010music Blackbox, firmware 3.1.9.
 *
 * Stock Waveform screen in Slicer mode: top-left = Slice (select), top-right = Slice Pos
 * (start of the selected slice), bottom knobs unbound. This binds
 *   bottom-left  -> start of the selected slice   (marker sel-1, same thing Slice Pos moved)
 *   bottom-right -> end of the selected slice     (marker sel, i.e. the next slice's start)
 *   top-right    -> zoom, in half-octave steps, centred on whichever of Start / End was turned last
 * The view also scrolls to that marker when a knob turn or a slice selection leaves it off screen.
 * Markers keep the stock limits: one sample clear of the neighbouring markers / sample end,
 * except that the first slice's Start may go down to sample 0.
 * The last slice ends at the end of the WAV, so its End knob is fixed.
 */
#include <stdint.h>

#define FN(addr) ((addr) | 1u)

typedef void (*knob_fn)(uint8_t *knob);
typedef void (*knob_label_fn)(uint8_t *knob, const char *label);
typedef void (*knob_int_fn)(uint8_t *knob, int v);
typedef void (*knob_range_fn)(uint8_t *knob, int lo, int hi);
typedef void (*slice_get_fn)(uint8_t *list, int idx, int *out);
typedef void (*slice_set_fn)(uint8_t *list, int idx, int value);
typedef void (*wave_list_fn)(uint8_t *wave, uint8_t *list);
typedef void (*wave_sel_fn)(uint8_t *wave, int sel);
typedef void (*view_fn)(uint8_t *view);
typedef void (*view_int_fn)(uint8_t *view, int v);
typedef void (*post_fn)(uint8_t *view, void *msg);

#define fw_knob_reset   ((knob_fn)FN(0x080b04c8))
#define fw_knob_label   ((knob_label_fn)FN(0x080b03c0))
#define fw_knob_type    ((knob_int_fn)FN(0x080b0b08))
#define fw_knob_range   ((knob_range_fn)FN(0x080b09e4))
#define fw_knob_value   ((knob_int_fn)FN(0x080b0790))
#define fw_slice_get    ((slice_get_fn)FN(0x08093cb4))
#define fw_slice_set    ((slice_set_fn)FN(0x08093cbc))
#define fw_wave_slices  ((wave_list_fn)FN(0x080c6e8c))
#define fw_wave_select  ((wave_sel_fn)FN(0x080c6ec8))
#define fw_slicepos_set ((view_int_fn)FN(0x080a53b8))   /* stock Slice Pos handler */
#define fw_post         ((post_fn)FN(0x080aed14))

/* waveform view */
#define VIEW_WAVE     0x38
#define WAVE_WIDTH    0x0c       /* pixels */
#define WAVE_DIRTY    0x32
#define WAVE_ZOOM     0x168      /* float, samples per pixel, 1..4096 */
#define WAVE_TOUCHES  0x178      /* fingers down */
#define WAVE_HOLD     0x180      /* ticks the view stays put before it may follow the playhead again */
#define WAVE_SCROLL   0x1e0      /* 1 follow, 2 hold, 3-6 touch gestures */
#define WAVE_CENTRE_X 0x240      /* pixel that shows WAVE_CENTRE */
#define WAVE_CENTRE   0x244      /* sample */
#define WAVE_PENDING  0x24c      /* float, zoom applied by the next tick (the stock pinch writes this); 0 = none */
#define VIEW_PAD      0x29c      /* u16 pad id */
#define VIEW_KNOB_BL  0x950
#define VIEW_KNOB_TR  0xc30
#define VIEW_KNOB_BR  0xf10
#define VIEW_LENGTH   0x2390     /* sample length */
#define VIEW_SLICES   0x2398     /* slice list; marker count at +4 */
#define VIEW_COUNT    0x239c
#define VIEW_SEL      0x47e4     /* selected slice, 1-based */
/* knob widget */
#define KNOB_PARAM    0x14
#define KNOB_STEP     0x28c      /* samples per detent, follows zoom */
#define KNOB_TYPE_INT 1
#define KNOB_TYPE_POS 0xd

#define PARAM_START   0x3e0      /* private ids: above the 500-entry parameter table */
#define PARAM_END     0x3e1
#define PARAM_ZOOM    0x3e2
#define MSG_PARAM     0x6e
#define MSG_SLICE_POS 0x4a
#define MSG_TAG       0x080cfba4u

/* Patch RAM (see solo.c): one byte, 1 = End was turned last, anything else = Start. Not zeroed at boot. */
#define ANCHOR_END (*(volatile uint8_t *)0x2405ffa0u)

#define ZOOM_LEVELS 25           /* level k = 4096 / 2^(k/2) samples per pixel: 0 = widest, 24 = one sample per pixel */
#define HOLD_TICKS  300          /* what the stock scroll-to uses */
#define EDGE        8            /* a marker this close to the edge counts as off screen */

static const float zoom_tab[ZOOM_LEVELS] = {
    4096.0f, 2896.309f, 2048.0f, 1448.155f, 1024.0f, 724.0773f, 512.0f, 362.0387f, 256.0f, 181.0193f,
    128.0f, 90.50967f, 64.0f, 45.25483f, 32.0f, 22.62742f, 16.0f, 11.31371f, 8.0f, 5.656854f,
    4.0f, 2.828427f, 2.0f, 1.414214f, 1.0f,
};

struct msg {
    uint16_t id, _r0;
    uint32_t tag;
    uint16_t pad, _r1;
    int32_t a, b;
    uint32_t c;
};

static int rd(uint8_t *p, int off)
{
    return *(int *)(p + off);
}

/* Marker index of the selected slice's start, or -1 when there is no valid selection. */
static int sel_marker(uint8_t *view)
{
    int count = rd(view, VIEW_COUNT), sel = rd(view, VIEW_SEL);
    return count > 0 && sel >= 1 && sel <= count ? sel - 1 : -1;
}

static void limits(uint8_t *view, int idx, int *lo, int *hi)
{
    int prev = 0, next = rd(view, VIEW_LENGTH);
    if (idx > 0)
        fw_slice_get(view + VIEW_SLICES, idx - 1, &prev);
    if (idx + 1 < rd(view, VIEW_COUNT))
        fw_slice_get(view + VIEW_SLICES, idx + 1, &next);
    *lo = idx > 0 ? prev + 1 : 0;                    /* stock Slice Pos stops at 1; the first slice may start at 0 */
    *hi = next - 1;
}

/* Samples per pixel, counting a zoom that is set but not applied yet. */
static float zoom(uint8_t *view)
{
    float pending = *(float *)(view + VIEW_WAVE + WAVE_PENDING);
    return pending != 0.0f ? pending : *(float *)(view + VIEW_WAVE + WAVE_ZOOM);
}

static int zoom_level(float z)
{
    int k = 0;
    while (k + 1 < ZOOM_LEVELS && z * z < zoom_tab[k] * zoom_tab[k + 1])
        k++;
    return k;
}

/* Widest level worth offering: the closest one that still shows the whole sample. */
static int zoom_widest(uint8_t *view)
{
    float width = (float)rd(view + VIEW_WAVE, WAVE_WIDTH), len = (float)rd(view, VIEW_LENGTH);
    int k = 0;
    while (k + 1 < ZOOM_LEVELS && zoom_tab[k + 1] * width >= len)
        k++;
    return k;
}

static void show(uint8_t *view, uint8_t *knob, int lo, int hi, int value)
{
    int step = (int)zoom(view);
    *(int *)(knob + KNOB_STEP) = step > 0 ? step : 1;
    fw_knob_range(knob, lo, hi);
    fw_knob_value(knob, value);
}

static void show_marker(uint8_t *view, uint8_t *knob, int idx)
{
    int lo, hi, value = 0;
    limits(view, idx, &lo, &hi);
    fw_slice_get(view + VIEW_SLICES, idx, &value);
    show(view, knob, lo, hi, value);
}

static void refresh_start(uint8_t *view)
{
    uint8_t *knob = view + VIEW_KNOB_BL;
    if (rd(knob, KNOB_PARAM) != PARAM_START)
        return;
    int idx = sel_marker(view);
    if (idx < 0)
        show(view, knob, 0, 0, 0);
    else
        show_marker(view, knob, idx);
}

static void refresh_end(uint8_t *view)
{
    uint8_t *knob = view + VIEW_KNOB_BR;
    if (rd(knob, KNOB_PARAM) != PARAM_END)
        return;
    int idx = sel_marker(view), len = rd(view, VIEW_LENGTH);
    if (idx < 0)
        show(view, knob, 0, 0, 0);
    else if (idx + 1 >= rd(view, VIEW_COUNT))
        show(view, knob, len, len, len);            /* last slice ends at the end of the WAV */
    else
        show_marker(view, knob, idx + 1);
}

static void move_marker(uint8_t *view, int idx, int value)
{
    int lo, hi;
    limits(view, idx, &lo, &hi);
    if (value < lo)
        value = lo;
    if (value > hi)
        value = hi;
    fw_slice_set(view + VIEW_SLICES, idx, value);
    fw_wave_slices(view + VIEW_WAVE, view + VIEW_SLICES);
    fw_wave_select(view + VIEW_WAVE, rd(view, VIEW_SEL));
    struct msg m = {MSG_SLICE_POS, 0, MSG_TAG, *(uint16_t *)(view + VIEW_PAD), 0, idx, value, 0};
    fw_post(view, &m);
}

static void refresh_zoom(uint8_t *view)
{
    uint8_t *knob = view + VIEW_KNOB_TR;
    if (rd(knob, KNOB_PARAM) != PARAM_ZOOM)
        return;
    fw_knob_range(knob, zoom_widest(view), ZOOM_LEVELS - 1);
    fw_knob_value(knob, zoom_level(zoom(view)));
}

/* Centre the view on the marker turned last (Start or End of the selected slice). */
static void focus(uint8_t *view, int only_if_hidden)
{
    uint8_t *wave = view + VIEW_WAVE;
    int idx = sel_marker(view), pos = rd(view, VIEW_LENGTH);
    if (idx < 0 || rd(wave, WAVE_TOUCHES) != 0)
        return;
    if (ANCHOR_END != 1)
        fw_slice_get(view + VIEW_SLICES, idx, &pos);
    else if (idx + 1 < rd(view, VIEW_COUNT))
        fw_slice_get(view + VIEW_SLICES, idx + 1, &pos);
    if (only_if_hidden) {
        int x = (int)((float)(pos - rd(wave, WAVE_CENTRE)) / zoom(view)) + rd(wave, WAVE_CENTRE_X);
        if (x >= EDGE && x < rd(wave, WAVE_WIDTH) - EDGE)
            return;
    }
    *(int *)(wave + WAVE_CENTRE) = pos;
    wave[WAVE_SCROLL] = 2;
    *(int *)(wave + WAVE_HOLD) = HOLD_TICKS;
    wave[WAVE_DIRTY] = 1;
}

static void set_zoom(uint8_t *view, int level)
{
    int widest = zoom_widest(view);
    if (level < widest)
        level = widest;
    if (level > ZOOM_LEVELS - 1)
        level = ZOOM_LEVELS - 1;
    *(float *)(view + VIEW_WAVE + WAVE_PENDING) = zoom_tab[level];
    focus(view, 0);
    refresh_start(view);
    refresh_end(view);
}

static void bind(uint8_t *knob, const char *label, int param, int type)
{
    fw_knob_reset(knob);
    fw_knob_label(knob, label);
    *(int *)(knob + KNOB_PARAM) = param;
    fw_knob_type(knob, type);
}

/* Replace the two "unbind bottom knob" calls in the Slicer-mode setup. */
void slice_bind_start(int param, int value, uint8_t *knob)
{
    (void)param;
    (void)value;
    bind(knob, "Start:", PARAM_START, KNOB_TYPE_POS);
    refresh_start(knob - VIEW_KNOB_BL);
}

void slice_bind_end(int param, int value, uint8_t *knob)
{
    (void)param;
    (void)value;
    bind(knob, "End:", PARAM_END, KNOB_TYPE_POS);
    refresh_end(knob - VIEW_KNOB_BR);
}

/* Replaces the calls to the stock top-right (Slice Pos) refresh after a zoom change and a later refresh. */
void slice_refresh(uint8_t *view)
{
    refresh_zoom(view);
    refresh_start(view);
    refresh_end(view);
}

/* Replaces the same call in the Slicer-mode setup, right after the stock code bound Slice Pos to the top-right knob. */
void slice_setup(uint8_t *view)
{
    bind(view + VIEW_KNOB_TR, "Zoom:", PARAM_ZOOM, KNOB_TYPE_INT);
    slice_refresh(view);
}

/* Replaces the same call after the Slice knob picked another slice. */
void slice_selected(uint8_t *view)
{
    slice_refresh(view);
    focus(view, 1);
}

/* Replaces the stock Slice Pos handler call (no knob sends it once the top-right knob is Zoom). */
void slice_pos_moved(uint8_t *view, int value)
{
    fw_slicepos_set(view, value);
    refresh_start(view);
    refresh_end(view);
}

/* Replaces the generic "forward knob change to the app" post in the view's knob handler. */
int sel_forward(uint8_t *view, struct msg *m);   /* clipsel.c: Clip mode's Start / End / Beats / BPM */

void slice_forward(uint8_t *view, struct msg *m)
{
    if (sel_forward(view, m))
        return;
    if (m->id == MSG_PARAM && m->a == PARAM_ZOOM) {
        set_zoom(view, m->b);
        return;
    }
    if (m->id == MSG_PARAM && (m->a == PARAM_START || m->a == PARAM_END)) {
        int idx = sel_marker(view);
        if (idx < 0)
            return;
        ANCHOR_END = m->a == PARAM_END;
        if (m->a == PARAM_START) {
            move_marker(view, idx, m->b);
            refresh_end(view);
        } else if (idx + 1 < rd(view, VIEW_COUNT)) {
            move_marker(view, idx + 1, m->b);
            refresh_start(view);
        }
        focus(view, 1);
        return;
    }
    fw_post(view, m);
}
