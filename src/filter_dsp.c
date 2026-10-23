/*
 * Pad crunch + Mutable Instruments-style state-variable filter. Original 1010music Blackbox, firmware 3.1.9.
 *
 * Stock: every voice runs its pad filter once per audio block (FUN_080762d8): one RBJ biquad, 12 dB/oct, low-pass
 * when the Filter knob is left of centre and high-pass when right of it, bypassed at centre. This replaces that
 * call (both pad classes) with:
 *   1. Crunch: the pad's Interp list gains seven entries after Normal / HighQ (16k down to 2k:
 *      on the test unit 26k / 20k were inaudible on bright material and 12k was where it started to bite). Each holds the
 *      voice's output at a lower sample rate (zero-order hold, no anti-aliasing: the old-sampler sound) and rounds
 *      it to 12 bits, before the filter, so the filter can tame the grit.
 *   2. Filter: 24 dB/oct, two of the trapezoidal state-variable filters from Emilie Gillet's stmlib (dsp/filter.h,
 *      class Svf; MIT licence, Copyright 2014 Emilie Gillet) in series: the first at a fixed Butterworth Q, the second
 *      carrying the Res knob. Cutoff and resonance go through the stock curves, so the Filter and Res knobs keep
 *      their ranges. Drive rides on Res: below the default (noon) the filter is clean; from noon to full the input is
 *      pushed into a soft clipper (up to +12 dB) and the resonant integrator is soft-limited, so high resonance
 *      growls and saturates instead of only getting louder.
 * The DSP half; filter.c has the hooks, which call in here only when bank 2 is live (stock's own filter and readers run
 * without it). Moved out of filter.c in 3.3.y so it lives in flash bank 2 (build.sh BANK2_SRCS): leaf DSP, no calls out
 * of bank 2 except to stock firmware; master_block()'s pointer comes in as mem.
 * State lives in the stock filter object, in the part only the stock process function used.
 * Stock firmware treats the new Interp values as HighQ, so presets stay loadable there.
 */
#include <stdint.h>
#include "filter.h"

#pragma GCC optimize("O2", "no-tree-loop-distribute-patterns")   /* per-sample loops run for every voice; no libc to call */

#define FN(addr) ((addr) | 1u)

typedef float (*curve_fn)(float x);
typedef float (*param_fn)(void *param);
typedef int (*buf_int_fn)(void *buf);
typedef int (*buf_chans_fn)(void *buf, float **left, float **right);

#define fw_cutoff_hz  ((curve_fn)FN(0x08060640))     /* knob 0..1 -> Hz */
#define fw_res_q      ((curve_fn)FN(0x080606c0))     /* Res 0..1 -> Q */
#define fw_param      ((param_fn)FN(0x0806fb30))     /* modulated parameter value */
#define fw_buf_silent ((buf_int_fn)FN(0x0804d8f4))
#define fw_buf_frames ((buf_int_fn)FN(0x0804d8e8))
#define fw_buf_chans  ((buf_chans_fn)FN(0x0804d944))

#define FS         48000.0f
#define PI_F       3.14159265f
#define OBJ_PARAMS 0x84          /* filter object -> its parameter block: Filter knob @+8, Res @+0x44 */

static const float crunch_rate[] = {16000.0f, 12000.0f, 10000.0f, 8000.0f, 6000.0f, 4000.0f, 2000.0f};
_Static_assert(sizeof crunch_rate / sizeof crunch_rate[0] == CRUNCHES, "filter.h: CRUNCHES");

