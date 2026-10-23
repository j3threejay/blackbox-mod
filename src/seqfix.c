/*
 * Sequencer: a note added or moved just ahead of the playhead plays on this pass. Original 1010music Blackbox, 3.1.9.
 *
 * Stock: a pattern keeps its notes sorted by start in a list whose [2] is the play index (the next note to play; the
 * player plays notes while start + loop start < now and advances it). A sorted insert (FUN_08063938) bumps the index
 * when the new note lands at or before it, so a note dropped right ahead of the playhead lands exactly at the index
 * and is counted as already played; so is one added after the last note. It sounds only on the next pass.
 *
 * This wraps the note-seq object's edit methods (vtable 0x080d0744: +0x58 add / update, +0x5c delete). After the
 * stock edit, if the edited pattern is the one playing, the index is recomputed from where the playhead really is:
 * index = number of notes with start < now - loop start; the note just placed also plays if it landed at most
 * GRACE ticks behind the playhead with nothing in between. Notes ahead of the playhead play on time this pass; notes
 * behind it, or already under it, wait for the next pass; nothing is skipped or played twice.
 * "now" is recorded per sequence by wrapping the call to the player (it is computed exactly as the player does, so
 * it is there even while the pattern is empty). Time-stretched sequences (+0x5e) are left stock.
 */
#include <stdint.h>

#define FN(addr) ((addr) | 1u)

typedef void (*list_set_fn)(void *list, void *event);
typedef void (*list_del_fn)(void *list, uint32_t id);
typedef int64_t *(*clock_fn)(int64_t *out, const void *clock, uint32_t lo, int32_t hi);
typedef void (*player_fn)(uint8_t *seq, const void *clock, int32_t a, int32_t b, uint32_t e);

#define fw_list_set ((list_set_fn)FN(0x08063b38))
#define fw_list_del ((list_del_fn)FN(0x08063c08))
int64_t *groove_s2t(int64_t *out, uint8_t *clock, uint32_t lo, int32_t hi);   /* groove.c */
#define fw_clock(out, clk, lo, hi) groove_s2t((out), (uint8_t *)(clk), (lo), (hi))   /* clock position -> sequencer time, through the Groove (3.3.q) */
#define fw_player   ((player_fn)FN(0x0805d1d8))          /* plays the notes due in this block */

#define SEQ_PATTERNS  0x320      /* pattern states, 0x48 bytes each */
#define PATTERN_SIZE  0x48
#define PATTERNS      0x20
#define SEQ_PLAYING   0xc20      /* -> the playing pattern state */
#define SEQ_STRETCH   0x5e       /* time-stretched playback: event times are scaled; left alone */
#define PAT_LIST      0x0c       /* event list: [0] u16 *handles (sorted), [1] count, [2] play index, [4] -> pool */
#define PAT_BASE      0x38       /* int64: this pass's loop start, same units as event starts */
#define EVENT_SIZE    0x18
#define EVENT_START   0x04
#define EVENT_ID      0x0c
#define GRACE         240        /* ticks (960 per 16th = a 64th): a note placed this close behind the playhead
                                    still plays, a hair late; the report: notes "close" ahead did not sound */

void bkp_enable(void);

#define SLOTS 32
struct seq_clock {
    uint32_t magic;
    struct {
        const void *seq;
        int64_t now;
    } slot[SLOTS];
};
#define CLK ((volatile struct seq_clock *)0x38800700u)   /* backup SRAM, after comp.c's state */
#define MAGIC 0x53514331u        /* "SQC1" */

static int find(const void *seq, int create)
{
    bkp_enable();
    if (CLK->magic != MAGIC) {
        for (int i = 0; i < SLOTS; i++)
            CLK->slot[i].seq = 0;
        CLK->magic = MAGIC;
    }
    int free = -1;
    for (int i = 0; i < SLOTS; i++) {
        if (CLK->slot[i].seq == seq)
            return i;
        if (free < 0 && CLK->slot[i].seq == 0)
            free = i;
    }
    if (create && free >= 0) {
        CLK->slot[free].seq = seq;
        return free;
    }
    return -1;
}

/*
 * Replaces the one call to the player (bl @0x0805d9a4). The player's first act is now = FUN_08069c94(clock,
 * clock[0..1] + a + b), then it plays every note with start + loop start < now; record that same now.
 */
void seq_play(uint8_t *seq, const void *clock, int32_t a, int32_t b, uint32_t e)
{
    int64_t t = *(const int64_t *)clock + (int64_t)a + (int64_t)b, now = 0;
    fw_clock(&now, clock, (uint32_t)t, (int32_t)(t >> 32));
    int i = find(seq, 1);
    if (i >= 0)
        CLK->slot[i].now = now;
    fw_player(seq, clock, a, b, e);
}

static void fix_index(uint8_t *seq, unsigned idx, uint32_t edited_id)
{
    uint8_t *pattern = seq + SEQ_PATTERNS + idx * PATTERN_SIZE;
    if (*(uint8_t **)(seq + SEQ_PLAYING) != pattern || seq[SEQ_STRETCH])
        return;
    int i = find(seq, 0);
    if (i < 0)
        return;
    int64_t rel = CLK->slot[i].now - *(int64_t *)(pattern + PAT_BASE);
    uint32_t *list = (uint32_t *)(pattern + PAT_LIST);
    const uint16_t *handles = (const uint16_t *)list[0];
    uint32_t count = list[1];
    const uint8_t *pool = *(const uint8_t **)list[4];
    uint32_t k = 0;
    while (k < count && (int64_t)*(const uint32_t *)(pool + (handles[k] & 0x3fff) * EVENT_SIZE + EVENT_START) < rel)
        k++;
    /* The note just placed, if it landed a hair behind the playhead and nothing else sits between it and the
       playhead: play it now (slightly late) instead of a whole pass later. */
    if (edited_id && k > 0) {
        const uint8_t *ev = pool + (handles[k - 1] & 0x3fff) * EVENT_SIZE;
        if (*(const uint32_t *)(ev + EVENT_ID) == edited_id && (int64_t)*(const uint32_t *)(ev + EVENT_START) >= rel - GRACE)
            k--;
    }
    list[2] = k;
}

/* Note-seq vtable +0x58 (stock 0x0805c0d8): add or update a note in pattern idx. */
void seq_set(uint8_t *seq, void *event, void *unused, unsigned idx)
{
    (void)unused;
    if (idx >= PATTERNS)
        return;
    fw_list_set(seq + SEQ_PATTERNS + idx * PATTERN_SIZE + PAT_LIST, event);
    fix_index(seq, idx, *(const uint32_t *)((const uint8_t *)event + EVENT_ID));
}

/* Note-seq vtable +0x5c (stock 0x0805c0f0): delete note `id` from pattern idx. */
void seq_del(uint8_t *seq, uint32_t id, unsigned idx)
{
    if (idx >= PATTERNS)
        return;
    fw_list_del(seq + SEQ_PATTERNS + idx * PATTERN_SIZE + PAT_LIST, id);
    fix_index(seq, idx, 0);
}
