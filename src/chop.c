/*
 * ChopShop (the Slicer chop modes): slice points placed by our code. Original 1010music Blackbox, firmware 3.1.9.
 *
 * chop_set_slices replaces a pad's slice points the way stock's Slice to Grid does (FUN_08099434; research/slicer/
 * SLICE_POINTS_RE.md 3.1): the app cell's sorted list (cell + 0x28, at most 128, the copy the preset saves), engine
 * message 0x3c to the pad's player (1000 = clear, 1 = insert: only what the app list took), ONE 0x66 so the screen
 * copies the cell again, and the project-changed flag. App / view context only (view code runs in the app task).
 * chop_beats lays the points on a beat grid: anchor + k x frames per beat x unit, whole file, at most 128; a pickup
 * slice at 0 when beat one is later than that (otherwise the audio before it could not be played as a slice).
 * CPU: none on the audio side; one pass over at most 128 points when asked.
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
 * Find / Random chops (Serato Sample's Find Samples / Set Random, on the Blackbox's slices) from a finished beat scan.
 * Beats quieter than 1/20 of the loudest are never picked (silence, fades). want points, ascending, in out[].
 *   Find: the track cut into `want` equal stretches of beats; in each, the beat that hits hardest, a bar start counted
 *         1.5x, everything nudged by a seeded random 0.6..1.4 so another roll (another seed) finds other chops.
 *   Random: `want` different usable beats at random.
 * Returns the count (fewer when the track has fewer usable beats).
 */
static uint32_t rnd(uint32_t *s)
{
    uint32_t x = *s ? *s : 0x9e3779b9u;
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    *s = x;
    return x;
}

static float loudest(const struct chop_job *j)
{
    float m = 0.0f;
    for (int b = 0; b < j->n; b++)
        if (j->level[b] > m) m = j->level[b];
    return m;
}

static int32_t at(const struct chop_job *j, int b)
{
    return (int32_t)(j->anchor + (float)b * j->fpb + 0.5f);
}

int chop_find(int32_t *out, int want, const struct chop_job *j, uint32_t seed)
{
    if (j->state != CHOP_DONE || j->n <= 0 || want <= 0)
        return 0;
    float floor = loudest(j) * 0.05f;
    int n = 0;
    for (int s = 0; s < want; s++) {
        int lo = j->n * s / want, hi = j->n * (s + 1) / want, best = -1;
        float bs = 0.0f;
        for (int b = lo; b < hi; b++) {
            float sc = (float)(rnd(&seed) >> 8) * (0.8f / 16777216.0f) + 0.6f;
            if (j->level[b] <= floor)
                continue;
            sc *= j->hit[b] * (b % 4 == 0 ? 1.5f : 1.0f) + 1e-6f;
            if (sc > bs) { bs = sc; best = b; }
        }
        if (best >= 0)
            out[n++] = at(j, best);
    }
    return n;
}

int chop_random(int32_t *out, int want, const struct chop_job *j, uint32_t seed)
{
    if (j->state != CHOP_DONE || j->n <= 0 || want <= 0)
        return 0;
    float floor = loudest(j) * 0.05f;
    int usable = 0;
    for (int b = 0; b < j->n; b++)
        usable += j->level[b] > floor;
    if (want > usable)
        want = usable;
    int n = 0;
    for (int b = 0; b < j->n && n < want; b++) {         /* selection sampling: each usable beat with p = left / remaining */
        if (j->level[b] <= floor)
            continue;
        if ((int)(rnd(&seed) % (uint32_t)usable) < want - n)
            out[n++] = at(j, b);
        usable--;
    }
    return n;
}

/*
 * The driver (GUI task, every frame: theme_compose calls chop_poll). chop_request starts an operation on pad q: the
 * tempo first (the detector, unless a re-roll of the same pad can reuse the last one), then Beats lays the points at
 * once; Find / Random scan the whole file for beat levels (chop_dsp.c, audio side) and pick from it. Find also turns
 * PlayThru on (Serato's Find Samples plays on past a chop).
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
#define CUE_DICE      36                                /* ~0.6 s of tumbling dice */
#define CUE_SHOW      90                                /* ~1.5 s of "32 chops" / "Fail n" */

