/*
 * Clip pads: tempo from a selection (an Octatrack idea, NOTES TIME STRETCH). Original 1010music Blackbox, firmware 3.1.9.
 *
 * Waveform screen, Clip mode (stock leaves all four knobs unbound there):
 *   top-left     Start:  the selection's first frame            (param 0x15c, saved with the pad)
 *   top-right    End:    the frame after its last one           (param 0x15d; 0 = the end of the file)
 *   bottom-left  Beats:  how many beats the selection holds     (param 0x15e; 0 = Auto: stock's guess, on the selection)
 *   bottom-right BPM:    the selection's own tempo; one detent up = x2 beats, down = /2 (the usual wrong guess)
 * Moving Start or End keeps Beats (an Auto Beats keeps guessing; a set one stays, and BPM follows the new length, as the
 * Octatrack's tempo does when you trim: asked for 10-24). The waveform shows the selection with stock's Start / End markers.
 *
 * The selection MEASURES, it does not trim (decided 10-25: "if I set the start and stop and then truncate it that's
 * not much different than stock"): Start is a beat and where playback begins, Start..End holds Beats beats, and that
 * tempo lays a beat grid from Start over the rest of the file. The clip plays every whole beat from Start to the file's
 * end, synced, sliced and looped exactly as stock would play a file that long (research/stretch/SELECTION_RE.md). No
 * selection (Start 0, End 0 / file end) = stock, to the bit.
 *   - stock's own setup (FUN_08064a94, entered through a trampoline: one patch covers all nine callers) is fed the
 *     played length (whole beats from Start) through its two file-length calls and that beat count in place of Beat
 *     Count, so every derived field (slice size, slot, loop grid, clip BPM, the app's clip length) is stock's arithmetic;
 *   - pad+0x238 / 0x23c (written by stock setup as 0 / file length and read by nothing) carry the selection's start /
 *     end from setup to the spawn: each slice's position gets + start, the last slice ends at the selection's end;
 *   - the Quant / Sync regrid (FUN_08064e7c) sees positions relative to the selection;
 *   - clip_read (filter.c) silences source past the selection's end, as stock does past the file's.
 * Not applied: Sync = Slice (markers), Slicer pads. CPU: setup and spawn only (per note / loop / slice), nothing per frame.
 */
#include <stdint.h>
#include "stretch.h"

#pragma GCC optimize("Os", "no-tree-loop-distribute-patterns")

#define FN(addr) ((addr) | 1u)
typedef int (*setting_fn)(const void *store, int param);
typedef int (*src_len_fn)(void *sample);
typedef unsigned (*src_rate_fn)(void *sample);
typedef int (*spawn_fn)(uint8_t *pad, uint8_t *layer, int delay, int index, void *clk, int note, int flag);
typedef void (*regrid_fn)(uint8_t *pad, int a1, int a2, int a3);
typedef float (*exp2_fn)(float x);
typedef float (*modpitch_fn)(uint8_t *mod);
typedef void (*hint_fn)(void *sample, int pos);
typedef void (*wave_list_fn)(uint8_t *wave, uint8_t *list);
typedef void (*view_int_fn)(uint8_t *view, int v);
typedef void (*knob_fn)(uint8_t *knob);
typedef void (*knob_label_fn)(uint8_t *knob, const char *label);
typedef void (*knob_int_fn)(uint8_t *knob, int v);
typedef void (*knob_range_fn)(uint8_t *knob, int lo, int hi);
typedef void (*post_fn)(uint8_t *view, void *msg);

#define fw_setting      ((setting_fn)FN(0x08093e9c))
#define fw_src_len      ((src_len_fn)FN(0x080636f0))
#define fw_src_rate     ((src_rate_fn)FN(0x0806377c))
#define fw_src_stereo   ((src_len_fn)FN(0x08063790))
#define fw_spawn        ((spawn_fn)FN(0x08065550))
#define fw_regrid       ((regrid_fn)FN(0x08064e7c))
#define fw_exp2         ((exp2_fn)FN(0x0805f728))
#define fw_modpitch     ((modpitch_fn)FN(0x0806fb30))
#define fw_hint         ((hint_fn)FN(0x0806375c))
#define fw_wave_slices  ((wave_list_fn)FN(0x080c6e8c))
#define fw_zoom_refresh ((view_int_fn)FN(0x080a52c4))
#define fw_knob_reset   ((knob_fn)FN(0x080b04c8))
#define fw_knob_label   ((knob_label_fn)FN(0x080b03c0))
#define fw_knob_type    ((knob_int_fn)FN(0x080b0b08))
#define fw_knob_range   ((knob_range_fn)FN(0x080b09e4))
#define fw_knob_value   ((knob_int_fn)FN(0x080b0790))
#define fw_post         ((post_fn)FN(0x080aed14))

#define P_SEL_START 0x15c         /* clean ids (SELECTION_RE.md 4); test_param_ids.py checks them */
#define P_SEL_END   0x15d
#define P_SEL_BEATS 0x15e
#define SEL_MIN     512           /* frames: a selection shorter than the two slice fades is ignored */
#define BEATS_MAX   512
#define SEL_BEATS_LONG 16         /* a detected tempo on a long file marks this many beats (Beats -> Auto stays a short turn) */
#define SEL_LONG_SECS  20.0f      /* tempo_dsp.c's loop length: a shorter file is a loop and keeps its whole length */
#define TOTAL_MAX   4096          /* beats played from Start (~34 min at 120 BPM) */
#define CLK_TEMPO   0x18          /* engine clock: the project tempo, float BPM */

/* class B pad */
#define PAD_ID      0x18
#define PAD_SOURCE  0x24
#define PAD_SEG     0x30
#define PAD_SYNC_ON 0x1f5
#define PAD_STEP    0x220
#define PAD_SEL_S   0x238         /* stock: 0, never read */
#define PAD_SEL_E   0x23c         /* stock: the file length, never read */
#define PAD_MARKERS 0x250
#define PAD_SLICER  0x254
#define PAD_PITCH   0xa80         /* 1/1000 semitone */
#define PAD_BEATCNT 0xb80
#define SEG_POS     0x08
#define SEG_END     0x10
#define SEG_RATE    0x18
#define SEG_FADEIN  0x24
#define SEG_HOLD    0x28
#define SEG_FADEOUT 0x2c
#define LAYER_MOD   0x94

