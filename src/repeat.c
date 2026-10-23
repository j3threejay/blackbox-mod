/*
 * Note repeat on the Pads screen. Original 1010music Blackbox, firmware 3.1.9.
 *
 * Asked for (2026-10-19): hold a control + hold pads = each pad retriggers on the beat at a chosen division, like an
 * MPC's Note Repeat, on the Swing / Groove grid, and recorded when a sequence records. Map: research/NOTE_REPEAT_RE.md.
 *
 * Controls (solo.c): the Pads column's third position (MUTE / SOLO / blank / blank) now reads MUTE / SOLO / RPT / 1/16.
 * Hold RPT and hold pads: they repeat. Tap the fourth button: the division steps 1/4, 1/8, 1/8T, 1/16, 1/16T, 1/32,
 * 1/32T. Velocity = the VEL slider (a repeat carries velocity 0, which the controller replaces with the slider's
 * value, as for a tap). Toggle pads (Launch Mode 2) are not repeated: they would play every other hit.
 *
 * Paths:
 *  - Screen task. The app's pad-down note-on (bl FUN_0804c61c @0x080a0a44) and pad-up note-off (bl FUN_0804c5d4
 *    @0x080a1a72) come here first. With RPT held, a pad's own note-on is NOT sent: the scheduler owns that pad until
 *    it is let go (its note-off is dropped too; the scheduler sends its own). The rest of the tap (select, light)
 *    is stock's.
 *  - Audio task, from duck_block before the engine's control tick (so before stock advances the clock and drains the
 *    inbox): repeat_tick puts each due repeat into the controller inbox with FUN_080518dc(engine, msg) - cmd 0x42 at a
 *    SAMPLE OFFSET in the coming block, +0x14 = 1, as stock's own CV path does - and its note-off (0x43) half a
 *    division later. The router plays the pad, records it and lights it, exactly as for a tap. (Never the app->engine
 *    ring from here: it sleeps while full and only this task empties it.)
 *    The coming block starts at clock + N (the player computes offsets after the advance: SWING_RE.md, FUN_080696d8
 *    adds the block before anything plays). Grid: straight ticks (960 a quarter); a repeat's sample =
 *    groove_t2s(next) (triplets on the raw map: an MPC does not swing them), due when that sample is in the block.
 *    Transport stopped: a free grid in samples from the press at the tempo.
 *  - Recording: the recorder stamps a note with the block start's RAW tick (bl FUN_08069c38 @0x0805c936), so a note
 *    that sounded swung was stored as if straight and swung again on playback. repeat_rec_tick returns the block
 *    start's STRAIGHT tick through the Groove instead (picked in testing: "straight grid"); with Swing 50 % and Groove Stock
 *    that is bit for bit stock's. This covers taps as well as repeats. External clock (+0x2c68 set): stock's.
 * First hit: at once if the press lands within a quarter of a division after a grid point (or the transport is
 * stopped), else on the next grid point.
 * State: in insert.c's SDRAM bank's spare tail (INS_OFFSET + 0x21800; both sides assert it).
 * CPU (estimate): idle ~10 instructions a block; a held pad ~2 map calls + a message per block (~0.02 %); each repeat
 * costs what a tap on that pad costs.
 */
#include <stdint.h>

#define FN(addr) ((addr) | 1u)

typedef void (*note_fn)(void *app, uint32_t pad, int note, int vel, int a5);
typedef void (*inbox_fn)(uint8_t *engine, const void *msg);
typedef void (*raw2s_fn)(int64_t *out, uint8_t *clk, const int64_t *ticks);
typedef int (*setting_fn)(const void *store, unsigned param);
#define fw_note_on   ((note_fn)FN(0x0804c61c))
#define fw_note_off  ((note_fn)FN(0x0804c5d4))
#define fw_inbox     ((inbox_fn)FN(0x080518dc))
#define fw_raw2s     ((raw2s_fn)FN(0x0804d798))
#define fw_setting   ((setting_fn)FN(0x08093e9c))
int64_t *groove_s2t(int64_t *out, uint8_t *clock, uint32_t lo, int32_t hi);   /* groove.c */
int64_t *groove_t2s(int64_t *out, uint8_t *clock, const int64_t *ticks);
uint8_t *master_block(void);                                                   /* master.c */

#define APP          ((const uint8_t *)0x24020088u)
#define APP_SCREEN   0x8ca4                  /* current screen: 2 = Pads */
#define SCREEN_PADS  2
#define APP_PADS     (0x24020088u + 0x1840u)  /* pad stores: + row * 0xf0 + col * 0x30 */
#define P_LAUNCH     0x93                    /* Launch Mode: Trigger, Gate, Toggle */
#define LAUNCH_TOGGLE 2
#define CLOCK_BPM    0x18
#define CLOCK_PLAYING 0x38
#define CLOCK_SYNC   0x2c68                  /* external clock state (FUN_080696d8: param_1[0xb1a]) */
#define CLOCK_RAW    0x30

