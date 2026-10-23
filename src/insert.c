/*
 * One insert effect per pad. Original 1010music Blackbox, firmware 3.1.9. The effects themselves: insert_dsp.c.
 *
 * Where: on the pad's own mix, after its voices are summed and before its sends and its output bus, so the reverb and
 * delay hear the effect and a chord costs the same as one note. Both pad classes build that mix the same way:
 *   class A (Sample, Multisample)  FUN_080596b0: mix buffer at [sp, #0x18], "a separate buffer is in use" at [sp, #0x1c]
 *   class B (Clip, Slicer)         FUN_08067fa4: mix buffer at [sp, #0x14], the output bus in sl
 * Stock only takes a separate buffer when the pad has a send or its pan / level stage to run; otherwise the voices
 * render straight into the output bus, on top of the other pads. So there are two hooks per class (insert_thunk.S):
 *   insert_buf_a / _b   where stock reads the pad's "stage is on" byte to decide: answer yes when the pad has an insert
 *   insert_run_a / _b   the first instruction after the voice loop: run the effect on the separate buffer
 * A pad with no voice sounding is not processed at all (stock returns early), so an effect's oscillator and delay
 * line stand still until the next note. Fine for these two; a long-tailed effect would need more.
 *
 * Settings: nine per pad (ids 0x1b6 .. 0x1be), in the pad's own store, so they save with the preset. The engine does
 * not get them as commands: like lfo.c it reads the app's stores itself, one pad per block (all 16 within 43 ms).
 * State: 16 x 8.4 KB behind the other blocks master.c takes from the SDRAM at boot. No block = no effect.
 * UI (master.c): the "Insert:" row on a pad's Conf tab; INFO on that row opens the eight-knob screen for that pad.
 */
#include "insert.h"

#define FN(addr) ((addr) | 1u)
typedef void (*register_list_fn)(void *table, int param, const char *label, const char *const *names, int count,
                                 const char *xml);
typedef void (*register_num_fn)(void *table, int param, int type, const char *label, int min, int max, const char *xml);
typedef void (*store_add_fn)(void *store, int param, int value);
typedef int (*setting_fn)(const void *store, unsigned param);
typedef int (*buf_int_fn)(void *buf);
typedef int (*buf_chans_fn)(void *buf, float **left, float **right);
#define fw_register_list ((register_list_fn)FN(0x0808c0d8))
#define fw_register_num  ((register_num_fn)FN(0x0808c12c))
#define fw_store_add     ((store_add_fn)FN(0x08093ef6))
#define fw_setting       ((setting_fn)FN(0x08093e9c))
#define fw_buf_frames    ((buf_int_fn)FN(0x0804d8e8))
#define fw_buf_chans     ((buf_chans_fn)FN(0x0804d944))

#define TYPE_PCT 8
#define P_INS        0x1b6       /* Off, Phaser, Flanger */
#define P_INS_PH     0x1b7       /* the phaser's model */
#define P_INS_FL     0x1b8       /* the flanger's model */
#define P_INS_RATE   0x1b9       /* Phaser and Flanger share these six: 0x1b9 .. 0x1be (the last is Mix) */
#define P_INS_MIX    0x1be
#define P_INS_GATE   0x1c2       /* the Gate's own five: Thresh, Attack, Hold, Release, Floor. It borrows Mix,
                                    which means the same thing for every type, so its page is 0x1c2 .. 0x1c6 + Mix */
#define P_INS_IN     0x1c7       /* "Input:" - the live audio input played through this pad */

