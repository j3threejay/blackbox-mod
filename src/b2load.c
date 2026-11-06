/*
 * The card loader: flash bank 2 written from a file on the SD card. Original 1010music Blackbox, firmware 3.1.9.
 *
 * WHY. The SD installer writes bank 1 only, so everything in bank 2 (Prism, Confetti, the per-pad insert models)
 * reached the test unit over the USB poke. That cannot ship: the rule is that everything installs from the card, "so we
 * knew it worked for other people", and the raw poke can write anywhere, bank 1's flash controls included. With
 * this, an install is two files on the card - BLACKBOX.bin through stock's installer as always, and B2_NAME, which
 * this code programs into bank 2 itself the first time it finds bank 2 is not the payload this image was built with.
 *
 * WHERE IT RUNS, and each of these was read out of stock, not assumed:
 *  - Stock's FatFs is NOT re-entrant (validate() at 0x08084440 takes no lock) and stock keeps it safe by doing all
 *    card access in one task: "pcmStreamer", entry 0x08043e74, whose loop FUN_080743b0 serves the file commands the
 *    screen task queues (FUN_08092f5c) and the sample streaming in turn. So this is called from that loop, in front
 *    of each of its three calls to FUN_08092f5c (b2load_thunk.S), and nowhere else.
 *  - A card read needs the scheduler: stock's disk driver waits on a queue the SDMMC interrupt posts to
 *    (0x08045ad8 / 0x08045aec). So not before the tasks run, and never from the audio task.
 *  - pcmStreamer is priority 0, the same as the screen task ("defaultTask") and below audioTask at 3 (the table at
 *    0x080cfbb0). Waiting here for a sector erase therefore costs the audio nothing and time-slices with the screen.
 *  - THE WATCHDOG WATCHES THIS TASK. The window watchdog is fed from the audio block (FUN_08046994) only while both
 *    monitored tasks have stamped within 3,750 blocks = 10 s; this task's stamp is FUN_080469c4 on 0x2400a584, which
 *    stock calls round its own long loops. Anything long in here has to stamp too, or the unit resets mid-write.
 *
 * WHAT MAY BE WRITTEN: bank 2 through bank 2's own registers (KEYR2 / CR2 / CCR2) - sectors 0-5 erased and
 * programmed, one claim word programmed once at the start of sector 6 - and that is checked on every erase and
 * every word, after a look at what is already there (owned(), below). NEVER bank 1's CR1 / KEYR1 - bank 1 holds the bootloader, the one mistake with no
 * recovery - and never sector 7 (0x081E0000), the unit's factory calibration. The recipe is the one BANK2.md
 * proved on the test unit and measure/bank2_write.py has used since.
 *
 * NOTHING MAY READ BANK 2 WHILE IT IS WRITTEN: a read of a bank under erase stalls until the erase ends, most of a
 * second. So it only writes when the pairing check has already said "not paired" (the three effects are bypassed
 * and nothing executes up there), and the header - the flash word that makes a payload valid - goes on LAST, so a
 * write cut short by the power leaves something the next boot sees as no payload and simply does again.
 *
 * A FLASH WORD THAT CANNOT BE READ faults the pairing scan. cpu.c's scan leaves a mark in backup SRAM for the next
 * boot (b2.h), which then keeps off bank 2 and lets this code rewrite it - at most B2_MAX_TRIES times per payload.
 *
 * A UNIT WITH NO PAYLOAD lists the three effects as "---" (cpu.c's b2_present, asked when the lists are built), and
 * a successful write here restarts the unit so the lists are built again with the payload in place.
 */
#include "b2.h"

#define FN(addr) ((addr) | 1u)
typedef int (*f_open_fn)(void *file, const char *path, unsigned mode);
typedef int (*f_read_fn)(void *file, void *to, unsigned bytes, unsigned *got);
typedef int (*f_close_fn)(void *file);
#define fw_f_open   ((f_open_fn)FN(0x08086534))
#define fw_f_read   ((f_read_fn)FN(0x08086866))
#define fw_f_close  ((f_close_fn)FN(0x08086d76))
#define FIL_BYTES   0x58         /* stock clears this much before every f_open (FUN_080971cc): FatFs built tiny */
#define FA_READ     1u

/* 8.3 on purpose, so it does not depend on how stock's FatFs was built for long names. Root of the card, as the
   empty path stock opens to see whether a card is there (0x080cb060). */
static const char B2_NAME[] = "BBEXTRA.BIN";