#define REPEAT_OFFSET (0x56800u + 0xb000u + 0x21800u)    /* insert.c's bank tail (it asserts its bank stays below) */
#define DIVS 7
static const uint16_t div_ticks[DIVS] = {960, 480, 320, 240, 160, 120, 80};
static const char *const div_names[DIVS] = {"1/4", "1/8", "1/8T", "1/16", "1/16T", "1/32", "1/32T"};
#define DIV_DEFAULT 3                         /* 1/16 */

struct rpt_state {
    uint32_t magic;
    uint8_t hold;                             /* RPT is held (screen task) */
    uint8_t div;                              /* index into div_ticks (screen task) */
    uint16_t held;                            /* pads held while RPT was (screen task) */
    uint32_t pad_id[16];                      /* each held pad's engine-form id (screen task) */
    uint16_t live, off_pending;               /* audio task */
    uint8_t clocked[16];                      /* audio: next[] is in ticks (1) or samples (0) */
    int64_t next[16];                         /* audio: the next repeat, straight tick or sample */
    int64_t off_at[16];                       /* audio: the sample of the pending note-off */
};
_Static_assert(sizeof(struct rpt_state) <= 0x800, "the insert bank's tail gives note repeat 0x800");
#define MAGIC 0x52505431u                     /* "RPT1" */

static volatile struct rpt_state *state(void)
{
    uint8_t *mem = master_block();
    if (!mem)
        return 0;
    volatile struct rpt_state *s = (volatile struct rpt_state *)(mem + REPEAT_OFFSET);
    if (s->magic != MAGIC) {                  /* the SDRAM keeps whatever an older build left: garbage, not ours */
        s->hold = 0;
        s->div = DIV_DEFAULT;
        s->held = 0;
        s->live = 0;
        s->off_pending = 0;
        s->magic = MAGIC;
    }
    return s;
}

static int pad_index(uint32_t pad)
{
    unsigned row = (pad >> 8) & 0xf, col = pad & 0xf;
    return row <= 3 && col <= 3 ? (int)(row * 4 + col) : -1;
}

/* ---- screen task ---- */

/* Replaces the app's pad-down note-on (bl @0x080a0a44). */
void repeat_pad_down(void *app, uint32_t pad, int note, int vel, int a5)
{
    volatile struct rpt_state *s = state();
    int i = pad_index(pad);
    if (s && s->hold && i >= 0) {
        const void *store = (const void *)(APP_PADS + (unsigned)(i >> 2) * 0xf0u + (unsigned)(i & 3) * 0x30u);
        if (fw_setting(store, P_LAUNCH) != LAUNCH_TOGGLE) {
            s->pad_id[i] = pad;
            s->held = (uint16_t)(s->held | (1u << i));
            return;                           /* the scheduler plays it, on the grid */
        }
    }
    fw_note_on(app, pad, note, vel, a5);
}

/* Replaces the app's pad-up note-off (bl @0x080a1a72). */
void repeat_pad_up(void *app, uint32_t pad, int note, int vel, int a5)
{
    volatile struct rpt_state *s = state();
    int i = pad_index(pad);
    if (s && i >= 0 && (s->held >> i) & 1) {
        s->held = (uint16_t)(s->held & ~(1u << i));
        return;                               /* the scheduler sends this pad's last note-off itself */
    }
    fw_note_off(app, pad, note, vel, a5);
}

/* solo.c: RPT pressed (1) / released (0), the division button, its label */
void repeat_hold(int on)
{
    volatile struct rpt_state *s = state();
    if (s)
        s->hold = (uint8_t)(on != 0);
}

void repeat_next_div(void)
{
    volatile struct rpt_state *s = state();
    if (s)
        s->div = (uint8_t)(s->div + 1u < DIVS ? s->div + 1u : 0u);
}

const char *repeat_div_name(void)
{
    volatile struct rpt_state *s = state();
    return div_names[s && s->div < DIVS ? s->div : DIV_DEFAULT];
}

int repeat_held(void)
{
    volatile struct rpt_state *s = state();
    return s && s->hold;
}

/* ---- audio task ---- */

struct note_msg {
    uint8_t cmd, _r[3];
    uint32_t offset, pad, note, vel;
    uint16_t on, a5;
};

static void send(uint8_t *engine, uint8_t cmd, uint32_t pad, int64_t at, int64_t s0, int n)
{
    int64_t off = at - s0;
    struct note_msg m = {cmd, {0, 0, 0}, (uint32_t)(off < 0 ? 0 : off >= n ? n - 1 : off), pad, 0, 0, 1, 0};
    fw_inbox(engine, &m);
}

static int64_t sample_of(uint8_t *clock, int64_t tick, int triplet)
{
    int64_t s = 0;
    if (triplet)
        fw_raw2s(&s, clock + 8, &tick);
    else
        groove_t2s(&s, clock, &tick);
    return s;
}

