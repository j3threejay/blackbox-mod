/*
 * Live mode: the keyboard plays the pad selected on the Pads screen. Original 1010music Blackbox, firmware 3.1.9.
 *
 * Stock: notes on the MIDI Seq channel go into the selected sequence and sound on the pad that sequence is mapped to
 * (a Keys sequence) or go out as MIDI (a MIDI sequence). To play a different pad from a keyboard you go to SEQS,
 * pick the square, and make sure it is a Keys sequence mapped to that pad. On stage that is too many steps.
 *
 * With Live Mode on, notes on the MIDI Seq channel play the selected pad instead, chromatically and with their
 * velocity, the same way the Keys screen plays it. Touch another pad and the keyboard follows. Other channels (Global
 * In, a pad's own MIDI In) are untouched, and with Live Mode Off nothing changes at all.
 *
 * How: the audio task's MIDI parser (FUN_0804cb1c) turns each note on / note off / poly pressure into an engine
 * event (type 5 / 6 / 0xc: channel 0-based at +8, note +0xc, velocity +0x10) and posts it to the engine's input bus
 * (FUN_080518dc @0x0804cbf0, the one call all three share). live_post replaces that call. For a note on the MIDI Seq
 * channel it posts the engine's own pad note message instead, the one the Keys screen sends (FUN_0804c61c builds it:
 * 0x42 on / 0x43 off, pad +8 as col | row << 8 | layer << 16, note +0xc, velocity +0x10 (0 = 100), +0x14 = 1). The
 * bus distributor (0x080507a6) turns that into the pad's note on with the velocity, exactly as for a Keys key.
 * The selected pad is the app's current cell (app +0x14, u16 layer << 8 | row << 4 | col), written by FUN_080978e4
 * whenever a pad is selected.
 *
 * Each held note remembers the pad it started, so its note off reaches that pad even after the selection moved on or
 * Live Mode was switched off with a key down. That table is in backup SRAM, switched on (bkp_enable) before every use:
 * the first cut touched it with the clock possibly off, and a note on the MIDI Seq channel at boot could fault.
 *
 * Setting: "Live Mode:" Off / On on Tools > MIDI, after USB Dev Out (global, saved with the other Tools settings as
 * "midilivemode").
 */
#include <stdint.h>

#define FN(addr) ((addr) | 1u)

typedef void (*register_fn)(void *table, int param, const char *label, const char *const *names, int count,
                            const char *xml);
typedef void (*store_add_fn)(void *store, int param, int value);
typedef int (*setting_fn)(const void *store, int param);
typedef void (*post_fn)(void *engine, const void *event);

#define fw_register_list ((register_fn)FN(0x0808c0d8))
#define fw_store_add     ((store_add_fn)FN(0x08093ef6))
#define fw_setting       ((setting_fn)FN(0x08093e9c))
#define fw_post          ((post_fn)FN(0x080518dc))

#define APP              ((const uint8_t *)0x24020088u)
#define SETTINGS         ((const void *)(0x24020088u + 0x8c90u))   /* app: global settings store */
#define APP_CELL         0x14     /* u16: the selected cell, layer << 8 | row << 4 | col */
#define PARAM_LIVE       0x1f0    /* free in stock and in the mod, and not special-cased by stock's cell get / set */
#define PARAM_MIDI_SEQ   0x79     /* "MIDI Seq:" None, Ch 1 .. 16 */

#define EV_NOTE_ON  5
#define EV_NOTE_OFF 6
#define MSG_PAD_ON  0x42
#define MSG_PAD_OFF 0x43

struct event {                    /* the engine bus entry: 24 bytes */
    uint8_t type, _r[7];
    uint32_t a;                   /* MIDI: channel. pad message: col | row << 8 | layer << 16 */
    uint32_t note;
    uint32_t velocity;
    uint16_t keyed, tag;          /* pad message: 1 = play at `note` (0 = the pad's own pitch); tag 0 */
};
_Static_assert(sizeof(struct event) == 24, "the engine bus entry is 24 bytes");

