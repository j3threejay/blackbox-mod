/*
 * The pad's ADSR as a modulation source ("ENV" in the Source list). Original 1010music Blackbox, firmware 3.1.9.
 *
 * Stock per-voice sources are velocity (code 0xd), key (0xe) and the LFO (4): the pad keeps them in a list of up to 8
 * entries (pad +0x4ec: float amount, u16 target +4, u16 source +6, u8 slot +8; count +0x54c), and every voice attaches
 * them to its own copies of the parameters (FUN_0805623c: source -> voice +0x84 / +0x8c / +0x520). The preset format
 * already names codes 1..3 "env1".."env3", but the engine drops them.
 *
 * ENV = code 1 = the voice's amp envelope: object at voice +0x28, its level (0..1, written every block by
 * FUN_0806a6c0) at +0x28 of that. A source is read at pointer +4, so the source pointer is voice +0x4c.
 *   env_mod_setup  wraps the pad's slot setup (FUN_08056810, one call @0x0805a138): stock only lists codes 4, 0xd,
 *                  0xe, so ENV goes in as velocity and the entry's source is put back to 1.
 *   env_mod_attach wraps FUN_0805623c (calls @0x08058c34, 0x0805a8da): after stock copied the parameters and attached
 *                  its own sources, attach the ENV entries with the same target -> parameter map stock uses.
 *
 * Clip and Slicer pads (pad class B, 3.1.D) have no list: the pad object holds two playing layers (at pad +0x260 and
 * +0x670, 0x410 apart, the second for the overlap when a clip or slice hands over), each with its own copies of the
 * parameters, and FUN_08067018 attaches a slot's source to both straight away. It only knows velocity, key, the LFO
 * and the MIDI sources, so env_mod_setup_b (the one call @0x080685c4) does the same for ENV and LFO 2 / 3:
 *   ENV      each layer's own amp envelope: object at layer +0x258, so the source pointer is layer +0x27c
 *   LFO2/3   the pad's LFO in lfo.c
 * Targets and amounts as FUN_08067018 has them for the LFO (Pitch counts double there).
 */
#include <stdint.h>

#define FN(addr) ((addr) | 1u)
typedef void (*setup_fn)(uint8_t *pad, uint8_t *cmd);
typedef void (*sync_fn)(uint8_t *pad, uint8_t *voice);
typedef void (*attach_fn)(float amount, void *param, void *source, int slot);
#define fw_setup  ((setup_fn)FN(0x08056810))
#define fw_sync   ((sync_fn)FN(0x0805623c))
#define fw_attach ((attach_fn)FN(0x0806fcd4))

#define SRC_ENV      1
#define SRC_LFO2     5            /* lfo.c: LFO 2 and 3, one per pad; the preset format's "lfo2" / "lfo3" */
#define SRC_LFO3     6
void *lfo_source(const uint8_t *pad, int k);
void lfo_route(const uint8_t *pad, unsigned target, unsigned slot, unsigned source);
#define SRC_VELOCITY 0xd
#define PAD_LIST     0x4ec
#define PAD_COUNT    0x54c
#define VOICE_ENV_SOURCE 0x4c            /* envelope object voice +0x28, level at its +0x28, read at source +4 */

struct entry {
    float amount;
    uint16_t target, source;
    uint8_t slot, pad[3];
};

/* target code -> the voice's parameter object, as FUN_0805623c maps them */
static const struct {
    uint16_t target, param;
} targets[] = {
    {2, 0x150}, {4, 0x150}, {9, 0x47c}, {10, 0x4b0}, {11, 0x448}, {0x11, 0x334}, {0x3c, 0x388}, {0x3e, 0x3bc},
    {0x40, 0x3f0}, {0x5c, 0x288}, {0x5d, 0x2bc}, {0x62, 0x184}, {0x8f, 0x1b8}, {0x90, 0x1ec}, {0x91, 0x220},
    {0x92, 0x254}, {200, 0x2f8},
};

