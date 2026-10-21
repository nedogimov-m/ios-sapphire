/* Pixel 5 first stage. No storage, power-domain, clock or GIC writes. */
#include <stdint.h>
#include "fdt.h"
#include "config.h"
#include "loader.h"
#include "../../shim/font.h"

#define MRS(reg) ({ uint64_t v; __asm__ volatile("mrs %0, " #reg : "=r"(v)); v; })
static volatile uint32_t *fb;
static unsigned row;
static struct hardware hw;

/* Kept in the loaded Image for a debugger; never written to device storage. */
volatile struct {
    uint64_t magic, dtb, midr, mpidr, mmfr0, timer_hz, current_el, status;
} redfin_report;

static void line(const char *s, uint64_t n)
{
    if (!fb || row >= 65) return;
    char buf[41];
    unsigned len = 0;
    while (*s && len < 20) buf[len++] = *s++;
    while (len < 21) buf[len++] = ' ';
    for (int shift = 60; shift >= 0; shift -= 4)
        buf[len++] = "0123456789ABCDEF"[(n >> shift) & 15];
    buf[len] = 0;
    for (unsigned i = 0; i < len; i++)
        for (unsigned y = 0; y < 16; y++)
            for (unsigned x = 0; x < 8; x++) {
                unsigned char c = (unsigned char)buf[i];
                uint32_t pixel = font8x16[c - 32][y] & (0x80 >> x) ? 0xffffffff : 0xff000000;
                for (unsigned sy = 0; sy < 2; sy++)
                    for (unsigned sx = 0; sx < 2; sx++)
                        fb[(24 + row * 32 + y * 2 + sy) * (DIAG_STRIDE / 4) +
                           24 + i * 16 + x * 2 + sx] = pixel;
            }
    row++;
}

static uint64_t smc(uint64_t fn)
{
    register uint64_t x0 __asm__("x0") = fn;
    register uint64_t x1 __asm__("x1") = 0;
    register uint64_t x2 __asm__("x2") = 0;
    register uint64_t x3 __asm__("x3") = 0;
    __asm__ volatile("smc #0" : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3) : :
        "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11", "x12", "x13",
        "x14", "x15", "x16", "x17", "memory");
    return x0;
}

void secondary_main(uint64_t cpu) { (void)cpu; for (;;) __asm__ volatile("wfe"); }

void exc_handler(uint64_t slot, uint64_t *regs)
{
    (void)regs;
    redfin_report.status = 0x100 + slot;
    /* Avoid repeated faults if the framebuffer itself caused the exception. */
    fb = 0;
    for (;;) __asm__ volatile("wfe");
}

void shim_main(uint64_t dtb)
{
    redfin_report.magic = 0x52454446494e3031; /* REDFIN01 */
    redfin_report.dtb = dtb;
    redfin_report.current_el = MRS(CurrentEL);
    redfin_report.midr = MRS(midr_el1);
    redfin_report.mpidr = MRS(mpidr_el1);
    redfin_report.mmfr0 = MRS(id_aa64mmfr0_el1);
    redfin_report.timer_hz = MRS(cntfrq_el0);
    if (redfin_fdt((const void *)(uintptr_t)dtb, &hw) || !hw.redfin) {
        redfin_report.status = 1;
        return;
    }
    /* Explicit build option: reservation start/stride are scanout hypotheses.
     * All framebuffer stores must remain within the live FDT's splash range. */
    uint64_t size = (uint64_t)DIAG_STRIDE * 2340;
    if (DIAG_SPLASH && hw.splash.base && !(hw.splash.base & 3) && hw.splash.size >= size) {
        fb = (volatile uint32_t *)(uintptr_t)hw.splash.base;
        for (unsigned y = 0; y < 2340; y++)
            for (unsigned x = 0; x < 1080; x++) fb[y * (DIAG_STRIDE / 4) + x] = 0xff000000;
    }
    line("REDFIN DIAGNOSTICS", 1);
    line("XNU PAYLOAD BYTES", XNU_PAYLOAD_SIZE);
    line("CURRENT EL", redfin_report.current_el >> 2);
    line("MIDR", redfin_report.midr);
    line("MPIDR", redfin_report.mpidr);
    line("MMFR0", redfin_report.mmfr0);
    line("16K FIELD", (redfin_report.mmfr0 >> 20) & 15);
    line("TIMER HZ", redfin_report.timer_hz);
    line("DTB", dtb);
    line("SPLASH BASE", hw.splash.base);
    line("SPLASH SIZE", hw.splash.size);
    for (unsigned i = 0; i < hw.banks; i++) {
        line("RAM BASE", hw.memory[i].base);
        line("RAM SIZE", hw.memory[i].size);
    }
    if (hw.psci_smc) line("PSCI VERSION", smc(0x84000000));
    redfin_report.status = 2;
#if XNU_PAYLOAD_SIZE
    redfin_report.status = 3;
    const char *why = redfin_boot(dtb, &hw);
    redfin_report.status = 4;
    line(why, 0);
#endif
    line("RESET AFTER SECONDS", DIAG_SECONDS);
    uint64_t start = MRS(cntpct_el0), hz = redfin_report.timer_hz;
    if (!hz || hz > 1000000000) return;
    while (MRS(cntpct_el0) - start < hz * DIAG_SECONDS) __asm__ volatile("yield");
    if (hw.psci_smc) smc(0x84000009); /* PSCI SYSTEM_RESET; no PSHOLD/IMEM MMIO. */
}