/* 1 = this build programs bank 2 from the file; 0 = it only reads the file and reports (test_b2load.py asks). */
__attribute__((used)) const uint8_t b2load_writes = B2LOAD_WRITE;

#define CARD_FOUND  (*(const volatile uint8_t *)(0x240021a4u + 0x15u))  /* stock's own "the root opened" (FUN_08042c90) */
#define WDG_DISK    (*(volatile uint32_t *)0x2400a584u)                 /* this task's stamp ... */
#define WDG_NOW     (*(const volatile uint32_t *)0x2400a58cu)           /* ... and the counter it copies */

#define FLASH_KEYR2 (*(volatile uint32_t *)0x52002104u)
#define FLASH_CR2   (*(volatile uint32_t *)0x5200210cu)
#define FLASH_SR2   (*(volatile uint32_t *)0x52002110u)
#define FLASH_CCR2  (*(volatile uint32_t *)0x52002114u)
#define KEY1        0x45670123u
#define KEY2        0xcdef89abu
#define CR_LOCK     (1u << 0)
#define CR_PG       (1u << 1)
#define CR_SER      (1u << 2)
#define CR_PSIZE64  (3u << 4)
#define CR_START    (1u << 7)
#define SR_BUSY     ((1u << 0) | (1u << 1) | (1u << 2))                /* BSY | WBNE | QW */
#define SR_EOP      (1u << 16)
#define SR_ERRORS   ((1u << 17) | (1u << 18) | (1u << 19) | (1u << 21) | (1u << 22) | (1u << 23) | (1u << 24))
#define SR_ECC      ((1u << 25) | (1u << 26))
#define DCIMVAC     (*(volatile uint32_t *)0xe000ef5cu)                 /* data cache: forget this line */
#define ICIALLU     (*(volatile uint32_t *)0xe000ef50u)                 /* instruction cache: forget everything */

/* Loop counts, not times: no clock in here can be trusted to be running. An erase measured 0.87 s on the test unit;
   these give up after some seconds of a controller that never comes back, and the watchdog covers anything worse. */
#define SPINS_ERASE 400000000u
#define SPINS_WORD  20000000u

static void stamp(void)
{
    WDG_DISK = WDG_NOW;
}

struct src {
    uint32_t file[FIL_BYTES / 4];
};

static int src_open(struct src *s)
{
    for (unsigned i = 0; i < FIL_BYTES / 4; i++)
        s->file[i] = 0;
    return fw_f_open(s->file, B2_NAME, FA_READ) == 0;
}

/* The file is read a flash word at a time: 32 bytes, eight words. */
static int src_word(struct src *s, uint32_t w[8])
{
    unsigned got = 0;
    return fw_f_read(s->file, w, 32u, &got) == 0 && got == 32u;
}

/* Is this first flash word the header of the payload THIS image was linked with? (b2head.c's b2_ok, on the file.) */
static int header_ok(const uint32_t w[8])
{
    uint32_t len = w[2];
    return w[0] == B2_MAGIC && w[1] == (uint32_t)B2_ID && len >= 32u && len <= B2_LIMIT && !(len & 31u)
           && w[3] == b2_expect_sum;
}

/* Read the whole file and say what it is. Nothing is erased on the strength of a header alone. */
static unsigned file_verdict(void)
{
    struct src s;
    uint32_t w[8];
    if (!src_open(&s))
        return B2_FILE_NONE;
    unsigned verdict = B2_FILE_WRONG;
    if (src_word(&s, w) && header_ok(w)) {
        uint32_t len = w[2], want = w[3], sum = w[4] + w[5] + w[6] + w[7], at = 32u;
        for (; at < len && src_word(&s, w); at += 32u) {
            for (int i = 0; i < 8; i++)
                sum += w[i];
            if (!(at & 0xffffu))
                stamp();
        }
        if (at >= len && sum == want)
            verdict = B2_FILE_OK;
    }
    fw_f_close(s.file);
    return verdict;
}

/* ---- bank 2's flash controller ---- */

/* As ST's own flash driver does round every step: nothing may still be sitting in the core's write buffer when the
   status register is read. Over USB each step was milliseconds apart; from here they are consecutive instructions. */
static inline void barrier(void)
{
    __asm__ volatile("isb\n dsb");
}

static int flash_wait(uint32_t spins)
{
    while (FLASH_SR2 & SR_BUSY)
        if (!spins--)
            return 0;
    return !(FLASH_SR2 & SR_ERRORS);
}