#define APP_PADS    (0x24020088u + 0x1840u)          /* app pad stores: + row * 0xf0 + col * 0x30 */

struct str_bank *stretch_bank(void);                   /* stretch.c: the SDRAM area (clip info lives there) */

static const void *pad_store(const uint8_t *pad)
{
    uint32_t id = *(const uint32_t *)(pad + PAD_ID);
    unsigned row = (id >> 8) & 0xff, col = id & 0xff;
    return row < 4 && col < 5 ? (const void *)(APP_PADS + row * 0xf0u + col * 0x30u) : 0;
}

static unsigned pad_index(const uint8_t *pad)
{
    uint32_t id = *(const uint32_t *)(pad + PAD_ID);
    return ((id >> 8) & 3) * 4 + (id & 3);
}

static int marker_mode(const uint8_t *pad)
{
    return pad[PAD_SYNC_ON] && *(const int32_t *)(pad + PAD_STEP) == 0xf0000 && *(const int32_t *)(pad + PAD_MARKERS);
}

/* The selection [*s, *e) in a file of len frames from the stored values; 0 = none (or not one we apply). */
static int selection(int start, int end, int len, int *s, int *e)
{
    *s = 0;
    *e = len;
    if (len <= 0)
        return 0;
    int a = start < 0 ? 0 : start, b = end <= 0 || end > len ? len : end;
    if ((a == 0 && b == len) || b - a < SEL_MIN)
        return 0;
    *s = a;
    *e = b;
    return 1;
}

/* Stock's Auto rule (setup step 4) on n frames at rate frate and the given tempo: beats, 0 if under half a beat. */
static int auto_beats(int n, unsigned frate, float tempo)
{
    if (!frate || !(tempo > 0.0f))
        return 0;
    float L = (float)n / (float)frate * (tempo / 60.0f);
    int ticks = (int)(L * 960.0f + 0.5f), r = (int)((float)ticks / 960.0f + 0.5f), P = 960;
    if (r > 1) {
        int p = 1;
        while (p * 2 <= r)
            p *= 2;
        P = 960 * p;
    }
    int lo = ticks / P * P, hi = lo + P;
    int T = ticks - lo < hi - ticks ? lo : hi;
    return T / 960;
}

/* ---- engine ---- */

void sel_setup_stock(uint8_t *pad, void *clk);         /* clipsel_thunk.S: stock setup past its first instruction */

/*
 * Stock setup, entered through the trampoline at its first instruction. Before it runs: the selection into
 * 0x238 / 0x23c (sel_len reads them during setup) and our Beats into Beat Count; after: Beat Count back, and the
 * selection back into 0x238 / 0x23c (stock writes 0 / the selection's length there).
 */
void sel_setup(uint8_t *pad, void *clk)
{
    void *sample = *(void **)(pad + PAD_SOURCE);
    const void *store = pad_store(pad);
    int s = 0, e = 0, len = sample ? fw_src_len(sample) : 0, on = 0, beats = 0;
    struct str_bank *bk = stretch_bank();
    if (bk && sample) {
        bk->clip[pad_index(pad)].frate = fw_src_rate(sample);   /* the screen's guess needs the file's rate */
        bk->clip[pad_index(pad)].eng = pad;                       /* tempo detection reads this pad's sample */
    }
    if (store && sample && !pad[PAD_SLICER] && !marker_mode(pad))
        on = selection(fw_setting(store, P_SEL_START), fw_setting(store, P_SEL_END), len, &s, &e);
    if (!on) {
        *(int32_t *)(pad + PAD_SEL_S) = 0;
        *(int32_t *)(pad + PAD_SEL_E) = len;
        sel_setup_stock(pad, clk);
        return;
    }
    /* the section's beats (set, or stock's guess on the section at the project tempo) -> frames per beat -> every
       whole beat from Start to the file's end */
    beats = fw_setting(store, P_SEL_BEATS);
    if (beats <= 0 || beats > BEATS_MAX)
        beats = auto_beats(e - s, fw_src_rate(sample), *(const float *)((const uint8_t *)clk + CLK_TEMPO));
    float fpb = beats > 0 ? (float)(e - s) / (float)beats : 0.0f;
    int total = fpb >= 1.0f ? (int)((float)(len - s) / fpb) : 0;
    if (total < 1) {
        *(int32_t *)(pad + PAD_SEL_S) = 0;
        *(int32_t *)(pad + PAD_SEL_E) = len;
        sel_setup_stock(pad, clk);
        return;
    }
    if (total > TOTAL_MAX)
        total = TOTAL_MAX;
    int play = s + (int)((float)total * fpb + 0.5f);
    if (play > len)
        play = len;
    *(int32_t *)(pad + PAD_SEL_S) = s;
    *(int32_t *)(pad + PAD_SEL_E) = play;
    uint32_t keep = *(uint32_t *)(pad + PAD_BEATCNT);
    *(uint32_t *)(pad + PAD_BEATCNT) = (uint32_t)total;
    sel_setup_stock(pad, clk);
    *(uint32_t *)(pad + PAD_BEATCNT) = keep;
    *(int32_t *)(pad + PAD_SEL_S) = s;
    *(int32_t *)(pad + PAD_SEL_E) = play;
}

/* The two file-length calls inside setup (BL @0x08064b2c, 0x08064c5a; clipsel_thunk.S passes the pad from r4). */
int sel_len(void *sample, uint8_t *pad)
{
    int len = fw_src_len(sample), s = *(int32_t *)(pad + PAD_SEL_S), e = *(int32_t *)(pad + PAD_SEL_E);
    return (s != 0 || e != len) && s >= 0 && e <= len && e - s >= SEL_MIN ? e - s : len;
}