/*
 * LIVE INPUT ON A PAD (requested 2026-10-10: the input through a pad's insert, its sends and the master FX, "an extra
 * processor for the input").
 * The audio task de-interleaves the ADC, gain-stages it and writes it into a bus of its own (FUN_0804caa4, which
 * ends in FUN_080518f0) BEFORE it runs the engine (both from FUN_08041470 @0x08041502 / 0x0804151e), so the samples
 * are already there when a pad renders.
 * Turning Input on for a pad does three things: the pad is made to process even with no voice sounding (stock
 * returns early otherwise), it is given its own mix buffer, and the input is added into that buffer just before the
 * insert runs. Everything after that is stock's: the insert, the pad's Level and Pan, its reverb / delay sends, its
 * output bus, and from there the master FX and the clipper.
 *
 * WHERE THE BUS IS, and 3.2.e / 3.2.h / 3.2.w all died on getting this wrong. FUN_0804caa4 is handed the object at
 * 0x2400a9c0 and passes on the POINTER it keeps at + 0x9a74 - the engine - and the bus is that pointer + 0x128e0 +
 * 0x1583c (FUN_0805f390). The first cut added the two offsets to 0x2400a9c0 itself, which is 0x24032adc: not a
 * buffer at all. Its "needs clearing" byte happened to be set, so stock's buffer getter tried to zero a "channel" at
 * 0xa8be291b and took an unaligned-access fault in the audio task on the first block after every boot (the fault
 * record off the test unit, 2026-10-11: PC 0x080c757c, LR 0x0804d96b, r0 0xa8be291b - the very words at 0x24032adc).
 * On the test unit the engine pointer is 0x24037038 and the bus 0x2405f154: 128 frames, channels in DTCM, the idle ADC
 * in them. So the pointer is read every time and the object is checked before a sample is taken from it, and it is
 * read directly - stock's getter CLEARS a buffer whose flag asks for it, which is no business of a reader.
 */
#define ENGINE_PTR (*(const volatile uint32_t *)(0x2400a9c0u + 0x9a74u))
#define INPUT_BUS_AT (0x128e0u + 0x1583cu)
struct fw_buf {                  /* stock's buffer object, as fw_buf_frames / fw_buf_chans read it */
    int32_t cap, len;
    float *l, *r;
    uint8_t silent, stereo;      /* silent: logically empty, the samples are stale until someone clears them */
};
#define APP_PADS  (0x24020088u + 0x1840u)                /* app pad stores: + row * 0xf0 + col * 0x30 */
#define APP_MUTED(q) (*(const volatile uint8_t *)(0x24020088u + 0x8a88u + ((q) >> 2) * 0x78u + ((q) & 3u) * 0x18u + 0xdu))
                                                         /* app pad records: + 0xd = muted (as solo.c) */

static const char *const type_names[INS_TYPES] = {"Off", "Phaser", "Flanger", "Gate"};
static const char *const type_names_none[INS_TYPES] = {"Off", "---", "---", "---"};   /* no bank 2 payload: cpu.c's b2_present */
int b2_present(void);
static const char *const in_names[IN_SOURCES] = {"Off", "In 1", "In 2", "In 1+2"};
static const char *const ph_names[PH_MODELS] = {"Pebble", "Ninety", "Vibe", "Deep", "Steps"};
static const char *const fl_names[FL_MODELS] = {"Electra", "Jet", "Tape", "Metal"};

/* master.c calls these from its own registration and pad-defaults hooks. */
void insert_register(void *table)
{
    static const char *const label[6] = {"Rate:", "Depth:", "Manual:", "Feedback:", "Spread:", "Mix:"};
    static const char *const xml[6] = {"insrate", "insdepth", "insmanual", "insfeedback", "insspread", "insmix"};
    fw_register_list(table, P_INS, "Insert:", b2_present() ? type_names : type_names_none, INS_TYPES, "insfx");
    fw_register_list(table, P_INS_IN, "Input:", in_names, IN_SOURCES, "insinput");
    fw_register_list(table, P_INS_PH, "Model:", ph_names, PH_MODELS, "insphaser");
    fw_register_list(table, P_INS_FL, "Model:", fl_names, FL_MODELS, "insflanger");
    for (int i = 0; i < 6; i++)
        fw_register_num(table, P_INS_RATE + i, TYPE_PCT, label[i], 0, 1000, xml[i]);
    /* the Gate's knobs are its own, so each type's page reads the way that type works */
    static const char *const g_label[5] = {"Thresh:", "Attack:", "Hold:", "Release:", "Floor:"};
    static const char *const g_xml[5] = {"insthresh", "insattack", "inshold", "insrelease", "insfloor"};
    for (int i = 0; i < 5; i++)
        fw_register_num(table, P_INS_GATE + i, TYPE_PCT, g_label[i], 0, 1000, g_xml[i]);
}

void clipwin_defaults(void *store);   /* clipwin.c: Slip rides this chain */