/*
 * Machine modes: the old samplers' pitch path, not just their output rate.
 *   grid    the machine's sample rate. The voice reader (machine_read) plays the pad's sample as if it had been
 *           sampled at this rate: it reads the source only on that grid (after a 5-tap anti-alias FIR at 0.45 x grid),
 *           so pitching skips or doubles stored samples like the SP's carry-adder pitch logic, and the aliasing moves
 *           with the note. (A fixed-rate hold alone, the 16k..2k crunch, cannot do that.)
 *   hold    1: the DAC runs at the grid rate whatever the pitch (SP-1200, SP-12, MPC60): zero-order hold at grid
 *           after the voice.
 *   clocked 1: the S950, whose DAC clock IS the pitch (3.1.T, from its schematic and OS: src/s950.c). The reader
 *           clocks the stored samples out one by one with no interpolation, and the output stage is its 36 dB/oct
 *           low-pass, which follows the voice's clock (0.4 x) and tops out at 16 kHz. "S950" is the machine at its
 *           widest Audio bandwidth (19.2 kHz, 48 kHz samples), "S950 Lo" at 12.5 kHz (31.25 kHz samples): the
 *           lowest whose input filter the reader's five taps can still follow (host/check_s950.py).
 *   out     output stage, an RBJ low-pass {b0, b1, a1, a2} at 48 kHz (b2 = b0): SP-1200 12 kHz Q 1.25, SP-12
 *           12.5 kHz Q 1.2 (resonant: the steep-filter ring), MPC60 16 kHz Q 0.9.
 *   SP Raw  (3.1.n) SP1200 without the output filter, like the SP's unfiltered outputs 7-8: the hold's images and the
 *           pitched-down sizzle come straight through.
 * All 12-bit. The SP's SSM2044 outputs are the pad's own Filter knob (24 dB SVF with drive) after this.
 * Drive (3.1.n): in a machine mode the pad's Saturation knob is the converter input level instead of the warm saturation
 * (od.c stands aside for these pads): gain 1 + 7 d^2 (up to +18 dB) into a hard clip at the converter's full scale,
 * ahead of the hold and the 12 bits, then level back by 1 / (1 + 1.1 d^2): hitting the SP's inputs hot.
 * MPC60 is the least documented: 40 kHz 12-bit with the same skip/double pitch is a best guess.
 */
struct machine {
    float grid;
    uint8_t hold, clocked, raw;
    float fir[5];
    float out[4];
    float dac;                   /* the DAC's rate when it is not the grid (SP 45); 0 = the grid */
    float hold_at;               /* 3.3.k: where the converter's hold samples, in reader grid steps after the reader's
                                    phase at the voice's first frame (see hold_anchor). Grit depends on it by up to
                                    ~10 dB; these are the grittiest on average (his pick, 2026-10-17: "grittier is
                                    better"). Around 0.6 - 0.75 is the least grit. Back a machine off here. */
};
static const struct machine machines[] = {
    {26040.0f, 1, 0, 0, {0.00302f, 0.24563f, 0.5027f, 0.24563f, 0.00302f}, {0.357143f, 0.714286f, 0.0f, 0.428571f}, 0.0f, 0.45f},
    {27500.0f, 1, 0, 0, {-0.00396f, 0.24215f, 0.52363f, 0.24215f, -0.00396f}, {0.376262f, 0.752523f, 0.092392f, 0.412654f}, 0.0f, 0.45f},
    {48000.0f, 0, 1, 0, {-0.07796f, 0.18391f, 0.7881f, 0.18391f, -0.07796f}, {0.0f, 0.0f, 0.0f, 0.0f}, 0.0f, 0.0f}, /* S950 */
    {40000.0f, 1, 0, 0, {-0.03947f, 0.16746f, 0.74402f, 0.16746f, -0.03947f}, {0.506372f, 1.012744f, 0.675162f, 0.350325f}, 0.0f, 0.5f},
    {26040.0f, 1, 0, 1, {0.00302f, 0.24563f, 0.5027f, 0.24563f, 0.00302f}, {0.0f, 0.0f, 0.0f, 0.0f}, 0.0f, 0.45f}, /* SP Raw */
    {31250.0f, 0, 1, 0, {-0.06897f, 0.27256f, 0.59283f, 0.27256f, -0.06897f}, {0.0f, 0.0f, 0.0f, 0.0f}, 0.0f, 0.0f}, /* S950 Lo */
    /* SP 45 (3.1.X): the record sampled into an SP-1200 at 45 rpm and tuned back down to 33 1/3, per pad and
       without a new file. Sped up by 1.35 the sample is stored at 26.04 / 1.35 = 19.29 kHz of its own time (the
       reader's grid, with a five-tap input filter near 9 kHz); the machine then plays it 1.35 slower through its
       26.04 kHz converter (the hold) and its output filter, as on SP1200.
       3.2.b: moved here, beside the other machines (by request). A pad saved on one of the plain crunches 16k..2k
       before 3.2.b comes back one place down the list. */
    {26040.0f / 1.35f, 1, 0, 0, {0.05302f, 0.25399f, 0.38598f, 0.25399f, 0.05302f}, {0.357143f, 0.714286f, 0.0f, 0.428571f},
     26040.0f, 0.45f},
};
_Static_assert(sizeof machines / sizeof machines[0] == MACHINES, "filter.h: MACHINES");

