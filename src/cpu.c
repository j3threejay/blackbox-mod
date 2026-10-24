/*
 * CPU meter for the audio engine. Original 1010music Blackbox, firmware 3.1.9.
 *
 * The audio task (FUN_08041470) waits on a queue for the SAI DMA half / full interrupts, then renders 256 frames
 * (5.33 ms at 48 kHz) and waits again. This wraps that wait: busy = cycles from waking to waiting again,
 * period = cycles between wake-ups, both from the Cortex-M7 DWT cycle counter. Once a second the average and the
 * worst block of that second are kept.
 *
 * Where it shows (3.1.I): the Tools screen's bottom bar has three labels (FUN_080c5450 builds them): the version, an
 * EMPTY middle one, and the card's free space, which FUN_080c5180 fills in whenever Tools refreshes. That refresh now
 * also writes "avg/peak%" into the middle label ("--%" if the cycle counter never moves). So the figure is as fresh
 * as the last time Tools drew itself. (Earlier builds appended it to the version text from the audio task; that never
 * showed on the unit, and the same text was the header of the master knob pages, where it wrapped.)
 *
 * cpu_name still supplies the global cell's name: the version, or a master page's title (master.c).
 */
#include <stdint.h>
#include "b2.h"

#define FN(addr) ((addr) | 1u)

typedef int (*receive_fn)(void *queue, void *item, uint32_t ticks, int peek);
typedef void (*label_fn)(uint8_t *label, const char *s);

#define fw_receive  ((receive_fn)FN(0x08088756))     /* FreeRTOS queue receive */
#define fw_label_set ((label_fn)FN(0x080a3dec))      /* label: set its text, then redraw */

/*
 * Our version text, in the cave. It must NOT be patched over stock's "3.1.9" at 0x080cf290: the compiler pooled
 * that string's last character as the standalone "9", and three tables point at it - the naming keyboard's top
 * row (0x080f0ba8: 5 6 7 8 9 0 q w e r t y) and two numeric value lists. Every build from the first one to 3.2.b
 * patched that byte, so the 9 key typed the build letter instead (reported by a user on the public 3.1.n, which
 * typed "n"; 3.2.b typed "b"). Instead the four places that DISPLAY the version are repointed here (patches/cave.py).
 */
#if defined(PUBLIC_BUILD) && defined(USB_DIAG)
const char fw_version[] = "JOE USB";              /* the USB diagnostic build for testers (usbdev.c, USB_DIAG) */
#elif defined(USB_DIAG)
const char fw_version[] = "3.3.i";                /* 3.3.h + USB_DIAG, for proving the readout on the test unit */
#elif defined(PUBLIC_BUILD) && defined(FAULT_SHOW)
const char fw_version[] = "JOE DIAG";             /* the diagnostic build for testers (fault.c, FAULT_SHOW) */
#elif defined(PUBLIC_BUILD)
#include "release.h"
const char fw_version[] = RELEASE_NAME;
#elif defined(CPU_PROF)
const char fw_version[] = "3.4.a2 P";             /* 3.4.a2 + CPU_PROF: per-block section timings for the peak hunt (prof.c) */
#elif defined(SLICE_DIAG)
const char fw_version[] = "3.3.j";                /* rc4 + SLICE_DIAG: per-trigger rows for the slicer crunch bug (filter.c) */
#elif defined(FAULT_SHOW)
const char fw_version[] = "3.3.g";                /* 3.3.e + FAULT_SHOW (3.3.f drew nothing: ARGB1555), for proving the diagnostic on the test unit */
#else
const char fw_version[] = "3.4.a2";               /* 3.4.a + TOOLS tabs fix (Groove to the Clock tab) + insert header cut: beta 2 candidate */
#endif
/* 1 = a public build: named, and without the raw USB peek / poke (test_usbdev.py and test_cpu.py ask). */
#ifdef PUBLIC_BUILD
__attribute__((used)) const uint8_t release_build = 1;
#else
__attribute__((used)) const uint8_t release_build = 0;
#endif
#define VERSION     (fw_version)
#define LABEL_SIZE  0xa0                             /* the bar's labels sit one after the other */

#define DEMCR      (*(volatile uint32_t *)0xe000edfcu)
#define DWT_CTRL   (*(volatile uint32_t *)0xe0001000u)
#define DWT_CYCCNT (*(volatile uint32_t *)0xe0001004u)
#define DWT_LAR    (*(volatile uint32_t *)0xe0001fb0u)

