/*
 * ChopShop (the Slicer chop modes): slice points placed by our code. Original 1010music Blackbox, firmware 3.1.9.
 *
 * chop_set_slices replaces a pad's slice points the way stock's Slice to Grid does (FUN_08099434; research/slicer/
 * SLICE_POINTS_RE.md 3.1): the app cell's sorted list (cell + 0x28, at most 128, the copy the preset saves), engine
 * message 0x3c to the pad's player (1000 = clear, 1 = insert: only what the app list took), ONE 0x66 so the screen
 * copies the cell again, and the project-changed flag. App / view context only (view code runs in the app task).
 * chop_beats lays the points on a beat grid: anchor + k x frames per beat x unit, whole file, at most 128; a pickup
 * slice at 0 when beat one is later than that (otherwise the audio before it could not be played as a slice).
 * CPU: none on the audio side but the attack scan (chop_dsp.c); here one pass over at most 128 x 1024 hits when asked
 * (GUI task, ~1 M instructions, ~2 ms once).
 */
#include <stdint.h>
#include "chop.h"

#define FN(addr) ((addr) | 1u)
typedef uint8_t *(*cell_fn)(uint8_t *app, void *ref);
typedef void (*list_fn)(void *list);
typedef void (*list_int_fn)(void *list, int v);
typedef void (*marker_msg_fn)(uint32_t engine, uint32_t pad, int pos, int op);
typedef void (*app_post_fn)(uint8_t *queue, void *msg);
#define fw_cell        ((cell_fn)FN(0x08098d0c))
#define fw_list_clear  ((list_fn)FN(0x08093c98))
#define fw_list_insert ((list_int_fn)FN(0x08093cca))
#define fw_marker_msg  ((marker_msg_fn)FN(0x0804c69c))
#define fw_app_post    ((app_post_fn)FN(0x080b5758))

#define APP        ((uint8_t *)0x24020088u)
#define ENGINE     0x2400a9c0u               /* what FUN_080a0ac8 passes FUN_0804c69c (literal @0x080a0cf0) */
#define CELL_REF   0x080eaf38u               /* the ref tag FUN_080a1718 builds */
#define MSG_TAG    0x080cfba4u
#define CELL_LIST  0x28
#define APP_QUEUE  0x30
#define APP_DIRTY  0x8cc4
#define CHOP_MAX   128
#define PICKUP_MIN 64                        /* frames: beat one later than this gets a pickup slice at 0 */

struct cmsg { uint16_t id, _r0; uint32_t tag; uint16_t pad, _r1; int32_t a, b; uint32_t c; };

/* pos[] ascending, 0 <= pos < the sample length, n <= 128. cell = the app's cell id (row << 4 | col). Returns how many
   the list kept. */
int chop_set_slices(uint16_t cell, const int32_t *pos, int n)
{
    struct { uint32_t tag; uint16_t pad, r; } ref = { CELL_REF, cell, 0 };
    uint8_t *c = fw_cell(APP, &ref);
    if (!c)
        return 0;
    uint32_t *list = (uint32_t *)(c + CELL_LIST);
    uint32_t ea = (cell & 0xfu) | ((cell >> 4) & 0xfu) << 8 | (uint32_t)((cell & 0x1fff) >> 8) << 16;
    fw_list_clear(list);
    fw_marker_msg(ENGINE, ea, 0, 1000);
    for (int i = 0; i < n && i < CHOP_MAX; i++) {
        uint32_t before = list[1];
        fw_list_insert(list, pos[i]);
        if (list[1] != before)
            fw_marker_msg(ENGINE, ea, pos[i], 1);
    }
    struct cmsg m = { 0x66, 0, MSG_TAG, cell, 0, 0, 0, 0 };
    fw_app_post(APP + APP_QUEUE, &m);
    APP[APP_DIRTY] = 1;
    return (int)list[1];
}

/* Slice points every unit_beats beats from anchor (beat one, frames) over a file of len frames at fpb frames a beat.
   Returns the count written to out (at most max). */