static const struct machine *machine_for(unsigned interp)
{
    return interp >= FIRST_MACHINE && interp < FIRST_CRUNCH ? &machines[interp - FIRST_MACHINE] : 0;
}

struct fstate {                  /* at filter object +4..+0x48; the stock coefficient sets and states used to live here */
    uint32_t magic;
    float g, r, drive;           /* smoothed: SVF frequency coefficient, damping of the resonant stage, drive 0..1 */
    float s1[2][2], s2[2][2];    /* integrator states [stage][channel] */
    float phase, held[2];        /* crunch: hold phase and held sample per channel */
    uint32_t on;                 /* what ran last block: 0 off (Filter at 0), 1 low-pass, 2 high-pass (3.3.z) */
    float next;                  /* 3.3.k: the source position the voice's next block should start at (hold_anchor) */
};
_Static_assert(sizeof(struct fstate) <= 0x44, "filter object +4..+0x48");
#define MAGIC 0x53564635u        /* "SVF5": bumped with the layout (3.3.z: `on` became the mode) */
#define R_BUTTERWORTH 1.84776f   /* 1 / 0.5412: first stage of a 4-pole Butterworth */
#define SMOOTH 0.33333f          /* per-block coefficient smoothing, as the stock filter */

/* tan(x) for 0 <= x < 1.45, Pade (3,2); 3% low at the top of the range, exact enough below. */
static float tan_approx(float x)
{
    float x2 = x * x;
    return x * (15.0f - x2) / (15.0f - 6.0f * x2);
}

static float quantize12(float x)
{
    float s = x * 2048.0f;
    int i = (int)(s + (s >= 0.0f ? 0.5f : -0.5f));
    return (float)i * (1.0f / 2048.0f);
}

/*
 * Output stage of a machine mode. State in the filter object at +0x60..+0x73, which only the stock process (replaced)
 * and its coefficient helper FUN_0807612c (called only from it) used; cleared with the filter's own state.
 *   rate  the voice's playback rate. Sample pads: written by voice_read_a (filter_thunk.S) on every read; the filter
 *         object is the voice + 0xa8 and the read comes first in the same function (FUN_08056fd0). Clip / slicer
 *         pads: written by clip_read; the filter object is that voice's object + 0x14c (clip_read_b).
 *   z     the SP / MPC60 low-pass; in an S950 mode z[0][0] holds the voice's slot in the S950 bank instead (a small
 *         integer: read back as a float it is as good as zero).
 */
struct ostate {
    float rate;
    union {
        float z[2][2];
        uint32_t slot;
    };
};

static void out_stage(uint8_t *obj, float **ch, int n, const float *c)
{
    struct ostate *o = (struct ostate *)(obj + 0x60);
    float b0 = c[0], b1 = c[1], a1 = c[2], a2 = c[3];
    for (int k = 0; k < 2; k++) {
        float *x = ch[k];
        if (!x)
            continue;
        float z1 = o->z[k][0], z2 = o->z[k][1];
        for (int i = 0; i < n; i++) {                       /* transposed direct form II */
            float in = x[i], y = b0 * in + z1;
            z1 = b1 * in - a1 * y + z2;
            z2 = b0 * in - a2 * y;
            x[i] = y;
        }
        o->z[k][0] = z1;
        o->z[k][1] = z2;
    }
}

/*
 * The S950's low-pass needs six values per channel, more than the filter object has spare: they live in SDRAM, in the
 * block master.c takes at boot (behind Prism's, the LFOs' and the USB ring), a slot per filter object that ever ran
 * an S950 mode. No block or no slot left = that voice goes without the low-pass.
 */
void s950_read(float grid, const float *fir, int32_t base, float sgn, float gain, float post, float rate,
               const float *src, int n_src, int pos, int *newpos, float *frac, float *dst, int n);
unsigned s950_filter_count(float clock, unsigned index);
void s950_filter(float *z, float **ch, int n, unsigned count);

#define S9_OFFSET (0x56800u + 0x7000u)
#define S9_SLOTS  256
#define S9_MAGIC  0x53393530u    /* "S950" */
struct s9_slot {
    const uint8_t *obj;
    float z[12];
};
struct s9_bank {
    uint32_t magic, used;
    struct s9_slot slot[S9_SLOTS];
};
_Static_assert(sizeof(struct s9_bank) <= 0x4000, "master.c's EXTRA_BYTES gives the bank 0x4000");

