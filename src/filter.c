/*
 * Pad Fidelity (crunch + machine modes) and the 24 dB filter: the hooks. Original 1010music Blackbox, firmware 3.1.9.
 * What they do is described in filter_dsp.c, which has the DSP and lives in flash bank 2 since 3.3.y (bank 1 was down
 * to ~1.8 KB). Everything here is reached from patched call sites, so it stays in bank 1 and calls into bank 2 only when
 * b2_live(); without the payload the voices get stock's filter and readers, and the list shows "---" for the modes.
 */
#include <stdint.h>
#include "filter.h"

#pragma GCC optimize("Os", "no-tree-loop-distribute-patterns")

#define FN(addr) ((addr) | 1u)

typedef int (*buf_int_fn)(void *buf);
typedef int (*buf_chans_fn)(void *buf, float **left, float **right);
typedef void (*register_fn)(void *table, int param, const char *label, const char *const *names, int count,
                            const char *xml);
typedef void (*stock_filter_fn)(uint8_t *obj, void *buf);

#define fw_buf_silent ((buf_int_fn)FN(0x0804d8f4))
#define fw_buf_frames ((buf_int_fn)FN(0x0804d8e8))
#define fw_register_list ((register_fn)FN(0x0808c0d8))
#define fw_filter     ((stock_filter_fn)FN(0x080762d8))  /* stock's per-voice filter (RBJ biquad): the hooks replaced
                                                            its two calls; the function itself is untouched */

uint8_t *master_block(void);     /* master.c */
int b2_live(void);               /* cpu.c: the matching bank 2 is there, so filter_dsp.c may be called */
int b2_present(void);            /* cpu.c: the same, asked while the lists are registered */

/*
 * S950 Lo (3.1.T) has the list place the S1000 mode had (3.1.u - 3.1.S: an eight-point sinc re-pitch, taken out for
 * its 2.3 KB), so every saved Fidelity value keeps its meaning except a pad left on S1000, which is now S950 Lo.
 */

const char *const interp_names[INTERPS] = {
    (const char *)0x080cd770u, (const char *)0x080cd778u,       /* Normal, HighQ */
    "SP1200", "SP-12", "S950", "MPC60", "SP Raw", "S950 Lo", "SP 45",
    "16k", "12k", "10k", "8k", "6k", "4k", "2k",
};
static const char *const interp_names_none[INTERPS] = {
    (const char *)0x080cd770u, (const char *)0x080cd778u,       /* no bank 2 payload: the modes read "---" */
    "---", "---", "---", "---", "---", "---", "---",
    "---", "---", "---", "---", "---", "---", "---",
};


/* Replaces the Interp list registration call: 2 -> 16 entries, and the label "Interp:" -> "Fidelity:" (the pick of
   names; the xml name "interpqual" stays, so presets are unaffected). */
void interp_register(void *table, int param, const char *label, const char *const *names, int count, const char *xml)
{
    (void)label;
    (void)names;
    (void)count;
    fw_register_list(table, param, "Fidelity:", b2_present() ? interp_names : interp_names_none, INTERPS, xml);
}

/* The pad's machine, from bank 2 (0 = none: stock reads and filters the voice) */
static const struct machine *pad_machine(const uint8_t *pad, uint8_t **mem)
{
    if (!b2_live())
        return 0;
    *mem = master_block();
    return filt_machine(pad, *mem);
}

#ifdef SLICE_DIAG
/*
 * SLICE_DIAG=1 ./build.sh (debug builds only, 2026-10-17): why some retriggers of an SP-12 slicer pad come out clean.
 * One row per clip / slicer trigger, in SDRAM behind the S950 bank (master block + 0x61000; the block's address is
 * backup SRAM 0x38800f70, so the Mac finds it with two peeks - measure/slice_diag.py). A trigger = a segment the
 * reader has not seen, or one that restarted (moved backwards, jumped forwards, or sat idle). Its row counts, until its voice's next
 * trigger: reads through the machine reader / through stock because the pad did not read as a machine / because
 * the rate was not > 0; filter calls on its voice with a machine Fidelity / another one / skipped as silent.
 * A clean-sounding trigger with reads_m and filt_m both counting every block = the code path is not the cause.
 */