int chop_beats(int32_t *out, int max, int32_t len, int32_t anchor, float fpb, float unit_beats)
{
    double step = (double)fpb * (double)unit_beats;
    int n = 0;
    if (!(step >= 16.0) || len <= 0 || max <= 0)
        return 0;
    if (anchor < 0 || anchor >= len)
        anchor = 0;
    if (anchor > PICKUP_MIN)
        out[n++] = 0;
    for (int k = 0; n < max; k++) {
        double p = (double)anchor + (double)k * step;
        if (p >= (double)len)
            break;
        out[n++] = (int32_t)(p + 0.5);
    }
    return n;
}

/*
 * Every chop on a hit of the attack scan (chop_dsp.c; asked 10-27: the markers must land on the real hits, the way
 * stock's transient Scan does). Hits quieter than ON_FLOOR x the loudest are never used (silence, fades, noise).
 *   Grid chops (chop_onto_hits): each point to the nearest hit within half a step either way, among those no more
 *         than 10 dB under the loudest there (a click in a gap does not win over the snare beside it); a point with
 *         none there is dropped. The file start stays a slice (the audio before the first hit must stay playable).
 *   Find: the file cut into `want` equal stretches; in each, the loudest, sharpest hit, nudged by a seeded random
 *         0.6..1.4 so another roll (another seed) finds other chops.
 *   Random: `want` different hits at random.
 * Unsorted out[] (chop_poll tidies). Returns the count (fewer when the file has fewer hits).
 */
#define ON_FLOOR   0.001f                     /* -30 dB (plain energy) */
#define ON_NEAR    0.1f                       /* grid chops: hits within 10 dB of the loudest in reach */

static uint32_t rnd(uint32_t *s)
{
    uint32_t x = *s ? *s : 0x9e3779b9u;
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    *s = x;
    return x;
}

static float sqrt_(float x)
{
#ifdef STR_HOST
    return __builtin_sqrtf(x);
#else
    float r;
    __asm__("vsqrt.f32 %0, %1" : "=t"(r) : "t"(x));
    return r;
#endif
}

static float floor_of(const struct chop_job *j)
{
    float m = 0.0f;
    for (int i = 0; i < j->n; i++)
        if (j->level[i] > m) m = j->level[i];
    return m * ON_FLOOR;
}

int chop_onto_hits(int32_t *pos, int n, float step, const struct chop_job *j)
{
    float floor = floor_of(j);
    int32_t half = (int32_t)(step * 0.5f);
    int m = 0;
    for (int i = 0; i < n; i++) {
        int32_t p = pos[i], best = -1, bd = half + 1;
        if (p <= 0) {                                    /* the pickup slice stays at the file start */
            pos[m++] = 0;
            continue;
        }
        float top = floor;
        for (int k = 0; k < j->n; k++) {
            int32_t d = j->at[k] - p;
            if ((d < 0 ? -d : d) <= half && j->level[k] > top) top = j->level[k];
        }
        for (int k = 0; k < j->n; k++) {
            int32_t d = j->at[k] - p;
            if (d < 0) d = -d;
            if (d < bd && j->level[k] > floor && j->level[k] >= top * ON_NEAR) { bd = d; best = j->at[k]; }
        }
        if (best >= 0)
            pos[m++] = best;
    }
    int lo = 0;
    for (int i = 1; i < m; i++)
        if (pos[i] < pos[lo]) lo = i;
    if (m < CHOP_MAX && (!m || pos[lo] > PICKUP_MIN))
        pos[m++] = 0;
    return m;
}

int chop_find(int32_t *out, int want, const struct chop_job *j, uint32_t seed)
{
    if (j->state != CHOP_DONE || j->n <= 0 || want <= 0)
        return 0;
    float floor = floor_of(j);
    int32_t span = j->len / want;
    int n = 0;
    for (int s = 0; s < want; s++) {
        int32_t lo = s * span, hi = s == want - 1 ? j->len : lo + span;
        int best = -1;
        float bs = 0.0f;
        for (int k = 0; k < j->n; k++) {
            if (j->at[k] < lo || j->at[k] >= hi || j->level[k] <= floor)
                continue;
            float sc = (float)(rnd(&seed) >> 8) * (0.8f / 16777216.0f) + 0.6f;
            sc *= sqrt_(j->level[k]) * (1.0f - 1.0f / j->score[k]) + 1e-9f;   /* loud x sharp */
            if (sc > bs) { bs = sc; best = k; }
        }
        if (best >= 0)
            out[n++] = j->at[best];
    }
    return n;
}

