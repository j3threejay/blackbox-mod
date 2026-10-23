/*
 * Pad-1 ducking as modulation sources. Original 1010music Blackbox, firmware 3.1.9.
 *
 * The engine has ten global modulation sources (mod1..mod10, the CV inputs of the Eurorack sibling) that the
 * Blackbox never feeds. Four of them become duck envelopes, all triggered when pad 1 starts a voice, each with its
 * own shape. They appear in the modulation Source list as EXP1 / EXP2 / PUMP / LINR; the slot's Amount is the
 * depth (negative = duck). Routing, per-pad depth and preset save/load are stock firmware.
 *
 * Envelope: 0 at rest, ramps to 1 over the attack from wherever it is, holds, then follows a release curve to 0.
 * The engine's own gain ramp (256 samples) limits how fast the audible dip can be: ~5 ms however short the attack.
 */
#include <stdint.h>

#define FN(addr) ((addr) | 1u)
typedef int (*process_fn)(uint8_t *engine, void *a, void *b);
#define fw_process ((process_fn)FN(0x08053164))

#define SOURCES      4
#define SAMPLES_PER_MS 48.0f
#define MAX_STEP     4800u         /* ignore gaps > 100 ms (first block, clock jumps) */
#define STEPS        32

enum { IDLE, ATTACK, HOLD, RELEASE };
enum { SHAPE_EXP, SHAPE_PUMP, SHAPE_LINEAR };

/* Release curves: envelope value (1 = full dip, 0 = recovered) at STEPS+1 points across the release.
 * The envelope scales the slot Amount, which acts on Level in dB (measured: ~0.65 dB per 1%). */
static const float curve[3][STEPS + 1] = {
    /* exponential decay, 99% done at the end (Octatrack EXP LFO style): most of the recovery happens early */
    { 1.00000f, 0.86474f, 0.74760f, 0.64614f, 0.55826f, 0.48216f, 0.41624f, 0.35915f,
    0.30970f, 0.26687f, 0.22978f, 0.19765f, 0.16983f, 0.14573f, 0.12486f, 0.10678f,
    0.09112f, 0.07756f, 0.06582f, 0.05565f, 0.04684f, 0.03920f, 0.03260f, 0.02687f,
    0.02191f, 0.01762f, 0.01390f, 0.01068f, 0.00789f, 0.00547f, 0.00338f, 0.00157f,
    0.00000f },
    /* schwung-ducker "Pump": cubic ease-out in amplitude, converted to dB for a 16.5 dB dip */
    { 1.00000f, 0.78085f, 0.63500f, 0.52758f, 0.44390f, 0.37638f, 0.32060f, 0.27375f,
    0.23391f, 0.19974f, 0.17025f, 0.14470f, 0.12250f, 0.10319f, 0.08639f, 0.07180f,
    0.05916f, 0.04825f, 0.03889f, 0.03090f, 0.02415f, 0.01850f, 0.01384f, 0.01005f,
    0.00704f, 0.00471f, 0.00296f, 0.00171f, 0.00088f, 0.00037f, 0.00011f, 0.00001f,
    0.00000f },
    /* straight line in dB */
    { 1.00000f, 0.96875f, 0.93750f, 0.90625f, 0.87500f, 0.84375f, 0.81250f, 0.78125f,
    0.75000f, 0.71875f, 0.68750f, 0.65625f, 0.62500f, 0.59375f, 0.56250f, 0.53125f,
    0.50000f, 0.46875f, 0.43750f, 0.40625f, 0.37500f, 0.34375f, 0.31250f, 0.28125f,
    0.25000f, 0.21875f, 0.18750f, 0.15625f, 0.12500f, 0.09375f, 0.06250f, 0.03125f,
    0.00000f },
};

/* value floats of the spare sources: engine + 0xd5b0 + row*100 + 4*0x14 + 4, rows 0..3 (source codes 0x12, 0x11, 0x10, 0xf) */
static const uint16_t value_off[SOURCES] = {0xd604, 0xd668, 0xd6cc, 0xd730};
/*                                           EXP1    EXP2    PUMP    LINR */
static const float attack_ms[SOURCES]  = {  1.0f,   1.0f,   5.0f,   4.0f};
static const float hold_ms[SOURCES]    = {  0.0f,   0.0f, 100.0f,  25.0f};
static const float release_ms[SOURCES] = {250.0f, 500.0f, 300.0f, 300.0f};
static const uint8_t shape[SOURCES]    = {SHAPE_EXP, SHAPE_EXP, SHAPE_PUMP, SHAPE_LINEAR};