/* The pad's selection as setup left it: 0 = none */
static int pad_sel(uint8_t *pad, int *s, int *e)
{
    void *sample = *(void **)(pad + PAD_SOURCE);
    if (!sample || pad[PAD_SLICER] || marker_mode(pad))
        return 0;
    int len = fw_src_len(sample);
    *s = *(int32_t *)(pad + PAD_SEL_S);
    *e = *(int32_t *)(pad + PAD_SEL_E);
    return (*s != 0 || *e != len) && *s >= 0 && *e <= len && *e - *s >= SEL_MIN;
}

/*
 * The three spawns (BL @0x08065a9a voice start, 0x08066cf2 next slice / loop restart, 0x08066b9a slicer re-pick).
 * Stock places slice N at N x (selection length / slices) from frame 0: move it by the selection's start. The last
 * slice ends at the selection's end; its hold is recomputed the way stock computes it (@0x08065822..0x080658d8).
 */
int sel_spawn(uint8_t *pad, uint8_t *layer, int delay, int index, void *clk, int note, int flag)
{
    int r = fw_spawn(pad, layer, delay, index, clk, note, flag), s, e;
    if (r < 0 || r > 3 || !pad_sel(pad, &s, &e))
        return r;
    uint8_t *seg = pad + PAD_SEG + r * 0x70;
    int64_t pos = *(int64_t *)(seg + SEG_POS) + s;
    *(int64_t *)(seg + SEG_POS) = pos;
    if (*(int64_t *)(seg + SEG_END) != 0) {
        int64_t end = e - 1;
        *(int64_t *)(seg + SEG_END) = end;
        float live = *(float *)(seg + SEG_RATE) *
                     fw_exp2((float)*(int32_t *)(pad + PAD_PITCH) / 1000.0f / 12.0f + fw_modpitch(layer + LAYER_MOD));
        if (live != 0.0f) {
            int fin = *(int32_t *)(seg + SEG_FADEIN), fout = *(int32_t *)(seg + SEG_FADEOUT);
            int h = (int)(0.5f + (float)(int32_t)(end - pos) * (1.0f / live)) - (fin ? fin : 0x100) - fout;
            if (h < 0)
                h = 0;
            *(int32_t *)(seg + SEG_HOLD) = fin ? h : h + 0x100;     /* a folded fade-in (voice start) is in the hold */
        }
    }
    fw_hint(*(void **)(pad + PAD_SOURCE), pos > 8 ? (int)pos - 8 : 0);
    return r;
}

/* The Quant / Sync handler's tail (b.w @0x080679da): stock's regrid works from frame 0, so hand it relative positions. */
void sel_regrid(uint8_t *pad, int a1, int a2, int a3)
{
    int s, e, on = pad_sel(pad, &s, &e) && *(int32_t *)(pad + 0x228) != 0xf0000;
    if (on)
        for (int i = 0; i < 4; i++)
            if (pad[PAD_SEG + i * 0x70])
                *(int64_t *)(pad + PAD_SEG + i * 0x70 + SEG_POS) -= s;
    fw_regrid(pad, a1, a2, a3);
    if (on)
        for (int i = 0; i < 4; i++)
            if (pad[PAD_SEG + i * 0x70])
                *(int64_t *)(pad + PAD_SEG + i * 0x70 + SEG_POS) += s;
}

/* clip_read (filter.c): where the source ends for this pad (the selection's end, or the file's) */
int sel_end(const uint8_t *pad)
{
    int s, e;
    return pad_sel((uint8_t *)pad, &s, &e) ? e : 0x7fffffff;
}


/* ---- audition while stopped (SELECTION_WORKFLOW_RE.md 2) ---- */

typedef int (*block_fn)(uint8_t *pad, void **ctx, int a2, int a3);
typedef int (*param_fn)(uint8_t *pad, int a1, int a2, int a3);
#define fw_block    ((block_fn)FN(0x08067fa4))
#define fw_param    ((param_fn)FN(0x08067648))
#define PAD_QUANT   0x218         /* s64: Quant Size in ticks, 0 = None */
#define CLK_PLAYING 0x38

/*
 * The Clip pad's block (BL FUN_08067fa4 @0x08068c6a). With the transport stopped a synced clip only arms (the white
 * bar) until PLAY. Asked for (10-24): hear it while stopped. So while stopped, and not on a Slicer, this one block sees
 * Quant None and Sync off, which stock plays at once, at its own speed, looped; the real values are put back after.
 * On PLAY it carries on and falls into sync at its next slice / loop. A Quant / Sync change made during such a block
 * goes through sel_param, which lets the handler see and write the real values.
 */
int sel_block(uint8_t *pad, void **ctx, int a2, int a3)
{
    const uint8_t *clk = ctx ? (const uint8_t *)*ctx : 0;
    struct str_bank *b = stretch_bank();
    if (b && clk)
        b->tempo = *(const float *)(clk + CLK_TEMPO);   /* for the Waveform screen's Beats / BPM readout */
    if (!b || !clk || clk[CLK_PLAYING] || pad[PAD_SLICER])
        return fw_block(pad, ctx, a2, a3);
    struct str_audition *a = &b->aud;
    a->pad = pad;
    a->quant = *(int64_t *)(pad + PAD_QUANT);
    a->sync = pad[PAD_SYNC_ON];
    a->on = 1;
    *(int64_t *)(pad + PAD_QUANT) = 0;
    pad[PAD_SYNC_ON] = 0;
    int r = fw_block(pad, ctx, a2, a3);
    *(int64_t *)(pad + PAD_QUANT) = a->quant;
    pad[PAD_SYNC_ON] = a->sync;
    a->on = 0;
    return r;
}