struct sd_row {
    uint32_t seq0;               /* audio block when it started */
    uint32_t pad_id;             /* pad +0x18: bank << 16 | row << 8 | col */
    uint8_t voice, seg, interp, flags;      /* voice 0 = pad+0x260, 1 = pad+0x670; flags bit 0 = a real row */
    uint16_t reads_m, reads_stock, reads_rate, filt_m, filt_other, filt_silent, reads_old, last;
    float rate;
};
struct sd_seg {
    const uint8_t *seg;
    int32_t pos;
    uint32_t seq;
};
#define SD_ROWS 48
#define SD_SEGS 8
struct sdiag {
    uint32_t magic, seq, rows, spare;
    uint32_t tot[8];             /* reads_m, reads_stock, reads_rate, filt_b_m, filt_b_other, filt_b_silent, filt_a, new segs */
    struct sd_seg segs[SD_SEGS];
    const uint8_t *cur_seg[2];
    struct sd_row cur[2];
    struct sd_row ring[SD_ROWS];
};
#define SD_MAGIC   0x53444731u   /* "SDG1" */
_Static_assert(0x3800 + sizeof(struct sdiag) <= 0x4000, "and inside its 0x4000");

static struct sdiag *sd(void)
{
    uint8_t *mem = master_block();
    if (!mem)
        return 0;
    struct sdiag *d = (struct sdiag *)(mem + SD_OFFSET);
    if (d->magic != SD_MAGIC) {
        uint32_t *w = (uint32_t *)d;
        for (unsigned i = 0; i < sizeof *d / 4; i++)
            w[i] = 0;
        d->magic = SD_MAGIC;
    }
    return d;
}

static int sd_voice(const uint8_t *pad, const uint8_t *filter)
{
    int off = (int)(filter - pad);
    return off == 0x260 + 0x14c ? 0 : off == 0x670 + 0x14c ? 1 : 2;
}

static unsigned pad_interp(const uint8_t *pad)
{
    return b2_live() ? filt_interp(pad, master_block()) : 0;
}

static inline uint16_t inc16(uint16_t v)
{
    return v == 0xffff ? v : (uint16_t)(v + 1);
}

/* master.c's master_on, once per audio block */
void sdiag_block(void)
{
    struct sdiag *d = sd();
    if (d)
        d->seq++;
}

/* clip_read: path 0 = machine reader, 1 = stock (pad not a machine), 2 = stock (rate not > 0) */
static void sd_read(const uint8_t *pad, const uint8_t *filter, const float *frac, int32_t pos, float rate, int path)
{
    struct sdiag *d = sd();
    if (!d)
        return;
    d->tot[path]++;
    const uint8_t *seg = (const uint8_t *)frac - 0x1c;
    int v = sd_voice(pad, filter);
    struct sd_seg *e = 0, *oldest = &d->segs[0];
    for (int i = 0; i < SD_SEGS; i++) {
        if (d->segs[i].seg == seg)
            e = &d->segs[i];
        if (d->segs[i].seq < oldest->seq)
            oldest = &d->segs[i];
    }
    /* restarted: new, moved backwards, jumped forwards further than a block reads, or idle for a few blocks */
    int fresh = !e || pos < e->pos || pos > e->pos + 4096 || d->seq - e->seq > 2;
    if (!e) {
        e = oldest;
        e->seg = seg;
        d->tot[7]++;
    }
    e->pos = pos;
    e->seq = d->seq;
    if (fresh && v < 2) {
        if (d->cur[v].flags & 1) {                          /* the voice's previous trigger, now complete */
            d->ring[d->rows % SD_ROWS] = d->cur[v];
            d->rows++;
        }
        struct sd_row *r = &d->cur[v];
        r->seq0 = d->seq;
        r->pad_id = *(const uint32_t *)(pad + 0x18);
        r->voice = (uint8_t)v;
        r->seg = (uint8_t)((seg - pad - 0x30) / 0x70);
        r->interp = (uint8_t)pad_interp(pad);
        r->flags = 1;
        r->reads_m = r->reads_stock = r->reads_rate = r->filt_m = r->filt_other = r->filt_silent = r->reads_old = 0;
        r->rate = rate;
        d->cur_seg[v] = seg;
    }
    if (v < 2) {
        struct sd_row *r = &d->cur[v];
        if (seg != d->cur_seg[v])
            r->reads_old = inc16(r->reads_old);
        else if (path == 0)
            r->reads_m = inc16(r->reads_m);
        else if (path == 1)
            r->reads_stock = inc16(r->reads_stock);
        else
            r->reads_rate = inc16(r->reads_rate);
        r->last = (uint16_t)(d->seq - r->seq0);
    }
}