static float *s950_state(const uint8_t *obj, struct ostate *o, uint8_t *mem)
{
    if (!mem)
        return 0;
    struct s9_bank *b = (struct s9_bank *)(mem + S9_OFFSET);
    if (b->magic != S9_MAGIC) {
        b->used = 0;
        b->magic = S9_MAGIC;
    }
    uint32_t i = o->slot;
    if (i < b->used && b->slot[i].obj == obj)
        return b->slot[i].z;
    for (i = 0; i < b->used && b->slot[i].obj != obj; i++)   /* back from another mode, which used z as its own */
        ;
    if (i == b->used) {
        if (i >= S9_SLOTS)
            return 0;
        b->slot[i].obj = obj;
        b->used = i + 1;
    }
    for (int k = 0; k < 12; k++)
        b->slot[i].z[k] = 0.0f;
    o->slot = i;
    return b->slot[i].z;
}

/*
 * 3.3.k: the hold, anchored to the reader. A machine voice is read on the machine's grid (machine_read, anchored on the
 * sample) and then held by the converter (crunch, at the DAC's rate). Up to 3.3.j the hold's phase ran free in the
 * filter object, so each new note met the reader's grid at whatever offset the last one left: at the original pitch a
 * 128-frame block is 73 1/3 SP-12 steps, so one of three, and the grit between them differs by 7 dB (measured on his
 * unit: the same slice retriggered came out at -16 / -18 / -23 dB). Now the reader leaves its grid phase at the voice's
 * first frame here, and when a voice starts somewhere new (not where its last block ended) its hold starts at
 * machine.hold_at steps after that phase. Every hit of the same sound at the same pitch is then the same.
 * In SDRAM, between the S950 bank and SLICE_DIAG's block. Written by the voice's first read in a block (class A: the
 * voice reader's kernels; class B: the segment reader), taken by that voice's filter call, which comes next.
 */
struct hold_stash {
    const uint8_t *pad;
    uint32_t valid;              /* HS_VALID when written and not yet taken; anything else (boot garbage too) = empty */
    float gp0;                   /* reader grid position at the first frame, in steps */
    float at;                    /* source position of the first frame */
    float adv;                   /* source samples per output frame, signed */
};
#define HS_OFFSET (S9_OFFSET + 0x3700u)
#define HS_VALID  0x484f4c44u    /* "HOLD" */
_Static_assert(sizeof(struct s9_bank) <= 0x3700, "the hold stash sits behind the S950 bank");

static volatile struct hold_stash *hold_stash(uint8_t *mem)
{
    return mem ? (volatile struct hold_stash *)(mem + HS_OFFSET) : 0;
}

static inline float frac_f(float x)
{
    int i = (int)x;
    float f = x - (float)i;
    return f < 0.0f ? f + 1.0f : f;
}

static void crunch(struct fstate *st, float **ch, int n, float rate)
{
    float step = rate / FS, phase = st->phase;
    float held0 = st->held[0], held1 = st->held[1];
    for (int i = 0; i < n; i++) {
        phase += step;
        if (phase >= 1.0f) {
            phase -= 1.0f;
            held0 = quantize12(ch[0][i]);
            if (ch[1])
                held1 = quantize12(ch[1][i]);
        }
        ch[0][i] = held0;
        if (ch[1])
            ch[1][i] = held1;
    }
    st->phase = phase;
    st->held[0] = held0;
    st->held[1] = held1;
}

/* Soft clip, unity gain at zero, flat at |x| = 1.5 t, ceiling t: t * (u - 4/27 u^3), u = x / t. */
static inline __attribute__((always_inline)) float soft(float x, float inv_t, float t)
{
    float u = x * inv_t;
    u = u > 1.5f ? 1.5f : u < -1.5f ? -1.5f : u;
    return t * u * (1.0f - 0.148148f * u * u);
}

/*
 * stmlib Svf::Process<FILTER_MODE_LOW_PASS / HIGH_PASS> for one channel with coefficients fixed for the block.
 * CLIP: soft-limit the band-pass integrator (the resonant loop); only used on the resonant stage while driven.
 */