/* The Clip pad's param handler (BL FUN_08067648 @0x080685d2), inside that block */
int sel_param(uint8_t *pad, int a1, int a2, int a3)
{
    struct str_bank *b = stretch_bank();
    if (!b || !b->aud.on || b->aud.pad != pad)
        return fw_param(pad, a1, a2, a3);
    struct str_audition *a = &b->aud;
    *(int64_t *)(pad + PAD_QUANT) = a->quant;
    pad[PAD_SYNC_ON] = a->sync;
    int r = fw_param(pad, a1, a2, a3);
    a->quant = *(int64_t *)(pad + PAD_QUANT);
    a->sync = pad[PAD_SYNC_ON];
    *(int64_t *)(pad + PAD_QUANT) = 0;
    pad[PAD_SYNC_ON] = 0;
    return r;
}

/* ---- knob acceleration on position knobs (SELECTION_WORKFLOW_RE.md 3) ---- */

static float log2_c(float x)                      /* bit trick + quadratic, error ~0.005 (compm.c's) */
{
    union { float f; uint32_t u; } v = {x};
    float e = (float)((int)((v.u >> 23) & 0xff) - 128);
    v.u = (v.u & 0x007fffffu) | 0x3f800000u;
    return e + (-0.34484843f * v.f + 2.02466578f) * v.f - 0.67487759f;
}

static float exp2_c(float x)
{
    if (x > 30.0f) x = 30.0f;
    if (x < -30.0f) return 0.0f;
    int i = (int)x - (x < 0.0f);
    float f = x - (float)i, p = 1.0f + f * (0.6565f + f * 0.3435f);
    union { float f; uint32_t u; } v = {p};
    v.u += (uint32_t)i << 23;
    return v.f;
}

typedef int (*accel_fn)(uint8_t *ring);
#define fw_accel    ((accel_fn)FN(0x080b0ce0))
#define KNOB_RING   0x294
#define KNOB_LO     0x14c
#define KNOB_HI     0x150
#define KNOB_SPP    0x28c         /* samples per step */
#define STEPS_TURN  20.0f         /* steps per knob turn at x1 (a guess: test_slice says 400 counts a step) */

/*
 * Stock's multiplier for a turning position knob (type 0xd: Start / End / Length / slice points), BL @0x080b0e88:
 * counts per ms over the last 8 readings, 1..6. Fine for a short sample, hopeless across a long one (a step is a
 * pixel of the waveform). Asked for (10-24): faster turns, bigger steps. Slow stays x1; full speed crosses the whole
 * range in about 1.5 turns; between them a square curve, so a medium turn is still controllable.
 */
int sel_accel(uint8_t *ring)
{
    int m = fw_accel(ring);
    if (m <= 1)
        return m;
    const uint8_t *knob = ring - KNOB_RING;
    int spp = *(const int32_t *)(knob + KNOB_SPP), lo = *(const int32_t *)(knob + KNOB_LO);
    int hi = *(const int32_t *)(knob + KNOB_HI);
    if (spp < 1)
        spp = 1;
    float steps = (float)(hi - lo) / (float)spp, top = steps / (3.0f * STEPS_TURN);
    if (top <= 6.0f || m <= 2)
        return m;
    /* m x (top / 6)^(((m - 2) / 4)^2): 3 -> ~1.4x stock, 4 -> ~4x, 5 -> ~25x, 6 -> full speed, about 3 turns across.
       (3.4.e's square curve jumped hundreds of steps on a gentle turn of a long file: glass test 10-25) */
    float x = (float)(m - 2) / 4.0f;
    int r = (int)((float)m * exp2_c(x * x * log2_c(top / 6.0f)) + 0.5f);
    return r > m ? r : m;
}


/* ---- tempo detection (tempo_dsp.c in bank 2): one job, a step per audio block ---- */

int b2_live(void);               /* cpu.c */

#define TEMPO_WAIT 4000          /* blocks (~20 s) a request waits for the pad's engine object before it fails */

/* stretch_tick, audio task, every block: start a job the screen asked for, or take its next step */
void sel_tempo_tick(struct str_bank *b)
{
    struct tempo_job *j = &b->tj;
    if (!b2_live())
        return;
    if (j->req != j->served) {
        int q = j->req_pad;
        uint8_t *eng = q >= 0 && q < 16 ? b->clip[q].eng : 0;
        void *obj = eng && (int)pad_index(eng) == q ? *(void **)(eng + PAD_SOURCE) : 0;   /* Clip or Slicer (ChopShop) */
        if (!obj) {
            /* setup has not run for this pad yet (3.4.g dropped the request here, silently): ask again next block */
            if (++j->misses < TEMPO_WAIT)
                return;
            j->served = j->req;
            j->pad = q;
            j->obj = 0;                                 /* take_tempo: "Fail 1" */
            j->state = TEMPO_FAILED;
            return;
        }
        j->served = j->req;
        /* tempo_start (bank 2) leaves these from the last job, and the job starts as SDRAM garbage at power-on: a stale
           loop flag makes the sweep score with the loop prior (the first detection after each boot: 129.4 for 194.5,
           read over USB 10-25). Cleared here so bank 2 stays as it is; move into tempo_start at the next bank 2 rewrite. */
        j->loop = 0;
        j->total = 0.0f;
        j->n_top = 0;
        j->idx = 0;
        j->cand = 0.0f;
        j->refine_hi = 0.0f;
        j->best_bpm = 0.0f;
        j->best_score = 0.0f;
        j->fetch = tempo_fw_fetch;
        j->misses = 0;
        tempo_start(j, q, obj, fw_src_len(obj), fw_src_rate(obj), fw_src_stereo(obj));
        return;
    }
    if (j->state > TEMPO_IDLE && j->state < TEMPO_DONE)
        tempo_step(j, b->scratch);
}

/* ---- the Waveform screen ---- */

typedef void (*text_fn)(void *text, const char *s);
#define fw_text_set ((text_fn)FN(0x080c3b98))
#define KNOB_TEXT   0x9c

static int sel_status(const uint8_t *knob);   /* below: 0 a set tempo, 1 detecting, 2 a guess, 10 + n failed */

