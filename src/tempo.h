/* Clip tempo detection (tempo_dsp.c, bank 2; also built for the Mac): the job clipsel.c / stretch.c run a step a block. */
#ifndef TEMPO_H
#define TEMPO_H
#include <stdint.h>

#define TEMPO_SECS  30.0f        /* the first 30 s of the file at most */
#define TEMPO_ENV   5632         /* envelope frames: 30 s at 48 kHz / 256 */
#define TEMPO_READ  2048         /* frames read per block */
#define TEMPO_CANDS 2            /* tempos scored per block */

enum { TEMPO_IDLE, TEMPO_READ_AUDIO, TEMPO_WHITEN, TEMPO_SWEEP, TEMPO_RELATIVES, TEMPO_WHOLE, TEMPO_REFINE,
       TEMPO_FINISH, TEMPO_DONE, TEMPO_FAILED };

struct tempo_job {
    uint32_t state;
    int32_t pad;                 /* app pad index 0..15 */
    void *obj;                   /* the sample */
    int32_t len, end, pos;       /* frames: the file, how far to read, read so far */
    uint32_t frate;
    int stereo;
    /* n frames from pos into l / r (r 0 = mono); returns 0 when that part is not loaded (nothing written, retry) */
    int (*fetch)(struct tempo_job *j, float *l, float *r, int n, int32_t pos);
    float fps, chunk_prev, rms_prev, total;
    int n_env, n_top, idx, loop;
    float cand, refine_hi, best_bpm, best_score;
    float top_bpm[8], top_score[8];
    float bpm, phase;            /* the answer: BPM, and beat one in frames from the file's start */
    uint32_t req, served;        /* clipsel.c: the screen's request number, and the one this job answers */
    int32_t req_pad;             /* the pad the screen asked about */
    uint32_t misses;
    float env[TEMPO_ENV];
    float flux[TEMPO_ENV];
};

void tempo_start(struct tempo_job *j, int pad, void *obj, int32_t len, uint32_t frate, int stereo);
int tempo_step(struct tempo_job *j, float *scratch);   /* scratch: 2 x TEMPO_READ floats */
int tempo_fw_fetch(struct tempo_job *j, float *l, float *r, int n, int32_t pos);   /* firmware only */

#endif