int chop_random(int32_t *out, int want, const struct chop_job *j, uint32_t seed)
{
    if (j->state != CHOP_DONE || j->n <= 0 || want <= 0)
        return 0;
    float floor = floor_of(j);
    int usable = 0;
    for (int k = 0; k < j->n; k++)
        usable += j->level[k] > floor;
    if (want > usable)
        want = usable;
    int n = 0;
    for (int k = 0; k < j->n && n < want; k++) {         /* selection sampling: each usable hit with p = left / remaining */
        if (j->level[k] <= floor)
            continue;
        if ((int)(rnd(&seed) % (uint32_t)usable) < want - n)
            out[n++] = j->at[k];
        usable--;
    }
    return n;
}

/*
 * The driver (GUI task, every frame: theme_compose calls chop_poll). chop_request starts an operation on pad q: the
 * tempo first (the detector, unless a re-roll of the same pad can reuse the last one), then the attack scan (chop_dsp.c,
 * audio side; once per file: kept until a new sample) as far as the chops need it: Beats to its last grid point, Find /
 * Random the whole file. Then every chop goes onto a hit. Find also turns PlayThru on (Serato's Find Samples plays on
 * past a chop).
 */
#include "stretch.h"
struct str_bank *stretch_bank(void);
void sel_ask_pad(int q);
int sel_take_pad(int q, float *bpm, float *phase, unsigned *frate);
typedef int (*src_int_fn)(void *src);
typedef void (*set_fn)(void *store, int param, int value);
typedef void (*eng_param_fn)(uint32_t engine, uint32_t pad, int param, int value, int a, int b);
#define fw_src_len    ((src_int_fn)FN(0x080636f0))
#define fw_src_stereo ((src_int_fn)FN(0x08063790))
#define fw_set        ((set_fn)FN(0x08093ecc))
#define fw_setting    ((int (*)(const void *, int))FN(0x08093e9c))
/* ChopShop's Tempo row (chopmode.c): a correction to the detected tempo, kept in the pad's P_SEL_BEATS (the Clip
   selection's Beats: Slicer pads never read it, sel_setup; a new sample clears it, sel_clear). 0 x1, 1 half, 2 double */
#define P_SEL_BEATS   0x15e
#define fw_eng_param  ((eng_param_fn)FN(0x0804c59c))   /* the engine's param message, as FUN_0809fa50 sends it */
#define P_PLAYTHRU    0xf2
#define P_BEATCOUNT   0xd2                              /* Slicer Beat Count: Auto, 1 .. 512 */
#define PAD_SOURCE    0x24
#define CHOP_WAIT     1800                              /* GUI frames (~30 s at 60 Hz) */
/* The Roll row's cue (asked 10-26: "a little dice ... something that tells you that you actually did roll it"),
   counted in GUI frames in chop_run.spare: [0] dice frames left after a request, [1] frames the result stays up,
   [2] chops placed. Shown by chop_view_tick (chopmode.c) through chop_roll_text. */
#define CUE_DICE      48                                /* ~0.8 s of two dice tumbling, slowing, landing */
#define CUE_SHOW      90                                /* ~1.5 s of "32 chops" / "Fail n" */

static const float unit_beats[5] = { 0.25f, 0.5f, 1.0f, 2.0f, 4.0f };

static uint16_t cell_of(int q) { return (uint16_t)((q >> 2) << 4 | (q & 3)); }

static void *pad_obj(struct str_bank *b, int q)
{
    uint8_t *eng = b->clip[q].eng;
    return eng ? *(void **)(eng + PAD_SOURCE) : 0;
}

static void with_tempo(struct str_bank *b, struct chop_run *r, int q, void *obj);

/* pad q's attack scan is this sample's and reaches frame upto */
static int scanned(struct str_bank *b, int q, void *obj, int32_t upto)
{
    return b->cj.state == CHOP_DONE && b->cj.pad == q && b->cj.obj == obj && b->cj.len >= upto;
}

