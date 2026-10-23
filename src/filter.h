/* Pad Fidelity + filter: what filter.c (the hooks; bank 1) and filter_dsp.c (the DSP; bank 2, 3.3.y) share. */
#ifndef FILTER_H
#define FILTER_H
#include <stdint.h>

/* The Fidelity list: Normal, HighQ (stock), the machines, the plain crunches. filter_dsp.c checks its tables match. */
#define STOCK_INTERP  2
#define MACHINES      7
#define CRUNCHES      7
#define FIRST_MACHINE STOCK_INTERP                      /* the order asked for (3.1.n): machines before the plain crunches */
#define FIRST_CRUNCH  (FIRST_MACHINE + MACHINES)
#define INTERPS       (FIRST_CRUNCH + CRUNCHES)

#define OBJ_RATE  0x60           /* filter object: the voice's playback rate, for a machine's output stage */
#define S9_OFFSET (0x56800u + 0x7000u)                  /* in master.c's block: the S950 bank, then the hold stash ... */
#define SD_OFFSET (S9_OFFSET + 0x3800u)                 /* ... and SLICE_DIAG's rows (filter.c) */
#define XF_OFFSET (0x56800u + 0x3d100u)                /* the filter's switch crossfade: scratch, 2 x XF_FRAMES floats */
#define XF_FRAMES 512

/*
 * The voice reader. Sample / multisample voices read their sample through FUN_08055f0c, which fetches the source into a
 * scratch buffer and resamples it with one of two kernels chosen by the stock Interp value: FUN_080619d0 (Normal,
 * 4-point cubic) or FUN_08061a64 (HighQ, Hermite). Both take (rate s0, src r0, n_src r1, int pos r2, int *newpos r3,
 * float *frac, float *dst, int n); the reading point is src[pos + frac] and moves by |rate| per output frame.
 * voice_read (filter.c) parks FUN_08055f0c's pad, absolute source position and signed rate here, so the machine grid is
 * anchored on the sample itself, not on each block's scratch buffer.
 * At rate exactly 1.0 the stock code copies without a kernel; the hold after the voice then does the same job.
 */
struct read_park {
    const uint8_t *pad;
    int32_t pos;
    float rate;
};
#define PARK ((volatile struct read_park *)0x2405fff4u)     /* the last 12 bytes of patch RAM */

/* filter_dsp.c, bank 2: call only when b2_live(). mem = master_block() (may be 0). */
struct machine;
unsigned filt_interp(const uint8_t *pad, uint8_t *mem);                 /* the pad's Fidelity */
const struct machine *filt_machine(const uint8_t *pad, uint8_t *mem);  /* its machine, or 0 */
void filt_read(const struct machine *m, uint8_t *mem, float rate, const float *src, int n_src, int pos, int *newpos,
               float *frac, float *dst, int n);                         /* a machine's reader kernel */
void filt_block(uint8_t *obj, void *buf, const uint8_t *pad, uint8_t *mem);   /* the per-voice filter */

#endif