static int flash_unlock(void)
{
    if (FLASH_CR2 & CR_LOCK) {
        FLASH_KEYR2 = KEY1;
        FLASH_KEYR2 = KEY2;
    }
    if (FLASH_CR2 & CR_LOCK)
        return 0;
    FLASH_CCR2 = SR_ERRORS | SR_ECC | SR_EOP;            /* start from clean flags */
    return 1;
}

static int flash_erase(unsigned sector)
{
    if (sector >= B2_LIMIT / B2_SECTOR || !flash_wait(SPINS_WORD))
        return 0;
    FLASH_CR2 = CR_PSIZE64 | CR_SER | (sector << 8);
    FLASH_CR2 = CR_PSIZE64 | CR_SER | (sector << 8) | CR_START;
    barrier();
    int ok = flash_wait(SPINS_ERASE);
    FLASH_CR2 = CR_PSIZE64;
    return ok;
}

/* One 256-bit flash word = eight consecutive word writes, which start the programming themselves. */
static int flash_word(uint32_t at, const uint32_t w[8])
{
    if (at >= B2_END || (at & 31u))
        return 0;
    volatile uint32_t *to = (volatile uint32_t *)(B2_BASE + at);
    FLASH_CR2 = CR_PSIZE64 | CR_PG;
    barrier();
    for (int i = 0; i < 8; i++)
        to[i] = w[i];
    barrier();
    int ok = flash_wait(SPINS_WORD);
    FLASH_CR2 = CR_PSIZE64;
    return ok;
}

/*
 * WHOSE IS IT? The loader erases, and an erase cannot be taken back. On the test unit bank 2's sectors 0-6 were blank
 * before the mod used them, and stock's own code points at nothing up there but the calibration in sector 7 - but
 * that is one unit and one firmware, and the bootloader has never been read. So before the first erase on any unit
 * the loader looks: sectors 0-6 must be BLANK, or blank after one of the mod's own payloads from before this check
 * existed (3.2.l - 3.3.c, which begin "BB2!"). Then it writes a claim, one flash word at the start of sector 6,
 * which nothing here ever erases - the payload is kept to sectors 0-5 - and from then on the claim is the answer:
 * a bank left half-erased by a power cut is still the mod's, and is simply erased again.
 * Anything else up there is left exactly as it is: the effects stay off, "!" stays on Tools, B2_FOREIGN is set.
 * The look is a read of flash that may not be readable, so it sits behind its own mark (b2.h): a boot that finds
 * that mark keeps away, and a boot that finds the SCAN's or the NAMES' mark - the payload area cannot be read -
 * trusts only a claim it can see, because proving the bank blank would mean reading the same bad word again.
 */
static const uint32_t claim_word[8] = {B2_CLAIM, ~B2_CLAIM, 1u, 0, 0, 0, 0, 0};

static int claimed(void)
{
    DCIMVAC = B2_BASE + B2_CLAIM_AT;
    return *(const volatile uint32_t *)(B2_BASE + B2_CLAIM_AT) == B2_CLAIM;
}

static int virgin(void)
{
    const volatile uint32_t *p = (const volatile uint32_t *)B2_BASE;
    uint32_t i = 0;
    if (p[0] == B2_MAGIC && p[2] >= 32u && p[2] <= B2_LIMIT && !(p[2] & 31u))
        i = p[2] / 4u;                                    /* one of ours, from before the claim: skip over it */
    for (; i < B2_END / 4u; i++) {
        if (p[i] != 0xffffffffu)
            return 0;
        if (!(i & 0x3fffu))
            stamp();
    }
    return 1;
}

static int owned(void)
{
    bkp_enable();
    uint32_t was = *B2_MARK;
    if (was == B2_MARK_CLAIMING)
        return 0;                                        /* this very look never came back, in an earlier boot */
    int dead = was == B2_MARK_SCANNING || was == B2_MARK_NAMING;
    bkp_put(B2_MARK, B2_MARK_CLAIMING);
    int ok = claimed();
    if (!ok && !dead && virgin()) {
        ok = flash_unlock() && flash_word(B2_CLAIM_AT, claim_word);
        FLASH_CR2 = CR_PSIZE64 | CR_LOCK;
        ok = ok && claimed();
    }
    bkp_put(B2_MARK, dead ? was : 0u);                   /* a dead scan's mark stays up until the bank is rewritten */
    return ok;
}

/*
 * Write the card file into bank 2. Only ever called with the pairing check saying "not paired", so nothing is
 * executing from bank 2 or reading it. Returns nonzero when every step reported clean; whether the result can be
 * trusted is b2_rescan()'s call, which reads it back through the ECC flags.
 */