#define SVF_LOOP(OUT, NEXT_S1)                                                                                     \
    for (int i = 0; i < n; i++) {                                                                                  \
        float hp = (x[i] - rg * s1 - s2) * h;                                                                      \
        float bp = g * hp + s1;                                                                                    \
        s1 = NEXT_S1;                                                                                              \
        float lp = g * bp + s2;                                                                                    \
        s2 = g * bp + lp;                                                                                          \
        x[i] = OUT;                                                                                                \
    }

static void svf(float *x, int n, float g, float r, float *s1p, float *s2p, int highpass, float limit)
{
    float h = 1.0f / (1.0f + r * g + g * g), rg = r + g, s1 = *s1p, s2 = *s2p;
    if (limit > 0.0f) {
        float inv = 1.0f / limit;
        if (highpass)
            SVF_LOOP(hp, soft(g * hp + bp, inv, limit))
        else
            SVF_LOOP(lp, soft(g * hp + bp, inv, limit))
    } else if (highpass) {
        SVF_LOOP(hp, g * hp + bp)
    } else {
        SVF_LOOP(lp, g * hp + bp)
    }
    *s1p = s1;
    *s2p = s2;
}

static void drive_in(float *x, int n, float amount)
{
    float pre = 1.0f + 3.0f * amount;
    for (int i = 0; i < n; i++)
        x[i] = soft(x[i] * pre, 1.0f, 1.0f);
}

/*
 * The pad's Interp setting, read from the app's record of the pad (what the screen shows and presets save), not from
 * the engine's copy: the engine's pad reset (FUN_080596b0, the block that zeroes +0x550..+0x582) sets its copy back to
 * Normal, which in 3.1.d-f made the crunch drop out a moment after each change.
 * Engine pad id (pad +0x18) = bank << 16 | row << 8 | col; app pad record = app + 0x1840 + row * 0xf0 + col * 0x30
 * (FUN_08098d0c), searched with the stock store lookup FUN_08093e9c.
 */
typedef int (*setting_fn)(const void *store, unsigned param);
#define fw_setting ((setting_fn)FN(0x08093e9c))
#define APP_PADS   (0x24020088u + 0x1840u)

/*
 * 3.3.l: where Fidelity (0xf1) and Saturation (0xdb) sit in each pad's store, remembered. Every voice looks them up
 * several times per 128-frame chunk (the readers, the filter call, Saturation), and stock's lookup FUN_08093e9c walks
 * the store from the top: both are about 40 entries in, ~280 instructions a look, ~12 per frame per voice. The value
 * is still read live every time; only the position is remembered, and it is checked (the entry there must carry the
 * id) before it is trusted, so a stale or garbage table costs a search, never a wrong value. 20 pads x 2 = 40 bytes in
 * the SDRAM block, after the hold stash.
 */
#define PS_OFFSET (S9_OFFSET + 0x3720u)
_Static_assert(0x3720 + 40 <= 0x3800, "below SLICE_DIAG's block");

static unsigned pad_setting(const uint8_t *pad, unsigned param, uint8_t *mem)
{
    if (!pad)
        return 0;
    uint32_t id = *(const uint32_t *)(pad + 0x18);
    unsigned row = (id >> 8) & 0xff, col = id & 0xff;
    if (row >= 4 || col >= 5)
        return 0;
    const uint8_t *store = (const uint8_t *)(APP_PADS + row * 0xf0u + col * 0x30u);
    const uint8_t *ent = *(const uint8_t *const *)(store + 4);
    unsigned count = *(const uint16_t *)(store + 10);
    if (param != 0xf1 && param != 0xdb)
        mem = 0;
    if (!mem || !ent)
        return (unsigned)fw_setting(store, param);
    uint8_t *at = mem + PS_OFFSET + (row * 5 + col) * 2 + (param == 0xdb);
    unsigned i = *at;
    if (i < count && *(const uint16_t *)(ent + i * 8) == param)
        return *(const uint32_t *)(ent + i * 8 + 4);
    for (i = 0; i < count; i++)                  /* stock's walk (same entry layout: id at +0, value at +4) */
        if (*(const uint16_t *)(ent + i * 8) == param) {
            *at = (uint8_t)(i < 255 ? i : 255);
            return *(const uint32_t *)(ent + i * 8 + 4);
        }
    return 0;
}

static unsigned pad_interp(const uint8_t *pad, uint8_t *mem)
{
    return pad_setting(pad, 0xf1, mem);
}