#define BLOCKS_PER_REPORT 188    /* ~1 s of 5.33 ms blocks */

/*
 * THE READING USED TO INVERT (3.2.c and earlier). Load was busy / period, both measured wake to wake, so when
 * blocks arrived late the period stretched and the ratio FELL: a dropout with four Flanger inserts + clipper +
 * Glue + Prism read 58/78 %, while VHS at 85/99 % was clean. A low number during a dropout was the symptom, not
 * headroom. The denominator is now the NOMINAL block - the shortest period seen in the previous report window -
 * so the figure is busy time against the time the engine actually had, and over 100 % means the render did not
 * fit. Healthy readings are unchanged (nominal == actual when nothing is late), so earlier photos still
 * compare.
 *
 * THE FIGURES SPAN THE TIME BETWEEN DRAWS, not a fixed second. The bar is only written when Tools is ENTERED
 * (FUN_080c5180 runs on msg 0x66 for cell 0x40 and on msg 0xd4), so a per-second average was a stale one-second
 * sample of whenever that happened - useless for "leave Tools, play something, come back", which is the only way
 * to watch the engine under load. Average, peak and the late count now accumulate until the bar is drawn and are
 * cleared by the draw, so one look summarises everything since the last look. The displayed pair is also held, so
 * an immediate second look shows the same figures rather than going blank. Past about five minutes without a look
 * the accumulator halves itself rather than wrapping, which turns the average into a slow fade of the oldest half.
 *
 * Beside it, "+n" counts blocks whose period ran past 1.5x nominal: a boundary the task did not meet. Reading the
 * pair during a dropout says which kind it is:
 *   peak at or over 100 %      -> out of CPU, the render does not fit in a block.
 *   "+n" with peak under 100 % -> something stalled the engine (SDRAM contention, a higher-priority task).
 *   +0 and peak under 100 %    -> NOT the audio task at all. Look at sample streaming starvation instead.
 * The count accumulates until the bar is drawn and is cleared by the draw, so a dropout that happened with another
 * screen up still shows on arriving at Tools (a boot or a preset load will show one too).
 */
struct cpu_state {
    uint32_t magic;
    uint32_t woke;               /* cycle count when the task last woke */
    uint32_t sum;                /* per-mille loads this report */
    uint32_t nom;                /* nominal block, cycles: the smallest report mean seen since boot */
    uint32_t win_start;          /* cycle count when this report began */
    uint16_t n, peak;            /* measured blocks and the worst one SINCE THE BAR WAS LAST DRAWN */
    uint16_t wakes;              /* all wake-ups, measured or not; only the dead-clock check reads it */
    uint16_t win_n;              /* blocks this nominal-estimate window */
    uint16_t avg_shown, peak_shown;   /* what the bar last showed, held so a second look is not blank */
    uint8_t armed, status;
    uint8_t late;                /* late blocks since the bar was last drawn, clamped at 99 */
    uint8_t b2chk;               /* bank 2: B2_PAIR bits 0 not checked, 1 matches this image, 2 does not;
                                    B2_LOOKED and the B2_FILE verdict belong to the card loader (b2load.c) */
};
#define M ((volatile struct cpu_state *)0x2405ffd0u)
#define MAGIC 0x43505534u        /* "CPU4": bumped with the layout */
#define STATUS_NONE    0         /* nothing measured yet */
#define STATUS_OK      1
#define STATUS_NO_CLOCK 2        /* a second of wake-ups and the cycle counter never moved */
#define PERIOD_FLOOR 100000u     /* a plausible block is far longer; two interrupts queued at once are not one */


static void start(void)
{
    DEMCR |= 1u << 24;           /* TRCENA */
    DWT_LAR = 0xc5acce55u;       /* unlock (Cortex-M7) */
    DWT_CTRL |= 1u;              /* CYCCNTENA */
    M->armed = 0;
    M->status = STATUS_NONE;
    M->sum = 0;
    M->nom = 0;
    M->win_start = DWT_CYCCNT;   /* so the first report's mean is a real elapsed time, not the raw counter */
    M->late = 0;
    M->b2chk = 0;
    M->n = M->peak = M->wakes = M->win_n = 0;
    M->magic = MAGIC;
}

