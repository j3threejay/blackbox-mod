/*
 * CPU_PROF=1 ./build.sh (debug builds only, 3.3.l): where an audio block's time goes, and what the WORST blocks
 * were doing. Testers see peaks 1.6-2.4x the average (one tester: 52/124, 54/88, 39/77, 47/84 %), and another's load
 * jumps while they turn knobs; the emulator cannot see either, so this records it on the unit.
 *
 * Every block (one wake of the audio task, cpu.c) is split into timed sections, DWT cycles:
 *   ctl     stock's control tick (FUN_08053164, called from duck_block)
 *   ours    our control-rate work in duck_block: the ducker, lfo_tick, insert_tick
 *   master  comp_process: master FX + compressor + clipper on Out 1
 *   fx1     munchi_process: the delay send, every Type
 *   fx2     fx2_core: the reverb send, Plate or Room
 *   filt    filter_process, all voices (with each voice's crunch / hold)
 *   read    voice_read + clip_read, all voices (stock's reader for Normal / HighQ, ours for the machines)
 * and the rest of the block (stock's voices outside those, the sequencer, messages from the app) is busy - sum.
 * Counted per block: voices (filter calls), reads, note starts (pads that started a voice, from the ducker's bits).
 *
 * Kept, in SDRAM where SLICE_DIAG would be (the two builds exclude each other): 24 load bins of 10 % (since boot),
 * 64-bit totals of every section, and the 8 WORST blocks since boot with their breakdown. measure/cpu_prof.py reads
 * it over the USB peek; two reads either side of a session give that session's totals. While it reads, it pokes
 * `freeze` (the only write it makes, inside this block) so the record holds still, then clears it.
 * The timing itself costs a few hundred cycles a block (each section looks up the block through master_block()).
 */
#include <stdint.h>

#pragma GCC optimize("Os", "no-tree-loop-distribute-patterns")

#ifdef CPU_PROF
#ifdef SLICE_DIAG
#error "CPU_PROF and SLICE_DIAG use the same SDRAM block: build one or the other"
#endif

#define DWT_CYCCNT (*(volatile uint32_t *)0xe0001004u)
uint8_t *master_block(void);

enum { S_CTL, S_OURS, S_MASTER, S_FX1, S_FX2, S_FILT, S_READ, SECTIONS };
struct pblk {
    uint32_t busy;               /* cycles, wake to wait */
    uint16_t load;               /* per mille of the nominal block, as the TOOLS meter */
    uint8_t voices, reads, starts, pad[3];
    uint32_t t[SECTIONS];
};
#define WORST 8
#define BINS 24
struct prof {
    uint32_t magic, blocks, nom;
    uint32_t hist[BINS];
    uint64_t tot_busy, tot[SECTIONS], tot_voices, tot_starts;
    struct pblk cur, worst[WORST];
    uint32_t freeze;             /* PROF_FROZEN: measure/cpu_prof.py holds the record still while it reads it */
};
#define PROF_FROZEN 0x465a5221u  /* "!RZF" */
#define PROF_OFFSET (0x56800u + 0x7000u + 0x3800u)
#define PROF_MAGIC  0x50524631u   /* "PRF1" */
_Static_assert(0x3800 + sizeof(struct prof) <= 0x4000, "inside the S950 bank's 0x4000");

static struct prof *prof(void)
{
    uint8_t *mem = master_block();
    if (!mem)
        return 0;
    struct prof *p = (struct prof *)(mem + PROF_OFFSET);
    if (p->magic != PROF_MAGIC) {
        uint32_t *w = (uint32_t *)p;
        for (unsigned i = 0; i < sizeof *p / 4; i++)
            w[i] = 0;
        p->magic = PROF_MAGIC;
    }
    return p;
}

static inline uint8_t sat8(unsigned v)
{
    return (uint8_t)(v > 255 ? 255 : v);
}

/* cpu.c, cpu_wait: the task woke for a block */
void prof_block_start(void)
{
    struct prof *p = prof();
    if (!p)
        return;
    uint32_t *w = (uint32_t *)&p->cur;
    for (unsigned i = 0; i < sizeof p->cur / 4; i++)
        w[i] = 0;
}

