/*
 * Live level meters on the Mixer screen: one per pad, after the fader. Original 1010music Blackbox, firmware 3.1.9.
 * (Asked for 2026-10-18: "after fader and per pad". Map: research/MIXER_METERS_RE.md.)
 *
 * Audio side (engine task):
 *  - Each pad's mix is added into its output bus by FUN_0804da6c, after Level, Pan, mute, Saturation and the insert:
 *    @0x0805aa12 (Sample / Multi pads) and @0x08068c0e (Clip / Slicer). meter_add (meter_thunk.S) takes the pad in r4
 *    and the pad's buffer in r1, records the buffer's peak, then goes on into FUN_0804da6c untouched.
 *  - A pad with no send, no Saturation and no insert is rendered by stock straight into the bus, with no buffer of its
 *    own to measure. While the Mixer is showing, insert_on() answers yes for every pad, so stock takes the path it
 *    takes for a pad with a reverb send (own buffer, then added in). Off the Mixer nothing changes.
 *  - meter_tick (from insert_tick, once per engine block) lets the peaks fall ~20 dB a second and counts `alive` down.
 * GUI side (screen task), Mixer view vtable 0x080f0f10:
 *  - slot 0 (tick, every frame): stock first; then `alive` = 8 and, every second frame, each pad's meter height
 *    (34 px, 1.5 dB a pixel: -51 .. 0 dBFS) and a 1 s peak-hold line. A change asks for the overlay layer to be
 *    redrawn (flags[1]); nothing changing costs nothing.
 *  - slot 1 (draw): stock first; then, on the overlay pass and not on the Mute / Solo screen, a 4 x 34 px strip at the
 *    right edge of each cell (x + 57 .. 60, y + 15 .. 48: clear of the texts, the play bar and the mute bar):
 *    green to -12 dB, yellow to -3 dB, red above, from the palette (indices 11, 20, 12), so themes colour it.
 * State: 140 bytes in master.c's SDRAM block, in filter.c's S950 region at +0x3760 (free; research section 4).
 * CPU (estimate): audio ~6 instr/frame per sounding pad for the peak, + the own-buffer path for pads that had none,
 * ~1-2 % with 16 pads and only while the Mixer shows; GUI: up to 30 overlay redraws a second while levels move.
 */
#include <stdint.h>

#define FN(addr) ((addr) | 1u)

typedef void (*view_fn)(uint8_t *view, uint8_t *arg);
typedef void (*fill_fn)(const int32_t *rect, int colour, void *canvas);

#define fw_mixer_tick ((view_fn)FN(0x080b6600))
#define fw_view_draw  ((view_fn)FN(0x080aeaf8))
#define fw_fill       ((fill_fn)FN(0x0808ea22))

uint8_t *master_block(void);
void bkp_enable(void);

#define METER_OFFSET (0x56800u + 0x7000u + 0x3760u)    /* filter.c's S9_OFFSET + 0x3760: free up to 0x3800 */
#define METER_MAGIC  0x4d455452u                        /* "RTEM" */

struct meter_state {
    uint32_t magic;
    volatile uint32_t alive;     /* GUI sets 8 every Mixer frame; the audio block counts it down */
    volatile float peak[16];     /* audio: max |x| of the pad's post-fader mix, falling */
    uint8_t shown[16], hold[16]; /* GUI: lit pixels, hold line (pixels) */
    uint16_t hold_left[16];      /* GUI: updates until the hold line starts to fall */
    uint32_t frame;              /* GUI: frame counter (meters move every second frame) */
};
_Static_assert(0x3760 + sizeof(struct meter_state) <= 0x3800, "inside the free part of the S950 region");

#define VIEW_CELLS   0x3ac       /* Mixer view: cell (row, col) at + row * 0x680 + col * 0x1a0 */
#define VIEW_MUTEMODE 0x1e40     /* Mixer view: Mute / Solo screen */
#define CELL_HIDDEN  0x30
#define CELL_ID      0x38        /* row << 4 | col, row 0 = the bottom row (the GUI's y runs up) */
#define CELL_CONTENT 0x188       /* 0 = an empty pad */
#define STRIP_X 57
#define STRIP_Y 15
#define STRIP_H 34
#define GREEN_TO 26              /* pixels: -12 dB */
#define YELLOW_TO 32             /* -3 dB */
#define STEP 0.84139514f         /* -1.5 dB */
#define HOLD_UPDATES 30          /* ~1 s at 30 updates a second */

static struct meter_state *state(void)
{
    uint8_t *mem = master_block();
    if (!mem)
        return 0;
    struct meter_state *m = (struct meter_state *)(mem + METER_OFFSET);
    if (m->magic != METER_MAGIC) {
        uint32_t *w = (uint32_t *)m;
        for (unsigned i = 0; i < sizeof *m / 4; i++)
            w[i] = 0;
        m->magic = METER_MAGIC;
    }
    return m;
}

/* ---- audio ---- */

/* insert.c's insert_on: while the Mixer shows, every pad gets its own mix buffer. Integer only (thunk context). */
int meter_alive(void)
{
    struct meter_state *m = state();
    return m && m->alive != 0;
}