/* Saturation into the converter: gain, hard clip at full scale, level back */
static void adc_drive(float **ch, int n, float d)
{
    float gain = 1.0f + 7.0f * d * d;
    /* level back: a hard-clipped loud loop at full drive (+18 dB) lands near its original RMS (0.48 x a full-scale
       square vs a 0.8 sine); quiet material that never reaches the ceiling comes out louder, as with a hot SP input */
    float post = 1.0f / (1.0f + 1.1f * d * d);
    for (int k = 0; k < 2; k++) {
        float *x = ch[k];
        if (!x)
            continue;
        for (int i = 0; i < n; i++) {
            float v = x[i] * gain;
            v = v > 1.0f ? 1.0f : v < -1.0f ? -1.0f : v;
            x[i] = v * post;
        }
    }
}

/* drive, then the two state-variable stages, in place, with the smoothed coefficients in st */
static void run(struct fstate *st, float **ch, int n, int hp)
{
    /* resonant stage ceiling: off below noon (clean, linear), from 4 down to 1 as drive rises */
    float limit = st->drive > 0.001f ? 4.0f - 3.0f * st->drive : 0.0f;
    for (int c = 0; c < 2; c++) {
        if (!ch[c])
            continue;
        if (st->drive > 0.001f)
            drive_in(ch[c], n, st->drive);
        svf(ch[c], n, st->g, R_BUTTERWORTH, &st->s1[0][c], &st->s2[0][c], hp, 0.0f);
        svf(ch[c], n, st->g, st->r, &st->s1[1][c], &st->s2[1][c], hp, limit);
    }
}