/*
 * Every knob's value text goes through here (BL @0x080b06e4 in stock's formatter FUN_080b0528, which every value set
 * runs, changed or not). The BPM knob holds tenths; stock prints them as a whole number ("%ld"), so print "123.6"
 * instead (asked for 10-25), "~123.6" while Beats is Auto (stock's guess from the project tempo: 3.4.g showed it like a
 * detected tempo, glass test 10-25), "Detect.." while the detector runs for this pad, "Fail n" when it gave up. Beats 0
 * reads "Guess" (picked: stock's Beat Count on the Clip POS page already says "Auto"). Others: untouched.
 */
void sel_knob_text(void *text, const char *s)
{
    const uint8_t *knob = (const uint8_t *)text - KNOB_TEXT;
    int id = *(const int *)(knob + 0x14);
    if (id == 0x3e3) {                                  /* K_BEATS (defined below): knob 0 Detect, 1 Guess, n + 1 = n beats */
        int v = 0;
        for (const char *p = s; *p >= '0' && *p <= '9'; p++) v = v * 10 + (*p - '0');
        if (v < 2) {
            fw_text_set(text, v ? "Guess" : "Detect");   /* "Guess", not "Auto": stock's Beat Count says Auto (picked 10-25) */
            return;
        }
        char b[8];
        int i = 7;
        b[i] = 0;
        v--;
        do { b[--i] = (char)('0' + v % 10); v /= 10; } while (v && i);
        fw_text_set(text, b + i);
        return;
    }
    if (id == 0x161) {                                  /* ChopShop's Roll (chopmode.c): its cue, not the number */
        char buf[16];                                   /* the knob's view is not known here: the run's own pad (the
                                                           tick, chopmode.c, checks the view's pad every frame) */
        fw_text_set(text, chop_roll_text(CHOP_ANY_PAD, buf));
        return;
    }
    if (id != 0x3e4) {                                  /* K_BPM */
        fw_text_set(text, s);
        return;
    }
    int st = sel_status(knob);
    if (st == 1) {
        fw_text_set(text, "Detect..");
        return;
    }
    if (st >= 10) {
        char f[8] = "Fail 0";
        f[5] = (char)('0' + st - 10);
        fw_text_set(text, f);
        return;
    }
    int v = 0, neg = 0;
    const char *p = s;
    if (*p == '-') { neg = 1; p++; }
    while (*p >= '0' && *p <= '9') v = v * 10 + (*p++ - '0');
    char buf[16], tmp[12];
    int n = 0, w = v / 10, i = 0;
    if (st == 2) buf[n++] = '~';
    if (neg) buf[n++] = '-';
    do { tmp[i++] = (char)('0' + w % 10); w /= 10; } while (w && i < 11);
    while (i) buf[n++] = tmp[--i];
    buf[n++] = '.';
    buf[n++] = (char)('0' + v % 10);
    buf[n] = 0;
    fw_text_set(text, buf);
}

#define VIEW_WAVE     0x38
#define WAVE_DIRTY    0x32
#define WAVE_ZOOM     0x168
#define WAVE_PENDING  0x24c
#define WAVE_START    0x228
#define WAVE_LENGTH   0x234
#define WAVE_SHOW_SE  0x23a
#define VIEW_PAD      0x29c
#define VIEW_KNOB_TL  0x670
#define VIEW_KNOB_TR  0xc30
#define VIEW_KNOB_BL  0x950
#define VIEW_KNOB_BR  0xf10
#define VIEW_STORE    0x2370      /* the screen's copy of the pad's settings (FUN_080a54a0 reads 0x8b there) */
#define VIEW_LENGTH   0x2390
#define KNOB_PARAM    0x14
#define KNOB_STEP     0x28c
#define KNOB_TYPE_INT 1
#define KNOB_TYPE_POS 0xd
#define P_MODE        0x8b        /* 1 = Clip */
#define K_BEATS       0x3e3       /* private knob ids (slice.c has 0x3e0..0x3e2) */
#define K_BPM         0x3e4
#define MSG_PARAM     0x6e
#define MSG_TAG       0x080cfba4u

struct msg {
    uint16_t id, _r0;
    uint32_t tag;
    uint16_t pad, _r1;
    int32_t a, b;
    uint32_t c;
};

/* The screen's pad id (view + 0x29c) is the app's cell id, row << 4 | col (as solo.c's mixer cells; stock compares it
   with message cell ids @0x080a6c2c). NOT the engine's row << 8 | col: 3.4.e decoded it that way, so every pad off
   the bottom row asked about the wrong pad (no auto tempo, a wrong BPM readout: glass test 10-25). */
static int view_q(const uint8_t *view)
{
    uint16_t id = *(const uint16_t *)(view + VIEW_PAD);
    return ((id >> 4) & 3) * 4 + (id & 3);
}

/* Per-view state the knobs need between turns: Patch RAM is full, so it rides in the SDRAM area (by pad). The view's
   pad id: view_q. */
static struct str_clipinfo *info_for(uint8_t *view)
{
    struct str_bank *b = stretch_bank();
    return b ? &b->clip[view_q(view)] : 0;
}

/* the project tempo, as the engine's clock had it last block (sel_block); 120 until a Clip pad has run */
static float b_tempo(void)
{
    struct str_bank *b = stretch_bank();
    return b && b->tempo > 20.0f && b->tempo < 400.0f ? b->tempo : 120.0f;
}

/* Ask the audio side for this pad's tempo (sel_tempo_tick serves it; take_tempo applies it) */
static void ask_tempo(uint8_t *view)
{
    struct str_bank *b = stretch_bank();
    struct str_clipinfo *ci = info_for(view);
    if (!b || !ci)
        return;
    ci->fail = 0;
    b->tj.misses = 0;                                   /* the wait for the pad's engine starts again */
    b->tj.req_pad = view_q(view);
    b->tj.req++;
}

/* Beats as set (0 = Auto), the knob's copy while it turns, else the screen's store copy */
static int stored_beats(uint8_t *view)
{
    struct str_clipinfo *ci = info_for(view);
    return ci && ci->have ? ci->beats : fw_setting(view + VIEW_STORE, P_SEL_BEATS);
}