void env_mod_setup(uint8_t *pad, uint8_t *cmd)
{
    uint16_t *source = (uint16_t *)(cmd + 0x14), ours = *source;
    lfo_route(pad, *(uint32_t *)(cmd + 0xc) & 0xffff, *(uint32_t *)(cmd + 0x10) & 0xff, ours);
    if (ours != SRC_ENV && ours != SRC_LFO2 && ours != SRC_LFO3) {
        fw_setup(pad, cmd);
        return;
    }
    *source = SRC_VELOCITY;
    fw_setup(pad, cmd);
    *source = ours;
    uint16_t target = (uint16_t)*(uint32_t *)(cmd + 0xc);
    uint8_t slot = (uint8_t)*(uint32_t *)(cmd + 0x10);
    struct entry *e = (struct entry *)(pad + PAD_LIST);
    uint32_t n = *(uint32_t *)(pad + PAD_COUNT);
    for (uint32_t i = 0; i < n && i < 8; i++)
        if (e[i].target == target && e[i].slot == slot && e[i].source == SRC_VELOCITY)
            e[i].source = ours;
}

void env_mod_attach(uint8_t *pad, uint8_t *voice)
{
    fw_sync(pad, voice);
    const struct entry *e = (const struct entry *)(pad + PAD_LIST);
    uint32_t n = *(uint32_t *)(pad + PAD_COUNT);
    for (uint32_t i = 0; i < n && i < 8; i++) {
        void *from;
        if (e[i].source == SRC_ENV)
            from = voice + VOICE_ENV_SOURCE;
        else if (e[i].source == SRC_LFO2 || e[i].source == SRC_LFO3)
            from = lfo_source(pad, e[i].source - SRC_LFO2);
        else
            continue;
        if (!from)
            continue;
        for (unsigned k = 0; k < sizeof targets / sizeof *targets; k++)
            if (targets[k].target == e[i].target) {
                fw_attach(e[i].target == 10 ? e[i].amount * 14.0f : e[i].amount, voice + targets[k].param,
                          from, e[i].slot);
                break;
            }
    }
}

/* ---- Clip and Slicer pads ---- */

#define fw_setup_b ((setup_fn)FN(0x08067018))
#define LAYER_STEP 0x410
#define LAYER_ENV_SOURCE (0x260 + 0x258 + 0x24)  /* first layer's envelope object, read at +4 = its level at +0x28 */
#define PAD_B_NOTHING 0xb70                      /* the source stock attaches for "none" */

static const struct {
    uint16_t target, param;                      /* the first layer's parameter object */
} targets_b[] = {
    {2, 0x2b8}, {4, 0x2b8}, {0x11, 0x484}, {0x3c, 0x514}, {0x3e, 0x548}, {0x40, 0x57c}, {0x5c, 0x2f4}, {0x62, 0x26c},
    {200, 0x448},
};

void env_mod_setup_b(uint8_t *pad, uint8_t *cmd)
{
    uint16_t source = *(uint16_t *)(cmd + 0x14), target = (uint16_t)*(uint32_t *)(cmd + 0xc);
    lfo_route(pad, target, *(uint32_t *)(cmd + 0x10) & 0xffff, source);
    if (source != SRC_ENV && source != SRC_LFO2 && source != SRC_LFO3) {
        fw_setup_b(pad, cmd);
        return;
    }
    int slot = (int)(*(uint32_t *)(cmd + 0x10) & 0xffff);
    float amount = (float)*(int16_t *)(cmd + 0x16) * 0.001f;
    for (unsigned k = 0; k < sizeof targets_b / sizeof *targets_b; k++) {
        if (targets_b[k].target != target)
            continue;
        if (target == 0x62)
            amount += amount;
        for (unsigned layer = 0; layer < 2; layer++) {
            uint8_t *from = source == SRC_ENV ? pad + LAYER_ENV_SOURCE + layer * LAYER_STEP
                                              : (uint8_t *)lfo_source(pad, source - SRC_LFO2);
            fw_attach(from ? amount : 0.0f, pad + targets_b[k].param + layer * LAYER_STEP, from ? from : pad + PAD_B_NOTHING, slot);
        }
        return;
    }
}