void chop_request(int q, int op, int unit, int want)
{
    struct str_bank *b = stretch_bank();
    if (!b || q < 0 || q > 15 || op <= CHOP_OP_NONE || op > CHOP_OP_RANDOM)
        return;
    struct chop_run *r = &b->cr;
    void *obj = pad_obj(b, q);
    /* this file's tempo already in hand (chop_forget drops it on a new sample): no detector. A Chop change mid-playback
       ran the detector and the whole-file scan again and choked a little (glass 10-27) */
    int known = r->pad == q && r->fpb > 0.0f && r->phase == CHOP_PH_IDLE && obj != 0;
    r->op = (uint8_t)op;
    r->pad = (uint8_t)q;
    r->unit = (uint8_t)(unit < 0 ? 0 : unit > 4 ? 4 : unit);
    r->want = want > 0 && want <= CHOP_MAX ? want : 64;
    r->seed = r->seed * 1664525u + 1013904223u + b->seq;
    r->frames = 0;
    r->fail = 0;
    r->spare[0] = CUE_DICE;
    r->spare[1] = 0;
    if (known) {
        if (op != CHOP_OP_BEATS && scanned(b, q, obj, fw_src_len(obj))) {
            r->phase = CHOP_PH_SCAN;                    /* the whole file's hits in hand: new picks (a re-roll, Find <-> Random) */
            r->seen = -1;
            return;
        }
        with_tempo(b, r, q, obj);                       /* the scan (or what it still needs) at the known tempo */
        return;
    }
    r->phase = CHOP_PH_TEMPO;
    sel_ask_pad(q);
}

/* a new sample on pad q: its last scan is the old file's, so the next Find / Random scans again (a re-roll would place
   the old file's beats: zero slices on a shorter file, glass 10-25) */
void chop_forget(int q)
{
    struct str_bank *b = stretch_bank();
    if (b && b->cr.pad == q)
        b->cr.fpb = 0.0f;
    if (b && b->cj.pad == q) {
        b->cj.obj = 0;                                  /* never this pad's scan again (the object may be reused) */
        b->cj.state = CHOP_IDLE;
    }
}

static void place(int q, const int32_t *pos, int n)
{
    chop_set_slices(cell_of(q), pos, n);
}

static float tempo_mult(int code)                     /* the true tempo / the detected one */
{
    return code == 1 ? 0.5f : code == 2 ? 2.0f : 1.0f;
}

static uint8_t *pad_cell(int q)
{
    struct { uint32_t tag; uint16_t pad, rr; } ref = { CELL_REF, cell_of(q), 0 };
    return fw_cell(APP, &ref);
}

static void done(struct chop_run *r, int fail, int n)  /* the run is over: show its result for a moment */
{
    r->phase = CHOP_PH_IDLE;
    r->fail = (uint8_t)fail;
    r->spare[1] = CUE_SHOW;
    r->spare[2] = (uint8_t)(n < 0 ? 0 : n > 255 ? 255 : n);
}

/* Two dice tumbling (asked 10-27: "more like dice tumbling"): every face change is a new random pair, the brackets
   turn [ ] ( ) < > to read as edge-on, the pair bounces a column left / right, and the changes come further apart
   until the dice land on their final faces (from the roll's seed) and hold. ASCII only; at most 13 characters. */
static const uint8_t dice_at[] = {0, 2, 4, 6, 9, 12, 16, 21, 27, 34, 42};   /* frames since the turn: a new face */
#define DICE_STEPS (sizeof dice_at / sizeof dice_at[0])

static uint32_t mix(uint32_t x)
{
    x ^= x >> 15; x *= 0x2c1b3c6du; x ^= x >> 12; x *= 0x297a2d39u; x ^= x >> 15;
    return x;
}