/* filter_process: what = 0 machine Fidelity, 1 another Fidelity, 2 skipped (buffer silent) */
static void sd_filter(const uint8_t *obj, const uint8_t *pad, int what)
{
    struct sdiag *d = sd();
    if (!d)
        return;
    int v = sd_voice(pad, obj);
    if (v == 2) {
        d->tot[6]++;
        return;
    }
    d->tot[3 + what]++;
    struct sd_row *r = &d->cur[v];
    if (what == 0)
        r->filt_m = inc16(r->filt_m);
    else if (what == 1)
        r->filt_other = inc16(r->filt_other);
    else
        r->filt_silent = inc16(r->filt_silent);
}
#endif


/* For od.c: this pad is in a machine mode, so its Saturation knob is the machine's input drive (applied here). */
int pad_machine_mode(const uint8_t *pad)
{
    uint8_t *mem;
    return pad_machine(pad, &mem) != 0;
}

/* Replaces the per-voice filter call. pad = the pad object the voice belongs to (thunks in filter_thunk.S). */
#ifdef CPU_PROF
#define filter_process filter_process_body /* prof.c times these under the hooked names */
#define voice_read voice_read_body
#define clip_read clip_read_body
#endif
void filter_process(uint8_t *obj, void *buf, const uint8_t *pad)
{
    if (!b2_live()) {
        fw_filter(obj, buf);     /* filter_dsp.c is in bank 2: stock's filter without it */
        return;
    }
    uint8_t *mem = master_block();
#ifdef SLICE_DIAG
    sd_filter(obj, pad, fw_buf_silent(buf) ? 2 : filt_machine(pad, mem) ? 0 : 1);
#endif
    filt_block(obj, buf, pad, mem);
}

typedef int (*voice_read_fn)(float frac, float rate, const uint8_t *pad, void *src, int pos, int a6, int frames,
                             int offset, void *scratch, void *out);
#define fw_voice_read ((voice_read_fn)FN(0x08055f0c))

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
    uint8_t *mem;
    if (rate == 1.0f && pad_machine(pad, &mem))
        rate = 1.00000012f;
    return fw_voice_read(frac, rate, pad, src, pos, a6, frames, offset, scratch, out);
}

typedef void (*kernel_fn)(float rate, const float *src, int n_src, int pos, int *newpos, float *frac, float *dst,
                          int n);
#define fw_kernel_normal ((kernel_fn)FN(0x080619d0))
#define fw_kernel_hq     ((kernel_fn)FN(0x08061a64))

/* Replace the kernel calls in FUN_08055f0c: Normal @0x0805619a / 0x080561be / 0x080561d4, HighQ @0x08056010 /
   0x08056098 / 0x080560bc. */
void read_normal(float rate, const float *src, int n_src, int pos, int *newpos, float *frac, float *dst, int n)
{
    uint8_t *mem;
    const struct machine *m = pad_machine(PARK->pad, &mem);
    if (m)
        filt_read(m, mem, rate, src, n_src, pos, newpos, frac, dst, n);
    else
        fw_kernel_normal(rate, src, n_src, pos, newpos, frac, dst, n);
}