static char *put_uint(char *p, unsigned v)
{
    char tmp[4];
    int n = 0;
    do {
        tmp[n++] = (char)('0' + v % 10);
        v /= 10;
    } while (v && n < 4);
    while (n)
        *p++ = tmp[--n];
    return p;
}

static uint8_t b2_checked(void);

/*
 * "34/71%", "34/71%+3", "--%", or nothing before the first second - and a leading "!" while flash bank 2 is NOT the
 * payload this image was built with, so Prism, Confetti and the per-pad insert are switched off. It goes here
 * because this label is redrawn on every entry to Tools; the version text beside it is set once when the screen is
 * built (3.2.y read plain "3.2.y" with the loader's "+" sitting unseen in cpu_name). Writes at most 13 bytes.
 */
#ifdef USB_DIAG
char *usbdev_diag_text(char *p);             /* usbdev.c: "U3r2c1 +0.12%" */
#endif

static void compose(char *buf)
{
    char *p = buf;
#ifdef USB_DIAG
    if (M->magic == MAGIC && b2_checked() != B2_PAIRED)
        *p++ = '!';              /* still the bank 2 mark, in front */
    usbdev_diag_text(p);         /* the USB diagnostic build shows this on TOOLS instead of the load */
    return;
#endif
    if (M->magic == MAGIC && b2_checked() != B2_PAIRED)
        *p++ = '!';
    if (M->magic == MAGIC && M->status == STATUS_OK) {
        p = put_uint(p, (M->avg_shown + 5u) / 10u);
        *p++ = '/';
        p = put_uint(p, (M->peak_shown + 5u) / 10u);
        *p++ = '%';
        if (M->late) {
            *p++ = '+';
            p = put_uint(p, M->late);
        }
    } else if (M->magic == MAGIC && M->status == STATUS_NO_CLOCK) {
        *p++ = '-';
        *p++ = '-';
        *p++ = '%';
    }
    *p = 0;
}

void usbdev_poll(void);         /* usbdev.c: the USB device probe on the power jack, served from here */
#ifdef CPU_PROF
void prof_block_start(void);    /* prof.c */
void prof_block_end(uint32_t busy, uint32_t nom);
#endif

/* Replaces the audio task's queue wait (bl @0x080414e4). */
int cpu_wait(void *queue, void *item, uint32_t ticks, int peek)
{
    if (M->magic != MAGIC)
        start();
    uint32_t idle_from = DWT_CYCCNT, busy = idle_from - M->woke;
#ifdef CPU_PROF
    if (M->armed)
        prof_block_end(busy, M->nom);
#endif
    int got = fw_receive(queue, item, ticks, peek);
    usbdev_poll();
    uint32_t now = DWT_CYCCNT, period = now - M->woke;
    if (got != 1) {
        M->armed = 0;
        return got;
    }
    if (M->armed && period > 1000u) {
        uint32_t base = M->nom ? M->nom : period;            /* first report: as it was before, busy / period */
        if (M->nom && period > base + (base >> 1) && M->late < 99u)
            M->late++;                                       /* a block boundary the task did not meet */
        uint32_t load = busy / (base / 1000u + 1u);          /* per mille of the time the engine actually had */
        if (load > 9990u)
            load = 9990u;
        if (M->n >= 60000u) {        /* ~5 minutes without a look: forget the oldest half rather than wrap */
            M->sum >>= 1;
            M->n >>= 1;
        }
        M->sum += load;
        M->n++;
        if (load > M->peak)
            M->peak = (uint16_t)load;
        if (++M->win_n >= BLOCKS_PER_REPORT) {
            M->status = STATUS_OK;
            /*
             * The nominal block, re-estimated: this report's MEAN period. The task cannot wake more often than the
             * SAI DMA fires, so a report's mean can never fall below the true block and anything that goes wrong
             * (late blocks, a missed interrupt, catching up on a backlog) only pushes it UP. Keeping the smallest
             * mean seen since boot therefore settles on the hardware's own rate after one quiet report and is never
             * dragged down by an outlier - which a per-period minimum would be, since a task working through two
             * queued interrupts shows one very short period.
             */
            uint32_t mean = (now - M->win_start) / M->win_n;
            if (mean > PERIOD_FLOOR && (M->nom == 0 || mean < M->nom))
                M->nom = mean;
            M->win_start = now;
            M->win_n = 0;
        }
    }
    if (++M->wakes >= 2 * BLOCKS_PER_REPORT) {
        if (M->n == 0)
            M->status = STATUS_NO_CLOCK;
        M->wakes = 0;
    }
#ifdef CPU_PROF
    prof_block_start();
    now = DWT_CYCCNT;                                        /* the block starts after the profiler's own setup */
#endif
    M->woke = now;
    M->armed = 1;
    return got;
}