static const char *dice_frame(uint32_t seed, int t, char *buf)
{
    static const char faces[6][4] = {" . ", ". .", "...", ": :", ":.:", ":::"};
    static const char open[3] = {'[', '(', '<'}, shut[3] = {']', ')', '>'};
    static const uint8_t bounce[4] = {0, 1, 2, 1};
    unsigned k = 0;
    while (k + 1 < DICE_STEPS && t >= dice_at[k + 1])
        k++;
    int last = k + 1 == DICE_STEPS;
    uint32_t h = mix(seed ^ (k * 0x9e3779b1u));
    int a = (int)(h % 6), d = (int)((h >> 8) % 6), s = last ? 0 : (int)(k % 3);
    char *p = buf;
    for (int i = last ? 1 : bounce[k & 3]; i > 0; i--)
        *p++ = ' ';
    for (int n = 0; n < 2; n++) {
        const char *f = faces[n ? d : a];
        *p++ = open[s]; *p++ = f[0]; *p++ = f[1]; *p++ = f[2]; *p++ = shut[s];
        if (!n)
            *p++ = ' ';
    }
    *p = 0;
    return buf;
}

/* The Roll row's text for pad q: tumbling dice, "Rolling..", the result, then a resting die. ASCII only: the font
   draws 0x20..0x7f (research, 10-26). buf holds at least 16. */
const char *chop_roll_text(int q, char *buf)
{
    struct str_bank *b = stretch_bank();
    const struct chop_run *r = b ? &b->cr : 0;
    if (r && q == CHOP_ANY_PAD)
        q = r->pad;
    if (!r || r->pad != q)
        return "[:.:]";
    if (r->spare[0])
        return dice_frame(r->seed, CUE_DICE - r->spare[0], buf);
    if (r->phase != CHOP_PH_IDLE)
        return "Rolling..";
    if (!r->spare[1])
        return "[:.:]";
    char *p = buf;
    if (r->fail) {
        const char *f = "Fail ";
        while (*f) *p++ = *f++;
        *p++ = (char)('0' + r->fail % 10);
    } else {
        char t[4];
        int v = r->spare[2], i = 0;
        do { t[i++] = (char)('0' + v % 10); v /= 10; } while (v && i < 3);
        while (i) *p++ = t[--i];
        const char *s = " chops";
        while (*s) *p++ = *s++;
    }
    *p = 0;
    return buf;
}

/* sorted, and two points closer than a sub-hop are one */
static int tidy(int32_t *pos, int n)
{
    for (int i = 1; i < n; i++) {
        int32_t v = pos[i];
        int j = i;
        for (; j > 0 && pos[j - 1] > v; j--)
            pos[j] = pos[j - 1];
        pos[j] = v;
    }
    int m = 0;
    for (int i = 0; i < n; i++)
        if (!m || pos[i] - pos[m - 1] >= ON_SUB)
            pos[m++] = pos[i];
    return m;
}

/* frames the scan judges behind its read point, and a little more */
#define SCAN_LAG ((ON_R + ON_P + 4) * ON_H)

static int grid(struct chop_run *r, int32_t len)
{
    return chop_beats(r->pos, CHOP_MAX, len, (int32_t)r->anchor, r->fpb, unit_beats[r->unit]);
}

/* The tempo is known (r->fpb, r->anchor): Beat Count to match, then the attack scan as far as the chops need */
static void with_tempo(struct str_bank *b, struct chop_run *r, int q, void *obj)
{
    int32_t *pos = r->pos, len = fw_src_len(obj);
    /* Beat Count = the file's beats at that tempo: stock's Slicer Sync fits each slice with the clip BPM it derives
       from Beat Count (SLICER_PLAYBACK_RE.md 1.4), and Auto is stock's own guess */
    int beats = (int)((float)len / r->fpb + 0.5f);
    beats = beats < 1 ? 1 : beats > 512 ? 512 : beats;
    uint8_t *c = pad_cell(q);
    if (c)
        fw_set(c, P_BEATCOUNT, beats);
    fw_eng_param(ENGINE, (uint32_t)((q & 3) | (q >> 2) << 8), P_BEATCOUNT, beats, 0, 0);
    int32_t upto = len;
    if (r->op == CHOP_OP_BEATS) {                     /* 128 points at most: only as far as the last (+ half a step) */
        int n = grid(r, len);
        if (n == CHOP_MAX)
            upto = pos[n - 1] + (int32_t)(r->fpb * unit_beats[r->unit] * 0.5f) + SCAN_LAG;
        if (upto > len)
            upto = len;
    }
    struct chop_job *j = &b->cj;
    if (j->pad == q && j->obj == obj && (j->state == CHOP_DONE || j->state == CHOP_SCAN)) {
        if (j->len < upto) {                            /* this file's scan, not far enough yet: it goes on */
            j->len = upto;
            j->misses = 0;
            __asm__ volatile("" ::: "memory");
            j->state = CHOP_SCAN;
        }
    } else {
        chop_scan_start(j, q, obj, upto, fw_src_stereo(obj));
        j->fetch = chop_fw_fetch;
    }
    r->seen = -1;
    r->phase = CHOP_PH_SCAN;
}

