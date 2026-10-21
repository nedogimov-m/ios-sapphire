#include "watchdog.h"

/* Google redbull watchdog_v2.c: WDT_HZ defaults to 32765, not 32768.
 * Source: kernel/msm commit 500b3a2059c1eec0fec08ec56add06320ea901a8,
 * drivers/soc/qcom/watchdog_v2.c, init_watchdog_data().
 */
int redfin_watchdog(const struct hardware *hw, unsigned seconds)
{
    /* KPSS timers have 20 significant bits; reserve three seconds for bite. */
    if (!hw || !hw->redfin || !hw->psci_smc || seconds < 10 || seconds > 29 ||
        hw->watchdog.base != 0x17c10000ULL || hw->watchdog.size != 0x1000)
        return -1;
    volatile uint32_t *wdt = (volatile uint32_t *)(uintptr_t)hw->watchdog.base;
    wdt[0x08 / 4] = 0;                 /* Disable before changing timers. */
    __asm__ volatile("dsb sy" ::: "memory");
    wdt[0x04 / 4] = 1;                 /* Reset elapsed counter. */
    wdt[0x10 / 4] = seconds * 32765U;   /* Bark. Interrupt stays masked. */
    wdt[0x14 / 4] = (seconds + 3) * 32765U; /* Hardware bite/reset. */
    __asm__ volatile("dsb sy" ::: "memory");
    wdt[0x08 / 4] = 1;
    wdt[0x04 / 4] = 1;
    __asm__ volatile("dsb sy" ::: "memory");
    return 0;
}