int b2_program(void)
{
    struct src s;
    uint32_t first[8], w[8];
    if (!src_open(&s))
        return 0;
    int ok = src_word(&s, first) && header_ok(first) && owned() && flash_unlock();
    uint32_t len = first[2];
    for (unsigned sector = 0; ok && sector * B2_SECTOR < len; sector++) {
        ok = flash_erase(sector);
        stamp();
    }
    for (uint32_t at = 32u; ok && at < len; at += 32u) {
        ok = src_word(&s, w) && flash_word(at, w);
        if (!(at & 0x1fffu))
            stamp();
    }
    if (ok)
        ok = flash_word(0, first);                       /* the header last: it is what makes the payload valid */
    FLASH_CR2 = CR_PSIZE64 | CR_LOCK;
    fw_f_close(s.file);
    /* The caches may still hold the old bank 2: the pairing check read it before it was rewritten. */
    for (uint32_t a = B2_BASE; ok && a < B2_BASE + len; a += 32u)
        DCIMVAC = a;
    ICIALLU = 0;
    __asm__ volatile("dsb\n isb");
    stamp();
    return ok;
}

/*
 * How many times this payload has been programmed without a clean scan after it (b2.h). A flash that cannot hold
 * the payload would otherwise be erased and rewritten on every boot for ever - and when the failure is a word the
 * scan cannot even read, every one of those boots ends in a fault. Twice, then leave it: effects off, "!" on
 * Tools. A different payload starts its own count, so a new file or a new build always gets its tries.
 */
#if B2LOAD_WRITE                 /* the tries and the restart are the writer's: B2LOAD_WRITE=0 builds without them */
static uint32_t tries_key(void)
{
    return (uint32_t)B2_ID ^ b2_expect_sum ^ 0x54524932u;
}

static unsigned tries(void)
{
    bkp_enable();
    return *B2_TRIES_ID == tries_key() && *B2_TRIES_N <= B2_MAX_TRIES ? *B2_TRIES_N : 0u;
}

static void tries_set(unsigned n)
{
    bkp_put(B2_TRIES_ID, tries_key());
    bkp_put(B2_TRIES_N, n);
}

/*
 * Bank 2 has just been written and reads back good: start again from the top. The lists were registered while it
 * was still the old bank 2 (or none), so they are calling the three effects "---"; the next boot registers them
 * by name, and the effects are live from its first block instead of switching on under a running engine.
 * Nothing is in flight to lose: all card access is this task's and it is between file commands, and the two
 * backup SRAM words just written went through bkp_put. It cannot loop - the next boot finds bank 2 paired and
 * writes nothing - and B2_MAX_TRIES bounds it even if that were to fail.
 */
static void restart(void)
{
    __asm__ volatile("dsb");
    *(volatile uint32_t *)0xe000ed0cu = (0x5fau << 16) | (1u << 2);      /* AIRCR: SYSRESETREQ */
    for (;;)
        ;
}
#endif

/*
 * b2load_thunk.S calls this from the disk task, in front of every file command step. It does its work once a
 * boot, the first time stock has found a card: B2_LOOKED goes up BEFORE anything else, so an attempt that dies
 * half way is not repeated until the next power-on.
 */
void b2_load_poll(void)
{
    if (!b2_ready() || (b2_state() & B2_LOOKED) || CARD_FOUND != 1u)
        return;
    int live = b2_live();                                /* settles the pairing if nobody has asked yet */
    b2_flag(B2_LOOKED);
    unsigned verdict = file_verdict();
    b2_flag((uint8_t)(verdict << B2_FILE_SHIFT));
#if B2LOAD_WRITE
    if (live) {
        owned();                 /* paired means it is the mod's beyond doubt: a unit whose payload was put there
                                    before the claim existed (the test unit, and no other) gets its claim now, while the
                                    bank reads well, so a later bad word can still be repaired */
    } else if (verdict == B2_FILE_OK && !owned()) {
        b2_flag(B2_FOREIGN);                             /* not blank and not ours: it is not this code's to erase */
    } else if (verdict == B2_FILE_OK) {
        unsigned n = tries();
        if (n < B2_MAX_TRIES) {
            tries_set(n + 1u);                           /* before the write, so one that kills the boot still counts */
            if (b2_program() && b2_rescan()) {
                tries_set(0);
                restart();
            }
        }
    }
#else
    (void)live;                  /* this build only reads the file and reports: the write is proven separately */
#endif
}