static int64_t straight(uint8_t *clock, int64_t sample)
{
    int64_t t = 0;
    groove_s2t(&t, clock, (uint32_t)sample, (int32_t)(sample >> 32));
    return t;
}

/* duck_block, before the engine's control tick. engine = the engine (its +0 is the sample clock), bufs[0xb] = frames */
void repeat_tick(uint8_t *engine, const uint32_t *bufs)
{
    volatile struct rpt_state *s = state();
    if (!s || !engine || !bufs)
        return;
    uint16_t want = s->hold && APP[APP_SCREEN] == SCREEN_PADS ? s->held : 0;
    if (!want && !s->live && !s->off_pending)
        return;
    int n = (int)bufs[0xb];
    if (n <= 0 || n > 1024)
        return;
    int64_t s0 = *(const int64_t *)engine + n, s1 = s0 + n;      /* the block about to be rendered */
    float bpm = *(const float *)(engine + CLOCK_BPM);
    if (!(bpm > 10.0f && bpm < 1000.0f))
        bpm = 120.0f;
    unsigned d = s->div < DIVS ? s->div : DIV_DEFAULT;
    int64_t div = div_ticks[d];
    int triplet = d == 2 || d == 4 || d == 6;
    int playing = engine[CLOCK_PLAYING] != 0 && engine[CLOCK_SYNC] == 0;
    int64_t period = (int32_t)(2880000.0f / bpm * (float)div / 960.0f);   /* samples: 60 s x 48 kHz per beat;
                                                                              32-bit maths (no libgcc here) */
    if (period < 16)
        period = 16;

    for (int i = 0; i < 16; i++) {           /* this block's note-offs first */
        uint16_t bit = (uint16_t)(1u << i);
        if ((s->off_pending & bit) && s->off_at[i] < s1) {
            send(engine, 0x43, s->pad_id[i], s->off_at[i], s0, n);
            s->off_pending = (uint16_t)(s->off_pending & ~bit);
        }
    }
    for (int i = 0; i < 16; i++) {
        uint16_t bit = (uint16_t)(1u << i);
        if (!(want & bit)) {
            s->live = (uint16_t)(s->live & ~bit);   /* let go: its last note-off is already pending */
            continue;
        }
        uint32_t pad = s->pad_id[i];
        if (!(s->live & bit) || s->clocked[i] != (uint8_t)playing) {
            int first = !(s->live & bit);
            s->live = (uint16_t)(s->live | bit);
            s->clocked[i] = (uint8_t)playing;
            if (playing) {
                int64_t t0 = straight(engine, s0);
                int32_t phase = (int32_t)t0 % (int32_t)div;          /* ticks stay inside int32 for ~150 h */
                if (phase < 0)
                    phase += (int32_t)div;
                s->next[i] = t0 - phase + div;
                if (first && (phase == 0 || phase * 4 <= div)) {
                    send(engine, 0x42, pad, s0, s0, n);              /* just after a grid point: now */
                    s->off_at[i] = s0 + period / 2;
                    s->off_pending = (uint16_t)(s->off_pending | bit);
                }
            } else {
                s->next[i] = s0;                                    /* stopped: now, then every period */
            }
        }
        if (playing) {
            for (int k = 0; k < 8; k++) {
                int64_t at = sample_of(engine, s->next[i], triplet);   /* due by its own SAMPLE: a triplet on the
                                                                          raw map and a swung 16th both land right */
                if (at >= s1)
                    break;
                if (s->off_pending & bit)                           /* the last one's off first */
                    send(engine, 0x43, pad, at, s0, n);
                send(engine, 0x42, pad, at, s0, n);
                s->off_at[i] = at + period / 2;
                s->off_pending = (uint16_t)(s->off_pending | bit);
                s->next[i] += div;
            }
        } else {
            for (int k = 0; k < 8 && s->next[i] < s1; k++) {
                int64_t at = s->next[i];
                if (s->off_pending & bit)
                    send(engine, 0x43, pad, at, s0, n);
                send(engine, 0x42, pad, at, s0, n);
                s->off_at[i] = at + period / 2;
                s->off_pending = (uint16_t)(s->off_pending | bit);
                s->next[i] += period;
            }
        }
    }
}

/* Replaces the recorder's block tick (bl FUN_08069c38 @0x0805c936): the block start's straight tick, through the
   Groove, so a recorded note plays back on the grid it was heard on. Audio task. */
void repeat_rec_tick(int64_t *out, uint8_t *clock)
{
    if (clock[CLOCK_SYNC]) {
        *out = *(const int64_t *)(clock + CLOCK_RAW);              /* external clock: stock's */
        return;
    }
    int64_t sample = *(const int64_t *)clock;
    groove_s2t(out, clock, (uint32_t)sample, (int32_t)(sample >> 32));
}