/* cpu.c, cpu_wait: the block just ended. nom = cpu.c's nominal block in cycles (0 until known). */
void prof_block_end(uint32_t busy, uint32_t nom)
{
    struct prof *p = prof();
    if (!p || !nom || p->freeze == PROF_FROZEN)
        return;
    struct pblk *c = &p->cur;
    uint32_t load = busy / (nom / 1000u + 1u);
    c->busy = busy;
    c->load = (uint16_t)(load > 65535u ? 65535u : load);
    p->nom = nom;
    p->blocks++;
    unsigned bin = load / 100u;
    p->hist[bin < BINS ? bin : BINS - 1]++;
    p->tot_busy += busy;
    for (int s = 0; s < SECTIONS; s++)
        p->tot[s] += c->t[s];
    p->tot_voices += c->voices;
    p->tot_starts += c->starts;
    int lo = 0;                                     /* replace the lightest of the worst, if this one is heavier */
    for (int i = 1; i < WORST; i++)
        if (p->worst[i].load < p->worst[lo].load)
            lo = i;
    if (c->load > p->worst[lo].load)
        p->worst[lo] = *c;
}

static void add(int s, uint32_t t0)
{
    uint32_t dt = DWT_CYCCNT - t0;
    struct prof *p = prof();
    if (p)
        p->cur.t[s] += dt;
}

/* duck.c: the two halves of its control tick */
void prof_ctl(uint32_t ours, uint32_t stock, unsigned starts)
{
    struct prof *p = prof();
    if (!p)
        return;
    p->cur.t[S_OURS] += ours;
    p->cur.t[S_CTL] += stock;
    p->cur.starts = sat8(p->cur.starts + starts);
}

/* ---- the timed wrappers: each takes the hooked name; the real code is renamed *_body under CPU_PROF ---- */

int comp_process_body(int *obj, void *bufs);
int comp_process(int *obj, void *bufs)
{
    uint32_t t = DWT_CYCCNT;
    int r = comp_process_body(obj, bufs);
    add(S_MASTER, t);
    return r;
}

int munchi_process_body(uint8_t *obj, uint32_t *bufs);
int munchi_process(uint8_t *obj, uint32_t *bufs)
{
    uint32_t t = DWT_CYCCNT;
    int r = munchi_process_body(obj, bufs);
    add(S_FX1, t);
    return r;
}

void fx2_core_body(float *state, const float *in, float *outl, float *outr, int n);
void fx2_core(float *state, const float *in, float *outl, float *outr, int n)
{
    uint32_t t = DWT_CYCCNT;
    fx2_core_body(state, in, outl, outr, n);
    add(S_FX2, t);
}

void filter_process_body(uint8_t *obj, void *buf, const uint8_t *pad);
void filter_process(uint8_t *obj, void *buf, const uint8_t *pad)
{
    uint32_t t = DWT_CYCCNT;
    filter_process_body(obj, buf, pad);
    add(S_FILT, t);
    struct prof *p = prof();
    if (p)
        p->cur.voices = sat8(p->cur.voices + 1u);
}

int voice_read_body(float frac, float rate, const uint8_t *pad, void *src, int pos, int a6, int frames, int offset,
                    void *scratch, void *out);
int voice_read(float frac, float rate, const uint8_t *pad, void *src, int pos, int a6, int frames, int offset,
               void *scratch, void *out)
{
    uint32_t t = DWT_CYCCNT;
    int r = voice_read_body(frac, rate, pad, src, pos, a6, frames, offset, scratch, out);
    add(S_READ, t);
    struct prof *p = prof();
    if (p)
        p->cur.reads = sat8(p->cur.reads + 1u);
    return r;
}

int clip_read_body(float rate, uint8_t *pad, uint8_t *filter, int32_t pos, int32_t pos_hi, int n, int *used,
                   float *frac, void *scratch, void *out, void **result);
int clip_read(float rate, uint8_t *pad, uint8_t *filter, int32_t pos, int32_t pos_hi, int n, int *used, float *frac,
              void *scratch, void *out, void **result)
{
    uint32_t t = DWT_CYCCNT;
    int r = clip_read_body(rate, pad, filter, pos, pos_hi, n, used, frac, scratch, out, result);
    add(S_READ, t);
    struct prof *p = prof();
    if (p)
        p->cur.reads = sat8(p->cur.reads + 1u);
    return r;
}
#endif