/* chop.c: a detection for pad q (Clip or Slicer), and its answer once it is there: 1 = bpm / phase (frames) / the file's
   rate set, -1 = it failed, 0 = not yet (or another pad's request replaced it). Taking it ends the job. */
void sel_ask_pad(int q)
{
    struct str_bank *b = stretch_bank();
    if (!b)
        return;
    b->tj.misses = 0;
    b->tj.req_pad = q;
    b->tj.req++;
}

int sel_take_pad(int q, float *bpm, float *phase, unsigned *frate)
{
    struct str_bank *b = stretch_bank();
    if (!b)
        return 0;
    struct tempo_job *j = &b->tj;
    if (j->served != j->req || j->pad != q || (j->state != TEMPO_DONE && j->state != TEMPO_FAILED))
        return 0;
    int ok = j->state == TEMPO_DONE && j->bpm > 0.0f;
    j->state = TEMPO_IDLE;
    *bpm = j->bpm;
    *phase = j->phase;
    *frate = j->frate;
    return ok ? 1 : -1;
}

/* sel_knob_text's BPM word for the pad on this view (the BPM knob is only ever bound on the Waveform screen) */
static int sel_status(const uint8_t *knob)
{
    uint8_t *view = (uint8_t *)knob - VIEW_KNOB_BR;
    struct str_bank *b = stretch_bank();
    struct str_clipinfo *ci = info_for(view);
    if (!b || !ci || stored_beats(view))
        return 0;                                       /* Beats set: a real tempo */
    const struct tempo_job *j = &b->tj;
    int q = view_q(view);
    if ((j->req != j->served && j->req_pad == q) || (j->req == j->served && j->pad == q && j->state > TEMPO_IDLE))
        return 1;                                       /* asked, running, or done and not yet taken */
    return ci->fail ? 10 + ci->fail : 2;
}

static int clip_mode(uint8_t *view)
{
    return fw_setting(view + VIEW_STORE, P_MODE) == 1;
}

static float view_zoom(uint8_t *view)
{
    float p = *(float *)(view + VIEW_WAVE + WAVE_PENDING);
    return p != 0.0f ? p : *(float *)(view + VIEW_WAVE + WAVE_ZOOM);
}

/* The view's selection as stored (s, e with e = the file end when unset), its Beats (explicit or guessed), its BPM x 10 */
static int end_set(uint8_t *view)              /* has End been set (else the section runs to the file's end)? */
{
    struct str_clipinfo *ci = info_for(view);
    int b = ci && ci->have ? ci->e : fw_setting(view + VIEW_STORE, P_SEL_END);
    return b > 0 && b < *(int32_t *)(view + VIEW_LENGTH);
}

static void view_sel(uint8_t *view, int *s, int *e, int *beats, int *bpm10)
{
    int len = *(int32_t *)(view + VIEW_LENGTH);
    int a = fw_setting(view + VIEW_STORE, P_SEL_START), b = fw_setting(view + VIEW_STORE, P_SEL_END);
    struct str_clipinfo *ci = info_for(view);
    if (ci && ci->have) { a = ci->s; b = ci->e; }             /* newer than the store copy while a knob turns */
    *s = a < 0 ? 0 : a > len ? len : a;
    *e = b <= 0 || b > len ? len : b;
    int n = *e - *s, bt = ci && ci->have ? ci->beats : fw_setting(view + VIEW_STORE, P_SEL_BEATS);
    unsigned frate = ci && ci->frate ? ci->frate : 48000u;
    if (bt <= 0)
        bt = auto_beats(n, frate, b_tempo());
    *beats = bt;
    *bpm10 = n > 0 && bt > 0 ? (int)((float)bt * 600.0f * (float)frate / (float)n + 0.5f) : 0;
}

static void show_pos(uint8_t *view, uint8_t *knob, int lo, int hi, int v)
{
    int step = (int)view_zoom(view);
    *(int *)(knob + KNOB_STEP) = step > 0 ? step : 1;
    fw_knob_range(knob, lo, hi);
    fw_knob_value(knob, v);
}

static void refresh(uint8_t *view)
{
    int s, e, beats, bpm10, len = *(int32_t *)(view + VIEW_LENGTH);
    view_sel(view, &s, &e, &beats, &bpm10);
    uint8_t *k;
    if (*(int *)((k = view + VIEW_KNOB_TL) + KNOB_PARAM) == P_SEL_START)
        /* End set: Start slides the section along (the tempo stays). End not set: Start moves on its own (a new clip:
           glass test 10-25, Start would not move until End had) */
        show_pos(view, k, 0, end_set(view) ? (len - (e - s) > 0 ? len - (e - s) : 0) : (len > SEL_MIN ? len - SEL_MIN : 0), s);
    if (*(int *)((k = view + VIEW_KNOB_TR) + KNOB_PARAM) == P_SEL_END)
        show_pos(view, k, s + SEL_MIN < len ? s + SEL_MIN : len, len, e);
    if (*(int *)((k = view + VIEW_KNOB_BL) + KNOB_PARAM) == K_BEATS) {
        /* the knob is the stored Beats + 1: 0 = Detect (turned to, it runs the detector), 1 = Auto. Stock's knob would
           not go below 0 on glass (3.4.j's -1 = Detect was unreachable, glass test 10-25), so no negative values. */
        fw_knob_range(k, 0, BEATS_MAX + 1);
        fw_knob_value(k, stored_beats(view) + 1);
    }
    if (*(int *)((k = view + VIEW_KNOB_BR) + KNOB_PARAM) == K_BPM) {
        fw_knob_range(k, 0, 99999);                     /* tenths: sel_knob_text shows "123.6" */
        fw_knob_value(k, bpm10);
    }
}

static void bind(uint8_t *knob, const char *label, int param, int type)
{
    fw_knob_reset(knob);
    fw_knob_label(knob, label);
    *(int *)(knob + KNOB_PARAM) = param;
    fw_knob_type(knob, type);
}