void insert_defaults(void *store)
{
    /* Off; Pebble; Electra; a slow sweep, most of the way deep, centred, a little feedback, some width, the classic sum */
    static const uint16_t first[9] = {INS_OFF, PH_PEBBLE, FL_ELECTRA, 330, 750, 500, 350, 250, 500};
    for (int i = 0; i < 9; i++)
        fw_store_add(store, P_INS + i, first[i]);
    /* The Gate as it first comes up: the settings read off pad 10 of the test unit once it was gating a drum pad
       (2026-10-11) - Thresh 80 %, Attack 0, Hold 0, Release 20 %, Floor 0. 3.2.u shipped Thresh 35 %, which is about
       -43 dB and opens for almost anything, so switching the Gate on did nothing audible. */
    static const uint16_t gate_first[5] = {800, 0, 0, 200, 0};
    for (int i = 0; i < 5; i++)
        fw_store_add(store, P_INS_GATE + i, gate_first[i]);
    fw_store_add(store, P_INS_IN, IN_OFF);
    clipwin_defaults(store);                         /* clipwin.c: Slip, on the same chain */
}

/* ---- the engine ---- */

struct ins_bank {
    uint32_t magic, scan;
    struct ins_set set[16];
    struct ins_state st[16];
};
#define INS_MAGIC  0x494e5332u   /* "INS2": bumped with the layout. The SDRAM keeps its contents through a reset and a
                                    reflash, so an old magic would vouch for bytes an older build never wrote. */
#define INS_OFFSET (0x56800u + 0xb000u)                  /* behind Prism, the LFOs, the USB ring and the S950 bank */
_Static_assert(sizeof(struct ins_bank) <= 0x22000, "master.c's EXTRA_BYTES gives the bank 0x22000");

uint8_t *master_block(void);     /* master.c: the boot-time SDRAM block, or 0 */

static struct ins_bank *bank(void)
{
    uint8_t *mem = master_block();
    if (!mem)
        return 0;
    struct ins_bank *b = (struct ins_bank *)(mem + INS_OFFSET);
    if (b->magic != INS_MAGIC) {
        /* Everything the audio path reads before insert_tick has been round all sixteen pads (43 ms). `input` was
           not cleared here at first: it came up as whatever the SDRAM held, so on the first blocks after a boot
           nearly every pad "carried the input". */
        for (int i = 0; i < 16; i++) {
            b->set[i].type = INS_OFF;
            b->set[i].input = IN_OFF;
            b->st[i].type = INS_OFF;
        }
        b->scan = 0;
        b->magic = INS_MAGIC;
    }
    return b;
}

static unsigned pad_index(const uint8_t *pad)
{
    uint32_t id = *(const uint32_t *)(pad + 0x18);       /* col | row << 8 */
    return ((id >> 8) & 3) * 4 + (id & 3);
}

static float knob(const void *store, unsigned param)
{
    int v = fw_setting(store, param);
    return (float)(v < 0 ? 0 : v > 1000 ? 1000 : v) * 0.001f;
}

/* duck_block calls this once per engine block: one pad's settings per call. */
void insert_tick(void)
{
    struct ins_bank *b = bank();
    if (!b)
        return;
    unsigned q = b->scan++ & 15;
    const void *store = (const void *)(APP_PADS + (q >> 2) * 0xf0u + (q & 3) * 0x30u);
    struct ins_set *p = &b->set[q];
    unsigned type = (unsigned)fw_setting(store, P_INS);
    if (type >= INS_TYPES)
        type = INS_OFF;
    unsigned in = (unsigned)fw_setting(store, P_INS_IN);
    /* A muted pad carries no input. Stock's mute acts on the pad's voices and the input joins the mix after them,
       so on 3.2.x muting the pad left the line sounding (reported 2026-10-11). The app's own pad record is what
       solo.c reads and writes, so MUTE, the Mixer's mute view and a solo on another pad all land here. */
    if (in >= IN_SOURCES || APP_MUTED(q))
        in = IN_OFF;
    p->input = (uint8_t)in;
    if (type == INS_OFF) {
        p->type = INS_OFF;
        b->st[q].type = INS_OFF;                             /* so it starts clean when it is switched on again */
        return;
    }
    unsigned model = 0, models = 1;
    if (type == INS_PHASER) {
        model = (unsigned)fw_setting(store, P_INS_PH);
        models = PH_MODELS;
    } else if (type == INS_FLANGER) {
        model = (unsigned)fw_setting(store, P_INS_FL);
        models = FL_MODELS;
    }
    p->model = (uint8_t)(model < models ? model : 0);        /* the Gate has only one */
    p->mix = knob(store, P_INS_MIX);                     /* Phaser and Flanger share this one */
    if (type == INS_GATE) {
        p->mix = 1.0f;                                   /* the Gate does not: the shared Mix comes up at 50 %, which
                                                            left a closed gate only 6 dB down (the first try, "not
                                                            hearing the gate"). Floor is its how-far-down knob. */
        p->thresh = knob(store, P_INS_GATE);
        p->attack = knob(store, P_INS_GATE + 1);
        p->hold = knob(store, P_INS_GATE + 2);
        p->release = knob(store, P_INS_GATE + 3);
        p->floor = knob(store, P_INS_GATE + 4);
    } else {
        p->rate = knob(store, P_INS_RATE);
        p->depth = knob(store, P_INS_RATE + 1);
        p->manual = knob(store, P_INS_RATE + 2);
        p->fb = knob(store, P_INS_RATE + 3);
        p->spread = knob(store, P_INS_RATE + 4);
    }
    p->type = (uint8_t)type;
}