/* Patch RAM in the gap above the heap (see solo.c), after the solo state. Not zeroed at boot. */
struct duck_state {
    uint32_t magic;
    uint32_t last;                 /* engine sample clock at the previous tick */
    uint8_t trig;                  /* set by the voice-start thunk (offset 8, see duck_thunk.S) */
    uint8_t stage[SOURCES];
    uint8_t spare;
    uint16_t trigs;                /* offset 14: a bit per pad (row * 4 + col), set by the voice-start thunk; lfo.c reads it */
    float value[SOURCES];
    float timer[SOURCES];          /* ms elapsed in the hold or release stage */
};
#define D ((volatile struct duck_state *)0x2405ff70u)
#define MAGIC 0x4455434cu          /* "DUCL": bumped when the state layout or meaning changes */

/* Replaces the call to the engine's control tick (FUN_08053164). */
void lfo_tick(uint32_t now);
void insert_tick(void);          /* insert.c: one pad's insert settings per block */
void clipwin_tick(uint8_t *engine); /* clipwin.c: one pad's Slip and Loop Len per block */

int duck_block(uint8_t *engine, void *a, void *b)
{
    uint32_t now = *(uint32_t *)engine;          /* low word of the 64-bit sample clock */
    if (D->magic != MAGIC) {
        for (int i = 0; i < SOURCES; i++) {
            D->stage[i] = IDLE;
            D->value[i] = 0.0f;
            D->timer[i] = 0.0f;
        }
        D->trig = 0;
        D->trigs = 0;
        D->last = now;
        D->magic = MAGIC;
    }
    uint32_t step = now - D->last;
    D->last = now;
    if (step > MAX_STEP)
        step = 0;
    float dt = (float)step / SAMPLES_PER_MS;

    int trig = D->trig;
    D->trig = 0;
    for (int i = 0; i < SOURCES; i++) {
        float v = D->value[i], timer = D->timer[i];
        int stage = trig ? ATTACK : D->stage[i];
        if (stage == ATTACK) {                    /* rises from wherever it is, so a retrigger never jumps */
            v += dt / attack_ms[i];
            if (v >= 1.0f) {
                v = 1.0f;
                stage = HOLD;
                timer = 0.0f;
            }
        } else if (stage == HOLD) {
            timer += dt;
            if (timer >= hold_ms[i]) {
                stage = RELEASE;
                timer = 0.0f;
            }
        } else if (stage == RELEASE) {
            timer += dt;
            float x = timer / release_ms[i] * (float)STEPS;
            int k = (int)x;
            if (k >= STEPS) {
                v = 0.0f;
                stage = IDLE;
            } else {
                const float *c = curve[shape[i]];
                v = c[k] + (c[k + 1] - c[k]) * (x - (float)k);
            }
        }
        D->stage[i] = (uint8_t)stage;
        D->value[i] = v;
        D->timer[i] = timer;
        *(float *)(engine + value_off[i]) = v;
    }
    lfo_tick(now);
    insert_tick();
    clipwin_tick(engine);
    return fw_process(engine, a, b);
}

/*
 * Source list for pad modulation (param 0x53): the eight stock entries plus ours.
 * KEY (3.1.W) is stock's own per-note source, code 0xe, "key" in the preset format: the engine attaches it on both
 * pad classes (FUN_0805623c: voice + 0x8c; FUN_08067018 case 0xe) but the menu never offered it. Its value is
 * (note - 60) / 60, set when the voice starts (FUN_08058548): 0 at middle C, 0.2 per octave, either side.
 */
const char *const duck_source_names[16] = {
    (const char *)0x080cea68, /* none */ (const char *)0x080cea94, /* VEL  */
    "KEY",
    (const char *)0x080ce644, /* LFO  */ "LFO2", "LFO3",       /* lfo.c */
    (const char *)0x080cea70, /* PTCH */
    (const char *)0x080cea78, /* MODW */ (const char *)0x080cea80, /* MVOL */
    (const char *)0x080cea88, /* MPAN */ (const char *)0x080cea90, /* CC   */
    "ENV",                                       /* envmod.c: the pad's ADSR; ahead of the duck shapes (by request) */
    "EXP1", "EXP2", "PUMP", "LINR",
};
const uint16_t duck_source_codes[16] = {
    0, 0xd, 0xe, 4, 5, 6, 0x19, 0x1a, 0x1c, 0x1d, 0x8000,   /* stock, with key after velocity, lfo2 / lfo3 after the LFO */
    1,                                           /* env1 */
    0x12, 0x11, 0x10, 0xf,                       /* mod4, mod3, mod2, mod1 */
};
