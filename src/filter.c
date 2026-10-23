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
 * State lives in the stock filter object, in the part only the stock process function used.
 * Stock firmware treats the new Interp values as HighQ, so presets stay loadable there.
 */
#include <stdint.h>

#pragma GCC optimize("O2", "no-tree-loop-distribute-patterns")   /* per-sample loops run for every voice; no libc to call */

#define FN(addr) ((addr) | 1u)

typedef float (*curve_fn)(float x);
typedef float (*param_fn)(void *param);
typedef int (*buf_int_fn)(void *buf);
typedef int (*buf_chans_fn)(void *buf, float **left, float **right);
typedef void (*register_fn)(void *table, int param, const char *label, const char *const *names, int count,
                            const char *xml);

#define fw_cutoff_hz  ((curve_fn)FN(0x08060640))     /* knob 0..1 -> Hz */
#define fw_res_q      ((curve_fn)FN(0x080606c0))     /* Res 0..1 -> Q */
#define fw_param      ((param_fn)FN(0x0806fb30))     /* modulated parameter value */
#define fw_buf_silent ((buf_int_fn)FN(0x0804d8f4))
#define fw_buf_frames ((buf_int_fn)FN(0x0804d8e8))
#define fw_buf_chans  ((buf_chans_fn)FN(0x0804d944))
#define fw_register_list ((register_fn)FN(0x0808c0d8))

#define FS         48000.0f
#define PI_F       3.14159265f
#define OBJ_PARAMS 0x84          /* filter object -> its parameter block: Filter knob @+8, Res @+0x44 */

static const float crunch_rate[] = {16000.0f, 12000.0f, 10000.0f, 8000.0f, 6000.0f, 4000.0f, 2000.0f};
#define CRUNCHES ((int)(sizeof crunch_rate / sizeof crunch_rate[0]))
#define STOCK_INTERP 2           /* Normal, HighQ */

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
};
static const struct machine machines[] = {
    {26040.0f, 1, 0, 0, {0.00302f, 0.24563f, 0.5027f, 0.24563f, 0.00302f}, {0.357143f, 0.714286f, 0.0f, 0.428571f}, 0.0f},
    {27500.0f, 1, 0, 0, {-0.00396f, 0.24215f, 0.52363f, 0.24215f, -0.00396f}, {0.376262f, 0.752523f, 0.092392f, 0.412654f}, 0.0f},
    {48000.0f, 0, 1, 0, {-0.07796f, 0.18391f, 0.7881f, 0.18391f, -0.07796f}, {0.0f, 0.0f, 0.0f, 0.0f}, 0.0f},      /* S950 */
    {40000.0f, 1, 0, 0, {-0.03947f, 0.16746f, 0.74402f, 0.16746f, -0.03947f}, {0.506372f, 1.012744f, 0.675162f, 0.350325f}, 0.0f},
    {26040.0f, 1, 0, 1, {0.00302f, 0.24563f, 0.5027f, 0.24563f, 0.00302f}, {0.0f, 0.0f, 0.0f, 0.0f}, 0.0f},     /* SP Raw */
    {31250.0f, 0, 1, 0, {-0.06897f, 0.27256f, 0.59283f, 0.27256f, -0.06897f}, {0.0f, 0.0f, 0.0f, 0.0f}, 0.0f},  /* S950 Lo */
    /* SP 45 (3.1.X): the record sampled into an SP-1200 at 45 rpm and tuned back down to 33 1/3, per pad and
       without a new file. Sped up by 1.35 the sample is stored at 26.04 / 1.35 = 19.29 kHz of its own time (the
       reader's grid, with a five-tap input filter near 9 kHz); the machine then plays it 1.35 slower through its
       26.04 kHz converter (the hold) and its output filter, as on SP1200.
       3.2.b: moved here, beside the other machines (by request). A pad saved on one of the plain crunches 16k..2k
       before 3.2.b comes back one place down the list. */
    {26040.0f / 1.35f, 1, 0, 0, {0.05302f, 0.25399f, 0.38598f, 0.25399f, 0.05302f}, {0.357143f, 0.714286f, 0.0f, 0.428571f},
     26040.0f},
};
#define MACHINES ((int)(sizeof machines / sizeof machines[0]))
#define FIRST_MACHINE STOCK_INTERP                      /* the order asked for (3.1.n): machines before the plain crunches */
#define FIRST_CRUNCH  (FIRST_MACHINE + MACHINES)
#define INTERPS       (FIRST_CRUNCH + CRUNCHES)