static const float unit_beats[5] = { 0.25f, 0.5f, 1.0f, 2.0f, 4.0f };

static uint16_t cell_of(int q) { return (uint16_t)((q >> 2) << 4 | (q & 3)); }

static void *pad_obj(struct str_bank *b, int q)
{
    uint8_t *eng = b->clip[q].eng;
    return eng ? *(void **)(eng + PAD_SOURCE) : 0;
}

void chop_request(int q, int op, int unit, int want)
{
    struct str_bank *b = stretch_bank();
    if (!b || q < 0 || q > 15 || op <= CHOP_OP_NONE || op > CHOP_OP_RANDOM)
        return;
    struct chop_run *r = &b->cr;
    int reuse = r->pad == q && r->fpb > 0.0f && op != CHOP_OP_BEATS && r->op == op && r->phase == CHOP_PH_IDLE;
    r->op = (uint8_t)op;
    r->pad = (uint8_t)q;
    r->unit = (uint8_t)(unit < 0 ? 0 : unit > 4 ? 4 : unit);
    r->want = want > 0 && want <= CHOP_MAX ? want : 32;
    r->seed = r->seed * 1664525u + 1013904223u + b->seq;
    r->frames = 0;
    r->fail = 0;
    r->spare[0] = CUE_DICE;
    r->spare[1] = 0;
    if (reuse && b->cj.state == CHOP_DONE && b->cj.pad == q) {
        r->phase = CHOP_PH_SCAN;                        /* a re-roll: same scan, new seed */
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

/* The Roll row's text for pad q: tumbling dice, "Rolling..", the result, then a resting die. ASCII only: the font
   draws 0x20..0x7f (research, 10-26). buf holds at least 16. */
const char *chop_roll_text(int q, char *buf)
{
    static const char *const dice[6] = {"[.]", "[:]", "[:.]", "[::]", "[:.:]", "[:::]"};
    struct str_bank *b = stretch_bank();
    const struct chop_run *r = b ? &b->cr : 0;
    if (r && q == CHOP_ANY_PAD)
        q = r->pad;
    if (!r || r->pad != q)
        return "[:.:]";
    if (r->spare[0])
        return dice[(CUE_DICE - r->spare[0]) / 6 % 6];
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

/* The tempo is known (r->fpb, r->anchor): Beat Count to match, then the chops (Beats) or the beat scan (Find, Random) */
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
    if (r->op == CHOP_OP_BEATS) {
        int n = chop_beats(pos, CHOP_MAX, len, (int32_t)r->anchor, r->fpb, unit_beats[r->unit]);
        place(q, pos, n);
        done(r, 0, n);
        return;
    }
    chop_scan_start(&b->cj, q, obj, len, fw_src_stereo(obj), r->anchor, r->fpb);
    b->cj.fetch = chop_fw_fetch;
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
    if (b->cj.state != CHOP_DONE || b->cj.pad != q) {
        done(r, 2, 0);
        return;
    }
    int n = r->op == CHOP_OP_FIND ? chop_find(pos, r->want, &b->cj, r->seed) : chop_random(pos, r->want, &b->cj, r->seed);
    if (n <= 0) {
        done(r, 2, 0);
        return;
    }
    place(q, pos, n);
    done(r, 0, n);
    if (r->op == CHOP_OP_FIND) {
        struct { uint32_t tag; uint16_t pad, rr; } ref = { CELL_REF, cell_of(q), 0 };
        uint8_t *c = fw_cell(APP, &ref);
        if (c)
            fw_set(c, P_PLAYTHRU, 1);
        fw_eng_param(ENGINE, (uint32_t)((q & 3) | (q >> 2) << 8), P_PLAYTHRU, 1, 0, 0);
    }
}