void read_hq(float rate, const float *src, int n_src, int pos, int *newpos, float *frac, float *dst, int n)
{
    uint8_t *mem;
    const struct machine *m = pad_machine(PARK->pad, &mem);
    if (m)
        filt_read(m, mem, rate, src, n_src, pos, newpos, frac, dst, n);
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

int stretch_read(float rate, uint8_t *pad, int32_t pos, int n, int *used, float *frac, void *out, void **result);

/* filter = the reading voice's filter object, put in the register stock leaves unused (clip_read_b, filter_thunk.S).
   A clip pad on a Stretch model (stretch.c) reads through it first. */
static int read_any(float rate, uint8_t *pad, uint8_t *filter, int32_t pos, int32_t pos_hi, int n, int *used, float *frac,
                    void *scratch, void *out, void **result)
{
    if (stretch_read(rate, pad, pos, n, used, frac, out, result) > 0) {
        *(float *)(filter + OBJ_RATE) = rate;              /* where the output stage looks for it, as below */
        return 1;
    }
    uint8_t *mem;
    const struct machine *m = pad_machine(pad, &mem);
#ifdef SLICE_DIAG
    sd_read(pad, filter, frac, pos, rate, !m ? 1 : !(rate > 0.0f) ? 2 : 0);
#endif
    if (!m || !(rate > 0.0f))
        return fw_clip_read(rate, pad, filter, pos, pos_hi, n, used, frac, scratch, out, result);
    void *src = *(void **)(pad + CLIP_SOURCE);
    if (fw_src_len(src) + 0xff < pos)
        return 0;
    *(float *)(filter + OBJ_RATE) = rate;
    int n_src = (int)((float)n * rate) + 8, cap = fw_buf_frames(scratch);
    if (n_src > cap)
        n_src = cap;
    int32_t start = pos - CLIP_BACK;
    int lead = start < 0 ? -start : 0;                      /* before the sample's first frame: silence */
    if (lead > n_src)
        lead = n_src;
    PARK->pad = pad;
    PARK->pos = start + 4;                                  /* machine_read: scratch[0] = source[PARK->pos - 4] */
    PARK->rate = rate;
    int idx = 4;
    if (!fw_src_stereo(src)) {
        float *s = fw_buf_mono(scratch);
        for (int i = 0; i < lead; i++)
            s[i] = 0.0f;
        if (n_src > lead)
            fw_fetch(src, s + lead, n_src - lead, start + lead, 0);
        filt_read(m, mem, rate, s, n_src, 4, &idx, frac, fw_buf_mono(out), n);
    } else {
        float *sl = 0, *sr = 0, *ol = 0, *orr = 0;
        fw_buf_pair(scratch, &sl, &sr);
        for (int i = 0; i < lead; i++)
            sl[i] = sr[i] = 0.0f;
        if (n_src > lead)
            fw_fetch2(src, sl + lead, sr + lead, n_src - lead, start + lead);
        fw_buf_pair(out, &ol, &orr);
        float f = *frac;
        filt_read(m, mem, rate, sl, n_src, 4, &idx, &f, ol, n);
        filt_read(m, mem, rate, sr, n_src, 4, &idx, frac, orr, n);
    }
    *used = idx - 4;
    *result = out;
    return 1;
}

int sel_end(const uint8_t *pad);   /* clipsel.c: where this pad's source ends (its selection's end), or INT32_MAX */

/*
 * The clip reader (see read_any). A clip with a selection must not sound past its end, which stock only ensures
 * at the file's end: a slice that runs on (slower tempo, pitch up) would play what follows the selection. As stock
 * does past the file: nothing at all once the position is 0xff past the end, else the frames from the end on silenced.
 */
int clip_read(float rate, uint8_t *pad, uint8_t *filter, int32_t pos, int32_t pos_hi, int n, int *used, float *frac,
              void *scratch, void *out, void **result)
{
    float f0 = *frac;
    int end = sel_end(pad);
    if (end != 0x7fffffff && pos > end + 0xff)
        return 0;
    int r = read_any(rate, pad, filter, pos, pos_hi, n, used, frac, scratch, out, result);
    if (r != 1 || end == 0x7fffffff || !(rate > 0.0f))
        return r;
    float k = ((float)(end - pos) - f0) / rate;          /* output frame k reads source pos + f0 + k x rate */
    int k0 = k <= 0.0f ? 0 : (int)k + ((float)(int)k < k);
    if (k0 >= n)
        return r;
    float *l = 0, *rr = 0;
    if (fw_src_stereo(*(void **)(pad + CLIP_SOURCE)))
        fw_buf_pair(*result, &l, &rr);
    else
        l = fw_buf_mono(*result);
    for (int i = k0; i < n; i++) {
        l[i] = 0.0f;
        if (rr)
            rr[i] = 0.0f;
    }
    return r;
}