/*
 * Replaces the 6-byte copy of the version string into the global cell's info (FUN_0809ad74, address 0x40, the
 * `ldr; ldr; str; ldrh; strh` @0x0809ad84). dest is the info's name field. The knob screen draws that name as its
 * header from three quarters of the way across, and what does not fit wraps round to the left edge (the 3.1.H
 * photos: "Prism 1/" then the "2" at the far left), so a title is 8 characters at most.
 */
const char *master_title(void);  /* master.c: the header for a Compressor / Master FX knob page, or 0 */
int b2_ok(void);                 /* b2head.c: is flash bank 2 the payload this image was built with */

/*
 * The same answer, cached, for the audio path - b2_ok() sums the whole payload and the engine asks every block.
 * The three effects whose DSP lives in bank 2 (Prism, Confetti, the per-pad insert) call this and BYPASS
 * themselves when it is false, because the alternative is what 3.2.l did on 2026-10-10 when bank 2 was erased
 * underneath it: the engine called into 0xff, hard-faulted, and the unit boot-looped on a saved preset. An
 * advisory marker on the version label was NOT enough; a missing or mismatched bank 2 has to be survivable.
 */
/*
 * b2_ok() ALONE IS NOT ENOUGH, and that is the bug that crashed every build from 3.2.m to 3.2.r. It checks the id,
 * which is a hash of bank 2's SOURCE FILES, and a sum that the payload carries about ITSELF - so a payload linked
 * against an older cave passes both: same sources, internally consistent, and calling cave addresses that have
 * since moved. Confetti's `bl rev4_step` went to the middle of relapse_block that way.
 *
 * So bank 1 now carries the sum of the bank 2 payload it was actually LINKED against (build.sh writes it here
 * after the link), and the payload on the unit must carry the same one. A different linked binary has a different
 * sum whatever its sources say, the version gains its "!", and the three effects bypass instead of crashing.
 */
__attribute__((used)) const volatile uint32_t b2_expect_sum = 0xffffffffu;
#define B2_SUM_ON_UNIT (*(const volatile uint32_t *)0x0810000cu)

/*
 * AND THE FLASH ITSELF HAS TO READ CLEANLY (3.2.t). This chip corrects one flipped bit per 256-bit flash word
 * without telling anyone and bus-faults on two, so a marginally written payload passes every check above - the
 * bytes are right - and then kills an instruction fetch once in a while. That was the "random crash while it was
 * playing" on 3.2.s (2026-10-11): the payload written on 2026-10-10 misread about once in 700 word reads.
 * So before trusting bank 2: clear the two ECC flags, read every flash word of the payload B2_SCANS times with
 * the data cache invalidated first (a cached read never touches the flash), and refuse the lot if either flag is
 * set. At that error rate sixteen passes miss it about once in five thousand boots; one pass missed it more often
 * than not. A healthy payload costs ~0.2 ms, once.
 * Not handled, and it matters for the public loader: a word that is PERMANENTLY uncorrectable faults inside this
 * scan on every boot. NOTES has the design (a scan-in-progress mark in backup SRAM that the next boot honours).
 */
#define FLASH_SR2   (*(volatile uint32_t *)0x52002110u)
#define FLASH_CCR2  (*(volatile uint32_t *)0x52002114u)   /* bank 2's flag-clear register: no unlock, no operation */
#define FLASH_ECC   ((1u << 25) | (1u << 26))             /* SNECCERR | DBECCERR */
#define DCIMVAC     (*(volatile uint32_t *)0xe000ef5cu)   /* data cache: forget the line holding this address */
#define B2_SCANS    16
#define B2_BYTE     ((volatile uint8_t *)&M->b2chk)

