/*
 * Clip time-stretch models: what stretch.c (firmware glue, bank 1) and stretch_dsp.c (the DSP, bank 2; also built
 * for the Mac) share.
 *
 * Stock's clip stretch is beat slicing (NOTES, TIME STRETCH): each slice of the clip starts on the tempo grid at its
 * own source position and plays at the pad's pitch until the next one takes over. A model changes only what happens
 * INSIDE one slice: the slice's source span is laid over its span on the grid, so it ends where the next slice starts
 * in the source as well as in time. Every slice still starts where stock starts it, so sync is stock's.
 *
 * One struct str_seg per live stock segment. Fresh (magic != STR_MAGIC or a new slice start) = reset.
 */
#ifndef STRETCH_H
#define STRETCH_H
#include <stdint.h>
#include "tempo.h"

enum { STR_STOCK, STR_SMOOTH, STR_KEYFRAME, STR_CYCLIC, STR_MODELS };

#define STR_MAGIC 0x53545232u    /* "STR1": bump with the layout */
#define STR_KF_RING 512          /* keyframes kept per set (power of two) */
#define STR_SCRATCH 4096         /* the fetch area: L in the first half, R in the second */
#define STR_SCRATCH_ALL (STR_SCRATCH + 512 + 1024)   /* floats the caller passes: + Smooth's two search windows */

/* Where the source comes from. Firmware: stock's sample object and its fetch; Mac: two arrays. */
struct str_src {
    void *obj;
    int32_t lo, len;                                 /* frames: the part that sounds (a clip's selection) */
    int stereo;
    /* n frames from pos into l / r (r may be 0 for mono); anything outside lo..len-1 reads as 0 */
    void (*fetch)(const struct str_src *s, float *l, float *r, int n, int32_t pos);
};

struct str_grain {                                   /* a read head: position = i + f */
    int32_t i;
    float f;
};

struct str_kfset {                                   /* keyframes in a ring: absolute position (24.8) and value */
    uint32_t pos[STR_KF_RING];
    float val[STR_KF_RING];
};

struct str_kfrd {                                    /* reading one set: window = keyframes m, m + 1 */
    uint32_t m;
    float u, len, inv, v0, dv;
};

struct str_kfph {                                    /* a keyframe playhead */
    int32_t i;
    float f;
    struct str_kfrd l, r;
};

struct str_seg {
    uint32_t magic;
    int32_t start;                                   /* the slice's first source frame */
    float span;                                      /* its length in the source */
    uint32_t t;                                      /* output frames since the slice started */
    uint8_t model, stereo, splicing, fresh;
    /* grain engine (Smooth, Cyclic) */
    struct str_grain cur, old;
    int32_t age;                                     /* output frames since cur started */
    /* keyframe engine */
    struct {
        uint32_t m_l, m_r;                           /* keyframes written so far, per set */
        int32_t an;                                  /* next source frame to analyse */
        float vprev[2], dprev[2];
        int sprev[2];
        int32_t last_n[2];
        uint32_t last[2];
        struct str_kfph ph[2];
        struct str_kfrd ref;
        int32_t ref_i;
        float ref_f, w, winc;
        uint8_t cur;
    } kf;
    struct str_kfset set[2];                         /* L, R (mono: only L) */
};

/* The firmware's SDRAM area (master.c: STR_OFFSET in its block): a slot per live model segment. */
#define STR_PTR_OFFSET (0x56800u + 0x3e100u)   /* in master.c's block: the area's address */
#define STR_SLOTS 32
#define STR_STALE 256            /* reads (of any clip segment) without a visit before a slot is free again */
#define STR_BANK_MAGIC 0x53544235u   /* "STB5" */
struct str_own {
    const uint8_t *seg;          /* the stock segment it follows */
    uint32_t seq;                /* the read it was last visited on */
    int32_t next, start, slice;  /* where stock will read next; the slice's first frame and index */
    uint8_t stock, model, spare[2];   /* stock: 1 = joined mid-way, or the model changed: stock plays the rest */
};
struct str_clipinfo {            /* clipsel.c: what the Waveform screen's knobs need about a pad's clip */
    uint8_t *eng;                /* the pad's engine object (setup writes it; tempo detection reads its sample) */
    uint32_t frate;              /* the file's rate (setup writes it) */
    int32_t s, e, beats;         /* the selection as the knobs last set it (e 0 = file end; beats 0 = Auto) */
    uint8_t have, fail, spare[2]; /* have: 1 = newer than the screen's store copy; fail: the last detection gave up (1..3) */
};
struct str_audition {             /* clipsel.c: a Clip pad playing while stopped (one block at a time) */
    uint8_t *pad;
    int64_t quant;
    uint8_t sync, on, spare[2];
};
struct str_bank {
    uint32_t magic, seq, scan;
    uint8_t model[16];           /* each pad's Stretch, as stretch_tick last read it */
    struct str_clipinfo clip[16];
    struct str_audition aud;
    float tempo;                 /* clipsel.c: the engine clock's tempo, last Clip block */
    struct str_own own[STR_SLOTS];
    float scratch[STR_SCRATCH_ALL];
    struct str_seg st[STR_SLOTS];
    struct tempo_job tj;         /* clipsel.c: one tempo detection at a time, a step per block */
};

/* bank 2: one clip segment read through a model; -1 = stock reads it */
int str_clip(uint8_t *mem, uint8_t *pad, int model, float rate, int32_t pos, int n, int *used, float *frac, void *out,
             void **result);

/*
 * Render n output frames of a segment. start = the slice's first source frame (a change resets the state), span =
 * its length in the source;
 * rate = the pad's pitch (source frames per output frame, stock's); ref_rate = the slice's source length / its length
 * on the grid (source frames per output frame the slice must cover). out_r may be 0 for a mono source.
 * Returns the source position the play head is at (for the caller's bookkeeping).
 */
int32_t str_render(struct str_seg *g, int model, const struct str_src *src, int32_t start, float span, float rate,
                   float ref_rate, float *out_l, float *out_r, int n, float *scratch);

#endif