/* The per-voice filter: filter_process (filter.c) with bank 2 live. pad = the pad object the voice belongs to. */
void filt_block(uint8_t *obj, void *buf, const uint8_t *pad, uint8_t *mem)
{
    /* the reader's note for this voice, if it read through a machine this block (taken even if nothing plays) */
    volatile struct hold_stash *hs = hold_stash(mem);
    int anchor = 0;
    float gp0 = 0.0f, at = 0.0f, adv = 0.0f;
    if (hs && hs->valid == HS_VALID) {
        if (hs->pad == pad) {
            anchor = 1;
            gp0 = hs->gp0;
            at = hs->at;
            adv = hs->adv;
        }
        hs->valid = 0;
    }
    if (fw_buf_silent(buf)) {
        return;
    }
    struct fstate *st = (struct fstate *)(obj + 4);
    struct ostate *o = (struct ostate *)(obj + 0x60);
    if (st->magic != MAGIC) {
        uint32_t *w = (uint32_t *)st;
        for (unsigned i = 0; i < sizeof *st / 4; i++)
            w[i] = 0;
        o->z[0][0] = o->z[0][1] = o->z[1][0] = o->z[1][1] = 0.0f;
        st->next = -1.0e9f;                                  /* no voice yet: the first one anchors */
        st->magic = MAGIC;
    }
    unsigned interp = pad_interp(pad, mem);
    int crunching = interp >= FIRST_MACHINE && interp < INTERPS;
    uint8_t *params = *(uint8_t **)(obj + OBJ_PARAMS);
    float knob = params ? fw_param(params + 8) : 0.0f;
    if (knob == 0.0f && !st->on && !crunching)
        return;                                              /* centred, and was: nothing to do */

    float *ch[2] = {0, 0};
    int n = fw_buf_frames(buf);
    fw_buf_chans(buf, &ch[0], &ch[1]);
    if (!ch[0] || n <= 0)
        return;
    const struct machine *m = machine_for(interp);
    if (m) {
        float d = (float)pad_setting(pad, 0xdb, mem) * 0.001f;
        /* S950: the reader already drove, rounded and clocked out the stored samples (s950_read) and left its rate.
           A rate that makes no sense = no reader ran for this object: do the 12 bits here, as 3.1.T did for clips. */
        float rate = o->rate < 0.0f ? -o->rate : o->rate;
        int read = m->clocked && rate > 0.01f && rate < 64.0f;
        if (!read) {
            rate = 1.0f;
            if (d > 0.0f)
                adc_drive(ch, n, d > 1.0f ? 1.0f : d);
            if (m->hold || m->grid < FS) {
                float hr = m->dac > 0.0f ? m->dac : m->grid;
                if (anchor) {
                    float d = at - st->next;
                    if (!(d <= 2.0f && d >= -2.0f)) {       /* a new note: start the hold hold_at steps after the grid */
                        st->phase = frac_f(gp0 - hr * (1.0f / FS) + m->hold_at);
                        st->held[0] = st->held[1] = 0.0f;
                    }
                    st->next = at + adv * (float)n;
                }
                crunch(st, ch, n, hr);
            } else {
                for (int k = 0; k < 2; k++)
                    if (ch[k])
                        for (int i = 0; i < n; i++)
                            ch[k][i] = quantize12(ch[k][i]);
            }
        }
        if (m->clocked) {
            float *z = s950_state(obj, o, mem);
            if (z)
                s950_filter(z, ch, n, s950_filter_count(m->grid * rate, 168));
        } else if (!m->raw) {
            out_stage(obj, ch, n, m->out);
        }
    } else if (crunching) {
        crunch(st, ch, n, crunch_rate[interp - FIRST_CRUNCH]);
    }
    /*
     * 3.3.z: THE POP AT THE CENTRE. Filter at 0 = off; left of it low-pass, right of it high-pass. Up to 3.3.y a switch
     * happened in one sample: off -> on started the filter from zero states (a low-pass then begins at 0 while the
     * input is mid-wave: a step), and a jump from one side to the other between blocks (an LFO does that every cycle)
     * swapped one output for the other. Measured on a 110 Hz sine: steps 3x and 80x the sine's own. Now a switch is
     * one block's crossfade from what ran to what runs, and a low-pass starts from the input's own level.
     */
    int mode = knob == 0.0f ? 0 : knob > 0.0f ? 2 : 1, was = st->on <= 2 ? (int)st->on : 0;
    float g = 0.0f, r = 0.0f, drive = 0.0f;
    if (mode) {
        float hz = fw_cutoff_hz(knob < 0.0f ? knob + 1.0f : knob);
        float res = fw_param(params + 0x44);
        float q = fw_res_q(res);
        drive = (res - 0.5f) * 2.0f;                            /* 0 up to the default Res, 1 at full */
        drive = drive < 0.0f ? 0.0f : drive > 1.0f ? 1.0f : drive * drive;
        if (hz < 10.0f)
            hz = 10.0f;
        if (hz > 0.45f * FS)
            hz = 0.45f * FS;
        if (!(q > 0.1f))
            q = 0.1f;                                            /* the stock curve's own minimum (Res at 0) */
        if (q > 40.0f)
            q = 40.0f;
        g = tan_approx(PI_F * hz / FS);
        r = 1.0f / q;
    }
    if (mode == was) {                                           /* the usual block: the same side as last time */
        if (!mode)
            return;
        st->g += SMOOTH * (g - st->g);
        st->r += SMOOTH * (r - st->r);
        st->drive += SMOOTH * (drive - st->drive);
        run(st, ch, n, mode == 2);
        return;
    }
    float *xf = mem && n <= XF_FRAMES ? (float *)(mem + XF_OFFSET) : 0;
    float *dry[2] = {0, 0};
    if (xf)
        for (int c = 0; c < 2; c++)
            if (ch[c]) {
                dry[c] = xf + c * XF_FRAMES;
                for (int i = 0; i < n; i++)
                    dry[c][i] = ch[c][i];
            }
    if (was && xf)
        run(st, ch, n, was == 2);                                /* what ran: its own states carry on, into ch (if it
                                                                    was off, ch is the dry signal already) */
    if (mode) {                                                  /* what runs now, from a clean start */
        st->g = g;
        st->r = r;
        st->drive = drive;
        float **in = xf ? dry : ch;
        for (int c = 0; c < 2; c++) {
            float x0 = in[c] ? in[c][0] : 0.0f, lp = mode == 1 ? x0 : 0.0f;
            st->s1[0][c] = st->s1[1][c] = 0.0f;
            st->s2[0][c] = st->s2[1][c] = lp;                    /* a low-pass's state at rest on the input level */
        }
        run(st, in, n, mode == 2);
    }
    st->on = (uint32_t)mode;
    if (!xf)
        return;                                                  /* no scratch block: switched without the fade */
    float step = 1.0f / (float)n;
    for (int c = 0; c < 2; c++) {                                /* ch = what ran -> (dry or what runs), S-curve: */
        if (!ch[c])                                              /* no corner at either end (a straight fade left one) */
            continue;
        float t = 0.0f;
        for (int i = 0; i < n; i++) {
            t += step;
            ch[c][i] += t * t * (3.0f - 2.0f * t) * (dry[c][i] - ch[c][i]);
        }
    }
}


