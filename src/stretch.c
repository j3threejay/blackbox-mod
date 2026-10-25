/*
 * Clip "Stretch:" models: the hooks (bank 1). The DSP and the per-segment bookkeeping are in stretch_dsp.c (bank 2).
 *
 * Setting: one list per pad (P_STRETCH: Stock, Smooth, Keyframe, Cyclic), on the Clip pad's POS page under Sync, in
 * the pad's own store so it saves with the preset. Stock = 0, so old presets play as they did.
 * The engine side reads it through stretch_tick (one pad per block, from insert_tick) into the SDRAM area, and
 * clip_read (filter.c) asks stretch_read first: -1 = stock's reader (or the machine modes) as before.
 * Memory: STR_BYTES of SDRAM from the firmware's permanent allocator, taken once at boot in master_alloc, apart from
 * the master block so a failed allocation only turns the models off. Its address sits in the master block.
 */
#include <stdint.h>
#include "stretch.h"

#pragma GCC optimize("Os", "no-tree-loop-distribute-patterns")

#define FN(addr) ((addr) | 1u)
typedef void (*register_fn)(void *table, int param, const char *label, const char *const *names, int count,
                            const char *xml);
typedef void (*store_add_fn)(void *store, int param, int value);
typedef int (*setting_fn)(const void *store, int param);
typedef uint32_t (*perm_alloc_fn)(uint32_t bytes, int one);
#define fw_register_list ((register_fn)FN(0x0808c0d8))
#define fw_store_add     ((store_add_fn)FN(0x08093ef6))
#define fw_setting       ((setting_fn)FN(0x08093e9c))
#define fw_perm_alloc    ((perm_alloc_fn)FN(0x0804436c))

#define P_STRETCH  0x14c          /* clean id (unregistered by stock, no stock compare): test_param_ids.py checks it */
#define STR_BYTES  ((sizeof(struct str_bank) + 0xfffu) & ~0xfffu)

uint8_t *master_block(void);      /* master.c */
int b2_live(void);                /* cpu.c */
int b2_present(void);

static const char *const names[STR_MODELS] = {"Stock", "Smooth", "Keyframe", "Cyclic"};
static const char *const names_none[STR_MODELS] = {"Stock", "---", "---", "---"};   /* no bank 2 payload */

typedef void (*register_num_fn)(void *table, int param, int type, const char *label, int min, int max, const char *xml);
#define fw_register_num ((register_num_fn)FN(0x0808c12c))
#define P_SEL_START 0x15c         /* clipsel.c: the Clip selection (Waveform screen) */
#define P_SEL_END   0x15d
#define P_SEL_BEATS 0x15e
#define BEAT_NAMES  ((const char *const *)0x080eb810u)   /* stock Beat Count's "Auto", "1" .. "512" */

void stretch_register(void *table)
{
    fw_register_list(table, P_STRETCH, "Stretch:", b2_present() ? names : names_none, STR_MODELS, "stretch");
    /* registered like stock's Sample Start (0x8f): a position (type 0xd) in frames; the screen sets the real range */
    fw_register_num(table, P_SEL_START, 0xd, "Start:", 0, 1000, "selstart");
    fw_register_num(table, P_SEL_END, 0xd, "End:", 0, 1000, "selend");
    fw_register_list(table, P_SEL_BEATS, "Beats:", BEAT_NAMES, 0x201, "selbeats");
}

void stretch_defaults(void *store)
{
    fw_store_add(store, P_STRETCH, STR_STOCK);
    fw_store_add(store, P_SEL_START, 0);                 /* no selection, Beats Auto: stock */
    fw_store_add(store, P_SEL_END, 0);
    fw_store_add(store, P_SEL_BEATS, 0);
}

/* master_alloc, once per boot: the area, its address into the master block's word, and a clean start */
void stretch_alloc(uint8_t *master)
{
    if (!master)
        return;
    uint32_t mem = fw_perm_alloc(STR_BYTES, 1);
    *(volatile uint32_t *)(master + STR_PTR_OFFSET) = mem;
    if (mem)
        *(volatile uint32_t *)mem = 0;
}

static struct str_bank *bank(void)
{
    uint8_t *m = master_block();
    if (!m)
        return 0;
    uint32_t a = *(volatile uint32_t *)(m + STR_PTR_OFFSET);
    if (a < 0xc0000000u || a > 0xc4000000u - STR_BYTES)
        return 0;
    struct str_bank *b = (struct str_bank *)a;
    if (b->magic != STR_BANK_MAGIC) {
        uint32_t *w = (uint32_t *)b;
        for (unsigned i = 0; i < ((uint8_t *)b->scratch - (uint8_t *)b) / 4; i++)
            w[i] = 0;                                   /* everything up to the scratch: the rest is per-slot magic */
        for (int i = 0; i < STR_SLOTS; i++)
            b->st[i].magic = 0;
        b->tj.state = TEMPO_IDLE;
        b->tj.req = b->tj.served = 0;
        b->magic = STR_BANK_MAGIC;
    }
    return b;
}

void sel_tempo_tick(struct str_bank *b);             /* clipsel.c */

struct str_bank *stretch_bank(void)                  /* clipsel.c */
{
    return bank();
}

/* duck_block, once per engine block: one pad's setting per call */
#define APP_PADS (0x24020088u + 0x1840u)                 /* app pad stores: + row * 0xf0 + col * 0x30 */
void stretch_tick(void)
{
    struct str_bank *b = bank();
    if (!b)
        return;
    unsigned q = b->scan++ & 15;
    const void *store = (const void *)(APP_PADS + (q >> 2) * 0xf0u + (q & 3) * 0x30u);
    int v = fw_setting(store, P_STRETCH);
    b->model[q] = (uint8_t)(v > 0 && v < STR_MODELS ? v : STR_STOCK);
    sel_tempo_tick(b);                                  /* clipsel.c: a tempo detection's next step */
}

/* clip_read (filter.c), before anything else: 1 = read through a model, -1 = not ours */
int stretch_read(float rate, uint8_t *pad, int32_t pos, int n, int *used, float *frac, void *out, void **result)
{
    if (!b2_live())
        return -1;
    struct str_bank *b = bank();
    if (!b)
        return -1;
    uint32_t id = *(const uint32_t *)(pad + 0x18);       /* col | row << 8 */
    unsigned q = ((id >> 8) & 3) * 4 + (id & 3);
    int model = b->model[q];
    if (model == STR_STOCK)
        return -1;
    return str_clip((uint8_t *)b, pad, model, rate, pos, n, used, frac, out, result);
}