/* insert_buf_a / _b: does this pad need its own mix buffer for an insert? No floating point in here: the thunks are
   entered with the caller's float registers live. */
int insert_on(const uint8_t *pad)
{
    struct ins_bank *b = bank();
    if (!b)
        return 0;
    const struct ins_set *p = &b->set[pad_index(pad)];
    return p->type != INS_OFF || p->input != IN_OFF;         /* live input needs its own buffer too */
}

/* insert_live_a (insert_thunk.S): does this pad have to render even with no voice sounding? */
int insert_live(const uint8_t *pad)
{
    struct ins_bank *b = bank();
    return b && b->set[pad_index(pad)].input != IN_OFF;
}

/* Could `n` floats really be at p? The on-chip RAMs and the SDRAM; anything else is not a channel. */
static int samples_at(const float *p, int n)
{
    uint32_t a = (uint32_t)p, end = a + 4u * (uint32_t)n;
    return !(a & 3u) && ((a >= 0x20000000u && end <= 0x20020000u) || (a >= 0x24000000u && end <= 0x24080000u)
                         || (a >= 0xc0000000u && end <= 0xc4000000u));
}

/* the live input, added into the pad's own mix just before the insert runs */
static void add_input(const struct ins_set *p, float *l, float *r, int n)
{
    uint32_t engine = ENGINE_PTR;
    if ((engine & 3u) || engine < 0x24000000u || engine >= 0x24080000u - INPUT_BUS_AT - sizeof(struct fw_buf))
        return;
    const volatile struct fw_buf *bus = (const volatile struct fw_buf *)(engine + INPUT_BUS_AT);
    int bn = bus->len ? bus->len : bus->cap;
    const float *il = bus->l, *ir = bus->stereo ? bus->r : il;
    if (bus->silent || bn <= 0 || bn > 1024 || !samples_at(il, bn) || !samples_at(ir, bn))
        return;
    if (bn < n)
        n = bn;
    const float *a = p->input == IN_RIGHT ? ir : il;
    const float *b2 = p->input == IN_LEFT ? il : ir;
    for (int i = 0; i < n; i++) {
        l[i] += a[i];
        if (r)
            r[i] += b2[i];
    }
}

/* insert_run_a / _b: the pad's voices are in `buf`, and it is the pad's own buffer. */
void insert_process(const uint8_t *pad, void *buf)
{
    struct ins_bank *b = bank();
    if (!b || !buf)
        return;
    unsigned q = pad_index(pad);
    const struct ins_set *p = &b->set[q];
    if (p->type == INS_OFF && p->input == IN_OFF)
        return;
    float *li = 0, *ri = 0;
    int ni = fw_buf_frames(buf);
    fw_buf_chans(buf, &li, &ri);
    if (p->input != IN_OFF && li && ni > 0)
        add_input(p, li, ri, ni);
    if (p->type == INS_OFF)
        return;                                              /* input only: it is already in the pad's mix */
    struct ins_state *s = &b->st[q];
    if (s->type != p->type || s->model != p->model) {
        for (unsigned i = 0; i < sizeof *s / 4; i++)
            ((volatile uint32_t *)s)[i] = 0;
        s->type = p->type;
        s->model = p->model;
    }
    float *l = 0, *r = 0;
    int n = fw_buf_frames(buf);
    fw_buf_chans(buf, &l, &r);
    if (l && n > 0 && b2_live())  /* ins_render is in bank 2: bypass rather than fault on a bad one */
        ins_render(s, p, l, r, n);
}