/* meter_thunk.S: before the pad's mix goes into its bus. buf: FUN_0804da6c's source {n0, n, L, R, silent @16, stereo @17} */
void meter_peak(const uint8_t *pad, const int32_t *buf)
{
    struct meter_state *m = state();
    if (!m || !m->alive || !pad || !buf)
        return;
    uint32_t id = *(const uint32_t *)(pad + 0x18);       /* col | row << 8 | bank << 16 */
    uint32_t col = id & 0xffu, row = (id >> 8) & 0xffu;
    if (col > 3 || row > 3 || (id >> 16) != 0)
        return;
    const uint8_t *flags = (const uint8_t *)(buf + 4);
    if (flags[0])                                        /* silent */
        return;
    int n = buf[1] ? buf[1] : buf[0];
    if (n <= 0 || n > 4096)
        return;
    const float *l = (const float *)buf[2], *r = flags[1] ? (const float *)buf[3] : 0;
    if (!l)
        return;
    float p = 0.0f, p2 = 0.0f;                            /* vabs + vmaxnm, two at a time */
    int i = 0;
    for (; i + 1 < n; i += 2) {
        p = __builtin_fmaxf(p, __builtin_fabsf(l[i]));
        p2 = __builtin_fmaxf(p2, __builtin_fabsf(l[i + 1]));
    }
    if (i < n)
        p = __builtin_fmaxf(p, __builtin_fabsf(l[i]));
    if (r) {
        for (i = 0; i + 1 < n; i += 2) {
            p = __builtin_fmaxf(p, __builtin_fabsf(r[i]));
            p2 = __builtin_fmaxf(p2, __builtin_fabsf(r[i + 1]));
        }
        if (i < n)
            p = __builtin_fmaxf(p, __builtin_fabsf(r[i]));
    }
    p = __builtin_fmaxf(p, p2);
    unsigned q = row * 4u + col;
    if (p > m->peak[q])
        m->peak[q] = p;
}

/* insert.c's insert_tick, once per engine block */
void meter_tick(void)
{
    struct meter_state *m = state();
    if (!m)
        return;
    if (m->alive)
        m->alive--;
    for (int q = 0; q < 16; q++)
        m->peak[q] *= 0.9942f;                          /* ~20 dB a second at 375 blocks a second */
}

/* ---- GUI ---- */

static uint8_t *cell_of(uint8_t *view, unsigned row, unsigned col)
{
    return view + VIEW_CELLS + row * 0x680u + col * 0x1a0u;
}

static unsigned pixels(float p)
{
    unsigned h = STRIP_H;
    float t = 1.0f;
    while (h && p < t) {
        t *= STEP;
        h--;
    }
    return h;
}

/* Mixer view vtable slot 0 (word @0x080f0f10): the per-frame tick. flags: {full, overlay} redraw wanted. */
void meter_view_tick(uint8_t *view, uint8_t *flags)
{
    fw_mixer_tick(view, flags);
    struct meter_state *m = state();
    if (!m)
        return;
    m->alive = 8;
    if (++m->frame & 1u)
        return;
    int changed = 0;
    for (unsigned q = 0; q < 16; q++) {
        unsigned h = pixels(m->peak[q]);
        unsigned hold = m->hold[q];
        if (h >= hold) {
            hold = h;
            m->hold_left[q] = HOLD_UPDATES;
        } else if (m->hold_left[q]) {
            m->hold_left[q]--;
        } else {
            hold--;                                          /* falls a pixel an update after the hold */
        }
        if (h != m->shown[q] || hold != m->hold[q])
            changed = 1;
        m->shown[q] = (uint8_t)h;
        m->hold[q] = (uint8_t)hold;
    }
    if (changed && flags)
        flags[1] = 1;
}

static void bar(void *canvas, int32_t x, int32_t y, unsigned from, unsigned to, int colour)
{
    if (to <= from)
        return;
    int32_t r[4] = {x, y + (int32_t)from, 4, (int32_t)(to - from)};
    fw_fill(r, colour, canvas);
}

static int zone(unsigned px)
{
    return px <= GREEN_TO ? 11 : px <= YELLOW_TO ? 20 : 12;
}

/* Mixer view vtable slot 1 (word @0x080f0f14): draw. dc: {full pass, overlay pass, ..., canvas @+4}. */
void meter_view_draw(uint8_t *view, uint8_t *dc)
{
    fw_view_draw(view, dc);
    if (!dc[1] || view[VIEW_MUTEMODE])
        return;
    struct meter_state *m = state();
    if (!m)
        return;
    void *canvas = *(void **)(dc + 4);
    for (unsigned row = 0; row < 4; row++)
        for (unsigned col = 0; col < 4; col++) {
            uint8_t *cell = cell_of(view, row, col);
            if (cell[CELL_HIDDEN] || !cell[CELL_CONTENT])
                continue;
            unsigned id = *(const uint16_t *)(cell + CELL_ID), q = ((id >> 4) & 3u) * 4u + (id & 3u);
            const int32_t *rect = (const int32_t *)(cell + 4);
            int32_t x = rect[0] + STRIP_X, y = rect[1] + STRIP_Y;
            unsigned h = m->shown[q], hold = m->hold[q];
            bar(canvas, x, y, 0, h < GREEN_TO ? h : GREEN_TO, 11);
            bar(canvas, x, y, GREEN_TO, h < YELLOW_TO ? h : YELLOW_TO, 20);
            bar(canvas, x, y, YELLOW_TO, h, 12);
            if (hold > h)
                bar(canvas, x, y, hold - 1, hold, zone(hold));
        }
}