static const struct machine *machine_for(unsigned interp)
{
    return interp >= FIRST_MACHINE && interp < FIRST_CRUNCH ? &machines[interp - FIRST_MACHINE] : 0;
}

/*
 * S950 Lo (3.1.T) has the list place the S1000 mode had (3.1.u - 3.1.S: an eight-point sinc re-pitch, taken out for
 * its 2.3 KB), so every saved Fidelity value keeps its meaning except a pad left on S1000, which is now S950 Lo.
 */

const char *const interp_names[INTERPS] = {
    (const char *)0x080cd770u, (const char *)0x080cd778u,       /* Normal, HighQ */
    "SP1200", "SP-12", "S950", "MPC60", "SP Raw", "S950 Lo", "SP 45",
    "16k", "12k", "10k", "8k", "6k", "4k", "2k",
};

/* Replaces the Interp list registration call: 2 -> 16 entries, and the label "Interp:" -> "Fidelity:" (the pick of
   names; the xml name "interpqual" stays, so presets are unaffected). */
void interp_register(void *table, int param, const char *label, const char *const *names, int count, const char *xml)
{
    (void)label;
    (void)names;
    (void)count;
    fw_register_list(table, param, "Fidelity:", interp_names, INTERPS, xml);
}

struct fstate {                  /* at filter object +4..+0x48; the stock coefficient sets and states used to live here */
    uint32_t magic;
    float g, r, drive;           /* smoothed: SVF frequency coefficient, damping of the resonant stage, drive 0..1 */
    float s1[2][2], s2[2][2];    /* integrator states [stage][channel] */
    float phase, held[2];        /* crunch: hold phase and held sample per channel */
    uint32_t on;                 /* filter was running last block */
};
#define MAGIC 0x53564633u        /* "SVF3": bumped with the layout */
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
uint8_t *master_block(void);

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