/*
 * One step on b2chk: clear `clear`, set `set`, return what it held - with interrupts masked, so no other task can
 * get in between the read and the write. NOT LDREXB / STREXB (the compiler's atomic builtins, used until rc4): on
 * later units (serials from ~2001009700, rev V like the test unit) the exclusive load of this byte bus-faults -
 * PRECISERR, BFAR 0x2405FFF3 - while a plain load of it one instruction earlier is fine. JOE DIAG caught it on two
 * units (2026-10-16); why their exclusives take an error and the test unit's do not is not known.
 */
static uint8_t b2_step(uint8_t set, uint8_t clear)
{
    uint32_t primask;
    __asm volatile("mrs %0, primask\n\tcpsid i" : "=r"(primask) : : "memory");
    uint8_t old = *B2_BYTE;
    *B2_BYTE = (uint8_t)((old & ~clear) | set);
    __asm volatile("msr primask, %0" : : "r"(primask) : "memory");
    return old;
}

/*
 * 1 = bank 2 is this image's payload and reads cleanly, 0 = it is not, -1 = another task is in here right now.
 *
 * THE SCAN CAN KILL THE UNIT, and before 3.3.a it would have done so on every boot: a flash word with two bad bits
 * cannot be corrected, the read bus-faults, the fault handler resets, and the next boot reads the same word. So
 * the scan announces itself in backup SRAM first (B2_MARK, see b2.h) and takes the announcement down when it comes
 * back. A boot that finds it still up does not read bank 2 at all: unpaired, effects off, "!" on Tools - and the
 * card loader, if the file is there, erases and rewrites the bank, which is the only thing that can clear a bad
 * word. b2_rescan takes the mark down after a rewrite.
 * B2_SCANNING in b2chk is the same announcement for THIS boot, so a task that preempts another mid-scan does not
 * mistake the mark for a dead scan (b2chk starts from zero every boot - cpu_boot - where the mark does not).
 */
static int b2_paired(void)
{
    if (b2_step(B2_SCANNING, 0) & B2_SCANNING)
        return -1;
    int ok = 0;
    bkp_enable();
    uint32_t mark = *B2_MARK;
    if (mark == B2_MARK_NAMING || mark == B2_MARK_CLAIMING) {
        ok = -1;                 /* the screen task is in b2_present right now, or the loader is looking the bank
                                    over - or one of them was, when an earlier boot died there. Either way no
                                    verdict: the loader's rewrite is what clears a stuck one. */
    } else if (mark != B2_MARK_SCANNING) {
        bkp_put(B2_MARK, B2_MARK_SCANNING);
        if (b2_ok() && B2_SUM_ON_UNIT == b2_expect_sum) {
            uint32_t len = *(const volatile uint32_t *)(B2_BASE + 8u);    /* b2_ok has just range-checked it */
            FLASH_CCR2 = FLASH_ECC;
            for (int pass = 0; pass < B2_SCANS; pass++)
                for (uint32_t a = B2_BASE; a < B2_BASE + len; a += 32u) {
                    DCIMVAC = a;
                    (void)*(const volatile uint32_t *)a;              /* any read of the word checks all 256 bits */
                }
            ok = !(FLASH_SR2 & FLASH_ECC);
        }
        bkp_put(B2_MARK, 0);
    }
    b2_step(0, B2_SCANNING);
    return ok;
}

/*
 * b2chk is written from three tasks - the audio task (b2_live), the screen task (cpu_name) and the disk task (the
 * card loader) - so every change to it is one b2_step (interrupts masked), never a bare read followed by a write.
 * Two tasks that both find it unchecked may both scan; they OR in the same answer. If a marginal flash made them
 * disagree the pair bits read 3, which is not 1, so the effects stay off: the safe direction.
 */
uint8_t b2_state(void)
{
    return M->magic == MAGIC ? M->b2chk : 0u;
}

void b2_flag(uint8_t bits)
{
    b2_step(bits, 0);
}

/* Has the meter's state been set up (the audio task has run), so that b2chk means something? */
int b2_ready(void)
{
    return M->magic == MAGIC;
}

static uint8_t b2_checked(void)
{
    if (!(M->b2chk & B2_PAIR)) {
        int paired = b2_paired();
        if (paired >= 0)         /* -1: someone else is scanning, and will write the verdict */
            b2_flag(paired ? B2_PAIRED : B2_UNPAIRED);
    }
    return M->b2chk & B2_PAIR;
}