/* The four "unbind" calls of the Clip-mode setup (BL FUN_080a7ee0(0, 0, knob) @0x080a5806 / 12 / 1e / 2a) */
void sel_bind_start(int a, int b, uint8_t *knob)
{
    (void)a; (void)b;
    uint8_t *view = knob - VIEW_KNOB_TL;
    struct str_clipinfo *ci = info_for(view);
    if (ci)
        ci->have = 0;                                   /* a pad (re)opened: read the store again */
    bind(knob, "Start:", P_SEL_START, KNOB_TYPE_POS);
    /* no detection on open (decided 10-25: stock's own behaviour with the new stretch models is the default; the
       detector runs only when Beats is turned down to "Detect") */
    refresh(view);
}

void sel_bind_end(int a, int b, uint8_t *knob)
{
    (void)a; (void)b;
    bind(knob, "End:", P_SEL_END, KNOB_TYPE_POS);
    refresh(knob - VIEW_KNOB_TR);
}

void sel_bind_beats(int a, int b, uint8_t *knob)
{
    (void)a; (void)b;
    bind(knob, "Beats:", K_BEATS, KNOB_TYPE_INT);
    refresh(knob - VIEW_KNOB_BL);
}

void sel_bind_bpm(int a, int b, uint8_t *knob)
{
    (void)a; (void)b;
    bind(knob, "BPM:", K_BPM, KNOB_TYPE_INT);
    refresh(knob - VIEW_KNOB_BR);
}

/* A zoom change (BL FUN_080a52c4 @0x080a53b0): stock re-ranges its own knobs; ours step one pixel per detent too */
void sel_zoom(uint8_t *view, int z)
{
    fw_zoom_refresh(view, z);
    if (clip_mode(view))
        refresh(view);
}

/* Clip mode's waveform update (BL FUN_080c6e8c @0x080a5b0e): stock's slice markers, then the selection's Start / End */
static void post_new(uint8_t *view, int param, int value)
{
    struct msg m = {MSG_PARAM, 0, MSG_TAG, *(uint16_t *)(view + VIEW_PAD), 0, param, value, 0};
    fw_post(view, &m);
}

/* A finished detection for the pad on screen: beat one becomes Start, the whole beats after it the section. */
static void take_tempo(uint8_t *view)
{
    struct str_bank *b = stretch_bank();
    struct str_clipinfo *ci = info_for(view);
    if (!b || !ci)
        return;
    struct tempo_job *j = &b->tj;
    int q = view_q(view);
    if (j->served != j->req || j->pad != q || (j->state != TEMPO_DONE && j->state != TEMPO_FAILED))
        return;
    int ok = j->state == TEMPO_DONE;
    j->state = TEMPO_IDLE;                              /* taken */
    int s, e, beats, bpm10;
    view_sel(view, &s, &e, &beats, &bpm10);
    int len = *(int32_t *)(view + VIEW_LENGTH);
    if (s != 0 || e != len || stored_beats(view))
        return;                                         /* a knob moved while it ran: the user's settings stay (3.4.g overwrote them) */
    s = (int)j->phase;
    float fpb = ok && j->bpm > 0.0f ? (float)j->frate * 60.0f / j->bpm : 0.0f;
    int n = fpb >= 1.0f && s >= 0 && s < len ? (int)((float)(len - s) / fpb) : 0;
    if (n < 1) {
        /* 1: the pad's engine never showed up, 2: the file could not be read, 3: no tempo in it */
        ci->fail = !j->obj ? 1 : j->misses > 2000 ? 2 : 3;
        refresh(view);
        return;
    }
    if (n > SEL_BEATS_LONG && (float)len >= SEL_LONG_SECS * (float)j->frate)
        n = SEL_BEATS_LONG;                             /* a long file: a 4-bar section (a loop keeps the whole loop) */
    if (n > BEATS_MAX)
        n = BEATS_MAX;
    e = s + (int)((float)n * fpb + 0.5f);
    if (e > len)
        e = len;
    post_new(view, P_SEL_START, s);
    post_new(view, P_SEL_END, e);
    post_new(view, P_SEL_BEATS, n);
    ci->s = s;
    ci->e = e == len ? 0 : e;
    ci->beats = n;
    ci->have = 1;
    refresh(view);
    view[VIEW_WAVE + WAVE_DIRTY] = 1;
}

/*
 * Waveform view vtable slot 0 (word @0x080f0004): the per-frame tick (every GUI frame, ~60 Hz). The screen's update
 * (and sel_wave with it) runs only on events (a 0x66 for its pad, 0xd4), so 3.4.g / 3.4.h left a finished detection
 * waiting for one: "Detect.." until PLAY was pressed (glass test 10-25). Collect it here; then stock's tick, which picks up
 * the knobs' redraw.
 */
#define fw_wave_tick ((void (*)(uint8_t *, uint8_t *))FN(0x080a6f20))

void sel_view_tick(uint8_t *view, uint8_t *flags)
{
    if (clip_mode(view))
        take_tempo(view);
    fw_wave_tick(view, flags);
}

void sel_wave(uint8_t *wave, uint8_t *list)
{
    fw_wave_slices(wave, list);
    uint8_t *view = wave - VIEW_WAVE;
    take_tempo(view);
    int s, e, beats, bpm10, len = *(int32_t *)(view + VIEW_LENGTH);
    view_sel(view, &s, &e, &beats, &bpm10);
    if (s == 0 && e == len)
        return;                                         /* stock already cleared the Start / End flag */
    if (*(int32_t *)(wave + WAVE_START) != s || *(int32_t *)(wave + WAVE_LENGTH) != e - s || !wave[WAVE_SHOW_SE])
        wave[WAVE_DIRTY] = 1;
    *(int32_t *)(wave + WAVE_START) = s;
    *(int32_t *)(wave + WAVE_LENGTH) = e - s;
    wave[WAVE_SHOW_SE] = 1;
}

static void post_param(uint8_t *view, const struct msg *like, int param, int value)
{
    struct msg m = *like;
    m.a = param;
    m.b = value;
    fw_post(view, &m);
}