static float *s950_state(const uint8_t *obj, struct ostate *o)
{
    uint8_t *mem = master_block();
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

static unsigned pad_setting(const uint8_t *pad, unsigned param)
{
    if (!pad)
        return 0;
    uint32_t id = *(const uint32_t *)(pad + 0x18);
    unsigned row = (id >> 8) & 0xff, col = id & 0xff;
    if (row >= 4 || col >= 5)
        return 0;
    return (unsigned)fw_setting((const void *)(APP_PADS + row * 0xf0u + col * 0x30u), param);
}

static unsigned pad_interp(const uint8_t *pad)
{
    return pad_setting(pad, 0xf1);
}

/* For od.c: this pad is in a machine mode, so its Saturation knob is the machine's input drive (applied here). */
int pad_machine_mode(const uint8_t *pad)
{
    return machine_for(pad_interp(pad)) != 0;
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

/* Replaces the per-voice filter call. pad = the pad object the voice belongs to (thunks in filter_thunk.S). */
void filter_process(uint8_t *obj, void *buf, const uint8_t *pad)
{
    if (fw_buf_silent(buf))
        return;
    struct fstate *st = (struct fstate *)(obj + 4);
    struct ostate *o = (struct ostate *)(obj + 0x60);
    if (st->magic != MAGIC) {
        uint32_t *w = (uint32_t *)st;
        for (unsigned i = 0; i < sizeof *st / 4; i++)
            w[i] = 0;
        o->z[0][0] = o->z[0][1] = o->z[1][0] = o->z[1][1] = 0.0f;
        st->magic = MAGIC;
    }
    unsigned interp = pad_interp(pad);
    int crunching = interp >= FIRST_MACHINE && interp < INTERPS;
    uint8_t *params = *(uint8_t **)(obj + OBJ_PARAMS);
    float knob = params ? fw_param(params + 8) : 0.0f;
    if (knob == 0.0f) {
        st->on = 0;
        if (!crunching)
            return;
    }

    float *ch[2] = {0, 0};
    int n = fw_buf_frames(buf);
    fw_buf_chans(buf, &ch[0], &ch[1]);
    if (!ch[0] || n <= 0)
        return;
    const struct machine *m = machine_for(interp);
    if (m) {
        float d = (float)pad_setting(pad, 0xdb) * 0.001f;
        /* S950: the reader already drove, rounded and clocked out the stored samples (s950_read) and left its rate.
           A rate that makes no sense = no reader ran for this object: do the 12 bits here, as 3.1.T did for clips. */
        float rate = o->rate < 0.0f ? -o->rate : o->rate;
        int read = m->clocked && rate > 0.01f && rate < 64.0f;
        if (!read) {
            rate = 1.0f;
            if (d > 0.0f)
                adc_drive(ch, n, d > 1.0f ? 1.0f : d);
            if (m->hold || m->grid < FS) {
                crunch(st, ch, n, m->dac > 0.0f ? m->dac : m->grid);
            } else {
                for (int k = 0; k < 2; k++)
                    if (ch[k])
                        for (int i = 0; i < n; i++)
                            ch[k][i] = quantize12(ch[k][i]);
            }
        }
        if (m->clocked) {
            float *z = s950_state(obj, o);
            if (z)
                s950_filter(z, ch, n, s950_filter_count(m->grid * rate, 168));
        } else if (!m->raw) {
            out_stage(obj, ch, n, m->out);
        }
    } else if (crunching) {
        crunch(st, ch, n, crunch_rate[interp - FIRST_CRUNCH]);
    }
    if (knob == 0.0f)
        return;

    float hz = fw_cutoff_hz(knob < 0.0f ? knob + 1.0f : knob);
    float res = fw_param(params + 0x44);
    float q = fw_res_q(res);
    float drive = (res - 0.5f) * 2.0f;                      /* 0 up to the default Res, 1 at full */
    drive = drive < 0.0f ? 0.0f : drive > 1.0f ? 1.0f : drive * drive;
    if (hz < 10.0f)
        hz = 10.0f;
    if (hz > 0.45f * FS)
        hz = 0.45f * FS;
    if (!(q > 0.1f))
        q = 0.1f;                                            /* the stock curve's own minimum (Res at 0) */
    if (q > 40.0f)
        q = 40.0f;
    float g = tan_approx(PI_F * hz / FS), r = 1.0f / q;
    if (!st->on) {
        st->g = g;
        st->r = r;
        st->drive = drive;
        for (int k = 0; k < 2; k++)
            st->s1[k][0] = st->s1[k][1] = st->s2[k][0] = st->s2[k][1] = 0.0f;
        st->on = 1;
    } else {
        st->g += SMOOTH * (g - st->g);
        st->r += SMOOTH * (r - st->r);
        st->drive += SMOOTH * (drive - st->drive);
    }
    int hp = knob > 0.0f;
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

/*
 * The voice reader. Sample / multisample voices read their sample through FUN_08055f0c, which fetches the source into a
 * scratch buffer and resamples it with one of two kernels chosen by the stock Interp value: FUN_080619d0 (Normal,
 * 4-point cubic) or FUN_08061a64 (HighQ, Hermite). Both take (rate s0, src r0, n_src r1, int pos r2, int *newpos r3,
 * float *frac, float *dst, int n); the reading point is src[pos + frac] and moves by |rate| per output frame.
 * voice_read (below) parks FUN_08055f0c's pad, absolute source position and signed rate here, so the machine grid is anchored on the sample itself, not on each block's scratch buffer.
 * At rate exactly 1.0 the stock code copies without a kernel; the hold after the voice then does the same job.
 */
struct read_park {
    const uint8_t *pad;
    int32_t pos;
    float rate;
};
#define PARK ((volatile struct read_park *)0x2405fff4u)     /* the last 12 bytes of patch RAM */

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

static void machine_read(const struct machine *m, float rate, const float *src, int n_src, int pos, int *newpos,
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
        float d = (float)pad_setting(PARK->pad, 0xdb) * 0.001f;
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

typedef int (*voice_read_fn)(float frac, float rate, const uint8_t *pad, void *src, int pos, int a6, int frames,
                             int offset, void *scratch, void *out);
#define fw_voice_read ((voice_read_fn)FN(0x08055f0c))

static const struct machine *pad_machine(const uint8_t *pad)
{
    return machine_for(pad_interp(pad));
}

/*
 * Replaces the calls to the sample-voice reader FUN_08055f0c (@0x08057214, 0x080574ce, 0x080575d2, 0x08057694): park
 * the pad, absolute position and signed rate for the kernels. At exactly the original pitch the stock reader copies
 * the source without a kernel; in a machine mode the rate goes in as the next float above 1.0, so those voices still
 * read through the machine's grid and anti-alias taps (a real SP filtered at sampling time; holding the raw source at
 * 26 kHz would fold everything above 13 kHz). The voice's own position bookkeeping is the caller's, unaffected.
 */
int voice_read(float frac, float rate, const uint8_t *pad, void *src, int pos, int a6, int frames, int offset,
               void *scratch, void *out)
{
    PARK->pad = pad;
    PARK->pos = pos;
    PARK->rate = rate;
    if (rate == 1.0f && pad_machine(pad))
        rate = 1.00000012f;
    return fw_voice_read(frac, rate, pad, src, pos, a6, frames, offset, scratch, out);
}

static const struct machine *read_machine(void)
{
    return pad_machine(PARK->pad);
}

/* Replace the kernel calls in FUN_08055f0c: Normal @0x0805619a / 0x080561be / 0x080561d4, HighQ @0x08056010 /
   0x08056098 / 0x080560bc. */
void read_normal(float rate, const float *src, int n_src, int pos, int *newpos, float *frac, float *dst, int n)
{
    const struct machine *m = read_machine();
    if (m)
        machine_read(m, rate, src, n_src, pos, newpos, frac, dst, n);
    else
        fw_kernel_normal(rate, src, n_src, pos, newpos, frac, dst, n);
}

void read_hq(float rate, const float *src, int n_src, int pos, int *newpos, float *frac, float *dst, int n)
{
    const struct machine *m = read_machine();
    if (m)
        machine_read(m, rate, src, n_src, pos, newpos, frac, dst, n);
    else
        fw_kernel_hq(rate, src, n_src, pos, newpos, frac, dst, n);
}

/*
 * Clip and slicer pads (engine class B) do not read through FUN_08055f0c. Each of their voices' segments reads through
 * FUN_080662e4 (one call, @0x08066622, in FUN_08066454): it fetches int(n x rate) + 8 source samples from the
 * segment's position into a scratch buffer and runs a four-point kernel over them (FUN_080603ec, the reading point
 * one sample past the position), or copies the source straight across at exactly the original pitch. This replaces
 * that call. Fidelity Normal / HighQ / the plain crunches: stock, untouched. A machine mode: the same fetch three
 * samples earlier (the machine kernels look two samples either side of a stored sample, which can sit a grid step
 * behind the reading point), then machine_read: the readers the sample pads use, anchored on the absolute position.
 * The count of source samples used and the fraction go back exactly as stock's would (same arithmetic), so loop
 * points, slices and tempo sync are where they were.
 */
typedef int (*clip_read_fn)(float rate, uint8_t *pad, uint8_t *filter, int32_t pos, int32_t pos_hi, int n, int *used,
                            float *frac, void *scratch, void *out, void **result);
typedef int (*src_int_fn)(void *src);
typedef void (*fetch_fn)(void *src, float *dst, int n, int32_t pos, int zero);
typedef void (*fetch2_fn)(void *src, float *left, float *right, int n, int32_t pos);
typedef float *(*buf_mono_fn)(void *buf);
#define fw_clip_read  ((clip_read_fn)FN(0x080662e4))
#define fw_src_len    ((src_int_fn)FN(0x080636f0))
#define fw_src_stereo ((src_int_fn)FN(0x08063790))
#define fw_fetch      ((fetch_fn)FN(0x08063634))
#define fw_fetch2     ((fetch2_fn)FN(0x08063608))
#define fw_buf_mono   ((buf_mono_fn)FN(0x0804d934))
#define fw_buf_pair   ((buf_chans_fn)FN(0x0804da0c))
#define CLIP_SOURCE 0x24         /* pad -> its sample */
#define CLIP_BACK   3            /* the fetch starts this many samples before the position */

/* count frames from start into l (and r): vlen 0 = the file as stock reads it (silence before frame 0); vlen > 0 =
   the region [rs, rs + vlen) taken as circular (clipwin.c's Slip), round its end as often as it takes */
void clip_fetch(void *src, int stereo, float *l, float *r, int count, int32_t start, int32_t rs, int32_t vlen)
{
    if (vlen <= 0) {
        int lead = start < 0 ? -start : 0;                  /* before the sample's first frame: silence */
        if (lead > count)
            lead = count;
        for (int i = 0; i < lead; i++) {
            l[i] = 0.0f;
            if (stereo)
                r[i] = 0.0f;
        }
        if (count > lead) {
            if (stereo)
                fw_fetch2(src, l + lead, r + lead, count - lead, start + lead);
            else
                fw_fetch(src, l + lead, count - lead, start + lead, 0);
        }
        return;
    }
    int32_t at = (start - rs) % vlen;
    start = rs + (at < 0 ? at + vlen : at);
    while (count > 0) {
        int32_t room = rs + vlen - start;
        int m = count < room ? count : (int)room;
        if (stereo) {
            fw_fetch2(src, l, r, m, start);
            r += m;
        } else {
            fw_fetch(src, l, m, start, 0);
        }
        l += m;
        count -= m;
        start = rs;
    }
}

static int clip_read_at(const struct machine *m, float rate, uint8_t *pad, uint8_t *filter, int32_t pos, int n,
                        int *used, float *frac, void *scratch, void *out, void **result, int32_t rs, int32_t vlen)
{
    void *src = *(void **)(pad + CLIP_SOURCE);
    ((struct ostate *)(filter + 0x60))->rate = rate;
    int n_src = (int)((float)n * rate) + 8, cap = fw_buf_frames(scratch);
    if (n_src > cap)
        n_src = cap;
    int32_t start = pos - CLIP_BACK;
    PARK->pad = pad;
    PARK->pos = start + 4;                                  /* machine_read: scratch[0] = source[PARK->pos - 4] */
    PARK->rate = rate;
    int idx = 4;
    if (!fw_src_stereo(src)) {
        float *s = fw_buf_mono(scratch);
        clip_fetch(src, 0, s, 0, n_src, start, rs, vlen);
        machine_read(m, rate, s, n_src, 4, &idx, frac, fw_buf_mono(out), n);
    } else {
        float *sl = 0, *sr = 0, *ol = 0, *orr = 0;
        fw_buf_pair(scratch, &sl, &sr);
        clip_fetch(src, 1, sl, sr, n_src, start, rs, vlen);
        fw_buf_pair(out, &ol, &orr);
        float f = *frac;
        machine_read(m, rate, sl, n_src, 4, &idx, &f, ol, n);
        machine_read(m, rate, sr, n_src, 4, &idx, frac, orr, n);
    }
    *used = idx - 4;
    *result = out;
    return 1;
}

/* filter = the reading voice's filter object, put in the register stock leaves unused (clip_read_b, filter_thunk.S) */
int clip_read(float rate, uint8_t *pad, uint8_t *filter, int32_t pos, int32_t pos_hi, int n, int *used, float *frac,
              void *scratch, void *out, void **result)
{
    const struct machine *m = pad_machine(pad);
    if (!m || !(rate > 0.0f))
        return fw_clip_read(rate, pad, filter, pos, pos_hi, n, used, frac, scratch, out, result);
    if (fw_src_len(*(void **)(pad + CLIP_SOURCE)) + 0xff < pos)
        return 0;
    return clip_read_at(m, rate, pad, filter, pos, n, used, frac, scratch, out, result, 0, 0);
}

/* clipwin.c: a machine-mode read at real over the circular region [rs, rs + vlen), seam or not; -1 = the pad reads
   through stock's reader (no machine mode), the caller's job */
int clip_read_ring(float rate, uint8_t *pad, uint8_t *filter, int32_t real, int32_t rs, int32_t vlen, int n, int *used,
                   float *frac, void *scratch, void *out, void **result)
{
    const struct machine *m = pad_machine(pad);
    if (!m || !(rate > 0.0f))
        return -1;
    return clip_read_at(m, rate, pad, filter, real, n, used, frac, scratch, out, result, rs, vlen);
}