/* Backup SRAM between usbdev.c's MIDI queue (0x38800908, 32 words) and fx2.c's state (0x38800a00). */
struct live_state {
    uint32_t magic;
    uint32_t held[4];             /* a bit per note: started by Live Mode and not released yet */
    uint8_t pad[128 / 2];         /* the pad index (row * 4 + col) each held note was started on, a nibble per note */
};
#define S ((volatile struct live_state *)0x38800990u)
#define MAGIC 0x4c495631u         /* "LIV1" */
_Static_assert(0x38800990u + sizeof(struct live_state) <= 0x38800a00u, "live.c's state runs into fx2.c's");

static const char *const live_names[2] = {"Off", "On"};

void live_register(void *table)
{
    fw_register_list(table, PARAM_LIVE, "Live Mode:", live_names, 2, "midilivemode");
}

void live_defaults(void *store)
{
    fw_store_add(store, PARAM_LIVE, 0);
}

void bkp_enable(void);           /* od.c: backup SRAM clock + write access, which nothing guarantees is on yet */

static void ensure(void)
{
    bkp_enable();
    if (S->magic == MAGIC)
        return;
    for (int i = 0; i < 4; i++)
        S->held[i] = 0;
    S->magic = MAGIC;
}

static int held(unsigned note)
{
    return (S->held[note >> 5] >> (note & 31)) & 1;
}

static unsigned held_pad(unsigned note)
{
    return (S->pad[note >> 1] >> ((note & 1) * 4)) & 0xf;
}

static void post_pad(void *engine, int type, unsigned pad, unsigned note, unsigned velocity)
{
    struct event m = {0};
    m.type = (uint8_t)type;
    m.a = (pad & 3) | (pad >> 2) << 8;
    m.note = note;
    m.velocity = velocity;
    m.keyed = 1;
    fw_post(engine, &m);
}

/* Replaces the MIDI parser posting a note on / note off / poly pressure to the engine bus (bl @0x0804cbf0). */
void live_post(void *engine, const struct event *ev)
{
    int on = ev->type == EV_NOTE_ON && ev->velocity != 0;
    int off = ev->type == EV_NOTE_OFF || (ev->type == EV_NOTE_ON && ev->velocity == 0);
    unsigned note = ev->note, seq;
    if ((!on && !off) || note > 127 || (seq = (unsigned)fw_setting(SETTINGS, PARAM_MIDI_SEQ)) == 0 || seq > 16 ||
        ev->a != seq - 1) {
        fw_post(engine, ev);
        return;
    }
    ensure();
    if (off) {
        if (!held(note)) {                       /* not ours: a note that started before Live Mode went on */
            fw_post(engine, ev);
            return;
        }
        S->held[note >> 5] &= ~(1u << (note & 31));
        post_pad(engine, MSG_PAD_OFF, held_pad(note), note, 0);
        return;
    }
    unsigned cell = *(const volatile uint16_t *)(APP + APP_CELL);
    if (fw_setting(SETTINGS, PARAM_LIVE) != 1 || cell > 0x33 || (cell & 0xf) > 3) {
        fw_post(engine, ev);                     /* Off, or the selection is not one of the 16 pads */
        return;
    }
    unsigned pad = (cell >> 4) * 4 + (cell & 0xf), shift = (note & 1) * 4;
    if (held(note))                              /* the same key again before its release: end the old one first */
        post_pad(engine, MSG_PAD_OFF, held_pad(note), note, 0);
    S->pad[note >> 1] = (uint8_t)((S->pad[note >> 1] & ~(0xfu << shift)) | pad << shift);
    S->held[note >> 5] |= 1u << (note & 31);
    post_pad(engine, MSG_PAD_ON, pad, note, ev->velocity);
}