typedef void (*kernel_fn)(float rate, const float *src, int n_src, int pos, int *newpos, float *frac, float *dst,
                          int n);
#define fw_kernel_normal ((kernel_fn)FN(0x080619d0))
#define fw_kernel_hq     ((kernel_fn)FN(0x08061a64))

static inline float floor_f(float x)
{
    int i = (int)x;
    return (float)(i - (x < (float)i));
}

static inline int round_i(float x)
{
    return (int)(x + (x >= 0.0f ? 0.5f : -0.5f));
}

static void machine_read(const struct machine *m, uint8_t *mem, float rate, const float *src, int n_src, int pos, int *newpos,
                         float *frac, float *dst, int n)
{
    /* scratch index -> absolute source position. Forward: scratch[0] = source[P - 4]. Reverse: FUN_08055f0c fetched
       from round(P) - n_src + 4 and reversed the buffer, so scratch[j] = source[round(P) + 3 - j]. */
    int32_t base = PARK->pos - 4;
    float sgn = 1.0f;
    if (PARK->rate < 0.0f) {
        sgn = -1.0f;
        base = PARK->pos + 3;            /* FUN_08055f0c rounds a float that already holds an integer */
    }
    if (m->clocked) {
        float d = (float)pad_setting(PARK->pad, 0xdb, mem) * 0.001f;
        d = d > 1.0f ? 1.0f : d;
        s950_read(m->grid, m->fir, base, sgn, 1.0f + 7.0f * d * d, 1.0f / (1.0f + 1.1f * d * d), rate, src, n_src, pos,
                  newpos, frac, dst, n);
        return;
    }
    /* Keep the per-frame maths small: a float holds a sample position 2.9 M samples (60 s) in to only 0.25 of a
       sample. Anchor once per call in double (the M7 FPU has it), then work relative to the grid point below. */
    double gd = 48000.0 / (double)m->grid;
    double kb = (double)(int32_t)((double)base / gd);
    if (kb * gd > (double)base)
        kb -= 1.0;
    float a0 = (float)((double)base - kb * gd);      /* 0 <= a0 < g: where the scratch sits on the grid */
    float g = (float)gd, inv_g = m->grid * (1.0f / 48000.0f);
    const float *h = m->fir;
    int hi = n_src - 3;
    float f = *frac;
    int idx = pos;
    volatile struct hold_stash *hs = hold_stash(mem);
    if (hs && hs->valid != HS_VALID) {                   /* the voice's first read this block: for hold_anchor */
        hs->pad = PARK->pad;
        hs->gp0 = frac_f((a0 + sgn * ((float)idx + f)) * inv_g + (1.0f / 8192.0f));
        hs->at = (float)base + sgn * ((float)idx + f);
        hs->adv = sgn * rate;
        hs->valid = HS_VALID;
    }
    for (int i = 0; i < n; i++) {
        /* + 1/8192 of a grid step: a reading point exactly on a grid line (a clip at its original pitch on the 40 kHz
           grid is, every sixth frame) would otherwise fall to either side by rounding */
        float gp = (a0 + sgn * ((float)idx + f)) * inv_g + (1.0f / 8192.0f), k0 = floor_f(gp);
        int j0 = round_i(sgn * (k0 * g - a0));
        j0 = j0 < 2 ? 2 : j0 > hi ? hi : j0;
        const float *s = src + j0;
        dst[i] = h[0] * s[-2] + h[1] * s[-1] + h[2] * s[0] + h[3] * s[1] + h[4] * s[2];
        float adv = rate + f;
        int step = (int)adv;
        idx += step;
        f = adv - (float)step;
    }
    *frac = f;
    *newpos = idx;                       /* the stock kernels return (pointer - src) + 1, pointer = src + idx - 1 */
}


/* ---- what filter.c calls (with bank 2 live) ---- */

unsigned filt_interp(const uint8_t *pad, uint8_t *mem)
{
    return pad_interp(pad, mem);
}

const struct machine *filt_machine(const uint8_t *pad, uint8_t *mem)
{
    return machine_for(pad_interp(pad, mem));
}

void filt_read(const struct machine *m, uint8_t *mem, float rate, const float *src, int n_src, int pos, int *newpos,
               float *frac, float *dst, int n)
{
    machine_read(m, mem, rate, src, n_src, pos, newpos, frac, dst, n);
}