int b2_live(void)
{
    if (M->magic != MAGIC)
        return 0;                /* before the meter's first block there is no b2chk to hold a verdict: not yet */
    return b2_checked() == B2_PAIRED;
}

/*
 * Is this image's payload in bank 2? The question the NAME LISTS ask when they are registered, which is while the
 * app is being built - long before the meter is up, so b2_live() would only say "not yet". No ECC passes (that is
 * b2_live's job, and it decides whether anything RUNS); this only decides what the lists call the three effects.
 * The read sits behind a mark of its own (b2.h: B2_MARK_NAMING), so a bank 2 that cannot be read is "not there"
 * from the second boot on instead of a fault on every one. This runs in the screen task, as the app is built.
 * A unit with no payload - someone copied BLACKBOX.bin to the card and nothing else - then shows "---" where
 * Prism, Confetti and the insert types would be, the way stock marks its own unused delay type, instead of
 * effects that can be chosen and do nothing. The places stay, so a preset saved with one keeps its value.
 */
int b2_present(void)
{
    bkp_enable();
    uint32_t mark = *B2_MARK;
    if (mark == B2_MARK_SCANNING || mark == B2_MARK_NAMING || mark == B2_MARK_CLAIMING)
        return 0;                /* a read of bank 2 never came back (or one is under way): do not add another */
    bkp_put(B2_MARK, B2_MARK_NAMING);
    int ok = b2_ok() && B2_SUM_ON_UNIT == b2_expect_sum;
    bkp_put(B2_MARK, 0);
    return ok;
}

/*
 * Once per boot, from fault.c's instrument_boot (so before any audio block): forget the meter's state, b2chk with
 * it. This RAM is not cleared by a reset, and until 3.3.a nothing cleared it - so after a restart without a power
 * cycle (a crash, or an install with the unit left on, as on 2026-10-11) the new boot inherited the old one's
 * "bank 2 is paired, and the loader has looked". A new image with a new payload would have run the old one.
 */
void cpu_boot(void)
{
    M->magic = 0;
}

/* The card loader has just rewritten bank 2: forget the old verdict and scan what is there now. */
int b2_rescan(void)
{
    bkp_enable();
    bkp_put(B2_MARK, 0);         /* what an earlier boot's scan died on has just been erased */
    int ok = b2_paired() > 0;
    if (ok) {
        b2_step(0, B2_PAIR);
        b2_flag(B2_PAIRED);
    }
    return ok;
}

void cpu_name(char *dest)
{
    const char *from = master_title();
    char *p = dest;
    int version = !from;
    if (version)
        from = VERSION;
    while (*from && p < dest + 8)
        *p++ = *from++;
    /*
     * A trailing "!" on the version means flash bank 2 is NOT the payload this image was built with - wrong id,
     * wrong length or a bad sum - so the relocated effects (Prism, Confetti, the per-pad insert models) are not
     * to be trusted. Checked once and remembered: the sum walks the whole payload, and this runs on every knob
     * page header.
     */
    if (version && M->magic == MAGIC) {
        if (b2_checked() != B2_PAIRED && p < dest + 8)
            *p++ = '!';
        /*
         * And what the card loader made of the bank 2 file on the card, while that is still being proven on
         * hardware: "+" it is there and it is this image's payload, "-" there is none, "?" it is some other
         * payload or damaged. Nothing = the loader has not looked (no card found yet).
         */
        static const char verdict[4] = {0, '+', '-', '?'};
        char v = verdict[(M->b2chk >> B2_FILE_SHIFT) & 3u];
        if (v && p < dest + 8)
            *p++ = v;
    }
    *p = 0;
}

/*
 * Replaces the Tools refresh's call that sets the free-space label (bl FUN_080a3dec @0x080c52a4): the empty label
 * before it in the bar gets the load. GUI task.
 */
void cpu_tools(uint8_t *space_label, const char *space)
{
    char buf[16];
    fw_label_set(space_label, space);
    if (M->n) {                  /* close off the period being reported BEFORE composing it, not after */
        M->avg_shown = (uint16_t)(M->sum / M->n);
        M->peak_shown = M->peak;
        M->sum = 0;
        M->n = M->peak = 0;
    }
    compose(buf);                /* reads avg_shown / peak_shown / late */
    M->late = 0;                 /* drawn: the next look reports only what happens from here */
    fw_label_set(space_label - LABEL_SIZE, buf);
}