/*
 * slice.c's forward hook asks this first (the knob-change post @0x080a6c6c): 1 = handled. Start / End go to the
 * store as any knob does (Beats untouched); Beats and BPM are private knobs that write Beats.
 */
int sel_forward(uint8_t *view, struct msg *m)
{
    if (m->id != MSG_PARAM || (m->a != P_SEL_START && m->a != P_SEL_END && m->a != K_BEATS && m->a != K_BPM))
        return 0;
    int s, e, beats, bpm10, redetect = 0;
    view_sel(view, &s, &e, &beats, &bpm10);
    struct str_clipinfo *ci = info_for(view);
    if (m->a == P_SEL_START || m->a == P_SEL_END) {
        fw_post(view, m);
        if (m->a == P_SEL_START) {
            /* Start is where the clip begins and a beat: the section slides with it, so the tempo stays */
            int len = *(int32_t *)(view + VIEW_LENGTH);
            if (end_set(view)) {
                int ne = e + (m->b - s);
                if (ne > len) ne = len;
                if (ne != e)
                    post_param(view, m, P_SEL_END, ne);
                e = ne;
            }
            s = m->b;
        } else {
            e = m->b;
        }
        if (!stored_beats(view))
            beats = 0;                                  /* Auto stays Auto: the guess follows the new length */
    } else if (m->a == K_BEATS) {
        int len = *(int32_t *)(view + VIEW_LENGTH), v = m->b - 1;   /* the knob is Beats + 1 (refresh) */
        if (v == 0) {
            beats = 0;                                  /* Auto: stock's guess on the section (Start / End stay) */
        } else if (v < 0) {
            /* turned down past Auto to Detect: forget the section and run the detector (asked for 10-25: opt in) */
            if (s != 0)
                post_param(view, m, P_SEL_START, 0);
            if (e != len)
                post_param(view, m, P_SEL_END, 0);
            s = 0;
            e = len;
            beats = 0;
            redetect = 1;
        } else {
            /* the first turn up from Auto keeps the guess shown, then a beat a detent */
            beats = !stored_beats(view) ? (beats > 0 ? beats : 1) : v > BEATS_MAX ? BEATS_MAX : v;
        }
        post_param(view, m, P_SEL_BEATS, beats);
    } else {
        if (m->b > bpm10 && beats * 2 <= BEATS_MAX) beats *= 2;   /* one detent either way: x2 / /2 */
        else if (m->b < bpm10 && beats > 1) beats /= 2;
        post_param(view, m, P_SEL_BEATS, beats);
    }
    if (ci) {
        ci->s = s;
        ci->e = e == *(int32_t *)(view + VIEW_LENGTH) ? 0 : e;
        ci->beats = beats;
        ci->have = 1;
        ci->fail = 0;                                   /* a hand on it: no "Fail" left over */
    }
    if (redetect)
        ask_tempo(view);
    refresh(view);
    view[VIEW_WAVE + WAVE_DIRTY] = 1;
    return 1;
}

/*
 * A new sample on a pad clears its selection (asked for 10-25; held until the 3.4.e glass test). Start / End are frames
 * in the OLD file. Stock already resets its own Start / Length in one place, FUN_0809aa94 (cell, by mode): on a sample
 * assigned, a recording done, a fresh WAV header, a mode change, a pad rebuilt. Each of those calls comes here instead
 * (patches/slice.py), so the selection goes exactly when stock's Start / Length go, and never on a project load (the
 * loader calls it only for empty pads, FUN_0809cb4c @0x0809cb78, left alone). The next Waveform visit finds the pad
 * empty and runs the detector.
 */
typedef void (*cell_fn)(void *app, void *ref);
typedef void *(*cell_store_fn)(void *app, void *ref);
typedef void (*set_fn)(void *store, int param, int value);
#define fw_cell_reset ((cell_fn)FN(0x0809aa94))
#define fw_cell_store ((cell_store_fn)FN(0x08098d0c))
#define fw_set        ((set_fn)FN(0x08093ecc))  /* a no-op for an id the store does not have */

static void sel_clear(void *store, int row, int col)
{
    if (store) {
        fw_set(store, P_SEL_START, 0);
        fw_set(store, P_SEL_END, 0);
        fw_set(store, P_SEL_BEATS, 0);
    }
    struct str_bank *b = stretch_bank();
    if (b && row >= 0 && row < 4 && col >= 0 && col < 4) {
        struct str_clipinfo *ci = &b->clip[row * 4 + col];
        ci->have = 0;                                   /* the knobs read the (now empty) store again */
        ci->fail = 0;
    }
}

void chop_invariant(void *store);   /* chopmode.c: the ChopShop flag only lives on a Slicer */

void sel_reset_cell(void *app, void *ref)
{
    fw_cell_reset(app, ref);
    uint16_t id = *(const uint16_t *)((const uint8_t *)ref + 4);       /* row << 4 | col */
    void *store = fw_cell_store(app, ref);
    sel_clear(store, (id >> 4) & 0xf, id & 0xf);
    chop_invariant(store);
}

/*
 * The two places a pad gets a new sample WITHOUT FUN_0809aa94 (glass test 10-25: a new sample kept the old
 * Start / End / Beats): a sample assigned to a pad that already had one (FUN_080a0ac8 zeroes Start / Length itself,
 * BL @0x080a0b6c: 0x90 = 0), and a recording into a pad already in Clip mode (FUN_0809d418 writes 0x95 at its end,
 * BL @0x0809d686; @0x0809d622 is after a reset anyway). Stock's write, then the selection goes; the pad from the
 * store's address (app pad stores: APP_PADS + row * 0xf0 + col * 0x30).
 */
void sel_assign_clear(void *store, int param, int value)
{
    fw_set(store, param, value);
    uint32_t off = (uint32_t)store - APP_PADS;
    if (off % 0x30u == 0 && off / 0xf0u < 4)
        sel_clear(store, (int)(off / 0xf0u), (int)(off % 0xf0u / 0x30u));
}