/* The Tempo row went from code old to code new on pad q (the store already holds new). With this pad's detection in
   hand, chop again at the corrected tempo without the detector (Beats at once, Find / Random rescan); 0 = no detection
   to reuse: the caller requests a normal chop, whose detection then reads the new code. */
int chop_retempo(int q, int old, int new_code)
{
    struct str_bank *b = stretch_bank();
    if (!b || q < 0 || q > 15)
        return 0;
    struct chop_run *r = &b->cr;
    void *obj = pad_obj(b, q);
    if (r->pad != q || !(r->fpb > 0.0f) || r->phase != CHOP_PH_IDLE || !obj || r->op <= CHOP_OP_NONE)
        return 0;
    r->fpb = r->fpb * tempo_mult(old) / tempo_mult(new_code);
    r->seed = r->seed * 1664525u + 1013904223u + b->seq;
    r->frames = 0;
    r->fail = 0;
    r->spare[0] = CUE_DICE;
    r->spare[1] = 0;
    with_tempo(b, r, q, obj);
    return 1;
}

void chop_poll(void)
{
    struct str_bank *b = stretch_bank();
    if (!b)
        return;
    struct chop_run *r = &b->cr;
    if (r->spare[0])
        r->spare[0]--;
    if (r->phase == CHOP_PH_IDLE) {
        if (r->spare[1] && !r->spare[0])
            r->spare[1]--;
        return;
    }
    if (r->phase == CHOP_PH_SCAN && b->cj.next != r->seen) {
        r->seen = b->cj.next;                           /* the scan is moving: a long file is not a stall */
        r->frames = 0;
    }
    if (++r->frames > CHOP_WAIT) {
        done(r, 2, 0);
        return;
    }
    int q = r->pad;
    int32_t *pos = r->pos;
    if (r->phase == CHOP_PH_TEMPO) {
        float bpm, phase;
        unsigned frate;
        int t = sel_take_pad(q, &bpm, &phase, &frate);
        if (!t)
            return;
        void *obj = pad_obj(b, q);
        if (t < 0 || !obj || !frate) {
            done(r, 1, 0);
            return;
        }
        uint8_t *c = pad_cell(q);
        r->fpb = (float)frate * 60.0f / bpm / tempo_mult(c ? fw_setting(c, P_SEL_BEATS) : 0);   /* the Tempo row */
        r->anchor = phase;
        with_tempo(b, r, q, obj);
        return;
    }
    /* CHOP_PH_SCAN */
    if (b->cj.state == CHOP_SCAN)
        return;
    void *obj = pad_obj(b, q);
    if (b->cj.state != CHOP_DONE || b->cj.pad != q || !obj || b->cj.obj != obj) {
        done(r, 2, 0);
        return;
    }
    int n;
    if (r->op == CHOP_OP_BEATS)
        n = chop_onto_hits(pos, grid(r, fw_src_len(obj)), r->fpb * unit_beats[r->unit], &b->cj);
    else
        n = r->op == CHOP_OP_FIND ? chop_find(pos, r->want, &b->cj, r->seed) : chop_random(pos, r->want, &b->cj, r->seed);
    if (n <= 0) {
        done(r, 2, 0);
        return;
    }
    n = tidy(pos, n);
    place(q, pos, n);
    done(r, 0, n);
    if (r->op == CHOP_OP_FIND) {                        /* Find plays on past a chop */
        uint8_t *c = pad_cell(q);
        if (c)
            fw_set(c, P_PLAYTHRU, 1);
        fw_eng_param(ENGINE, (uint32_t)((q & 3) | (q >> 2) << 8), P_PLAYTHRU, 1, 0, 0);
    }
}
