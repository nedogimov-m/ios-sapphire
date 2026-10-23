/* SPDX-License-Identifier: MIT
 * GUI2 serial handoff: touch finishes DRV2 setup before WLAN can acquire its
 * writer. Touch continues its SPI/HID loop; it issues no more RPMh commands.
 * All native firmware/radio MMIO remains on the bound CPU0 worker.
 */
#include <pexpert/arm64/board_config.h>
#include <pexpert/pexpert.h>
#include <arm64/redfin_gui_profile.h>
#include <sys/systm.h>
#include <sys/redfin_wifi_gui.h>
extern int redfin_gui_cpu0(void);
extern int redfin_spmi_return_ready(void);
extern bool redfin_touch_boot_lease_valid(unsigned);
extern bool redfin_touch_boot_lease_held(unsigned);
extern int redfin_touch_rail_ready(void);
extern void redfin_wifi_fw_start(void);
/* One frozen boot epoch. The touch owner never releases DRV2/SE0; a stopped
 * SPI event session does not revoke the retained rail/return ownership.
 * 0=unclaimed, 3=preparing/refused, 1=published, 2=stopped (never restart). */
static unsigned wifi_gui_handoff;
static const char *wifi_gui_arguments;
static char wifi_gui_frozen[608];
static unsigned wifi_gui_bytes;
static uint64_t wifi_gui_epoch;

static bool wifi_gui_unchanged(void)
{
    const char *args = PE_boot_args();
    bool valid = args && args == wifi_gui_arguments && wifi_gui_bytes && wifi_gui_epoch &&
        !memcmp(args, wifi_gui_frozen, wifi_gui_bytes);
    if (!valid) {
        unsigned expected = 1;
        (void)__atomic_compare_exchange_n(&wifi_gui_handoff, &expected, 2, false,
            __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE);
    }
    return valid;
}

bool redfin_wifi_gui_requested(void)
{
    unsigned state = __atomic_load_n(&wifi_gui_handoff, __ATOMIC_ACQUIRE);
    if (state == 1 || state == 2) return wifi_gui_unchanged();
    if (state == 3) return false;
    const char *args = PE_boot_args();
    unsigned bytes = 0;
    if (!args) return false;
    while (bytes < 608 && args[bytes]) ++bytes;
    return bytes < 608 && redfin_wifi_gui_profile(args, bytes + 1, NULL);
}
bool redfin_wifi_gui_ready(void)
{
    return __atomic_load_n(&wifi_gui_handoff, __ATOMIC_ACQUIRE) == 1 &&
        redfin_gui_cpu0() && wifi_gui_unchanged() && redfin_touch_boot_lease_held(2);
}
bool redfin_wifi_gui_boot_id(uint64_t *epoch)
{
    if (!epoch || !redfin_wifi_gui_ready()) return false;
    *epoch = wifi_gui_epoch;
    return true;
}
bool redfin_wifi_return_held(void)
{ return redfin_spmi_return_ready() == 1 || redfin_wifi_gui_ready(); }
void redfin_wifi_gui_start(void)
{
    if (!redfin_wifi_gui_requested() || !redfin_gui_cpu0() ||
        !redfin_touch_boot_lease_valid(2) || redfin_touch_rail_ready() != 1) return;
    unsigned expected = 0;
    if (!__atomic_compare_exchange_n(&wifi_gui_handoff, &expected, 3, false, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) return;
    const char *args = PE_boot_args();
    unsigned bytes = 0;
    if (args) while (bytes < sizeof(wifi_gui_frozen) && args[bytes]) ++bytes;
    if (!args || bytes == sizeof(wifi_gui_frozen) ||
        !redfin_wifi_gui_profile(args, bytes + 1, &wifi_gui_epoch)) return;
    memcpy(wifi_gui_frozen, args, bytes + 1);
    wifi_gui_arguments = args; wifi_gui_bytes = bytes + 1;
    if (!wifi_gui_unchanged() || !redfin_touch_boot_lease_valid(2)) return;
    __atomic_store_n(&wifi_gui_handoff, 1, __ATOMIC_RELEASE);
    printf("REDFIN WIFI GUI: touch DRV2 setup complete; starting the serialized native radio worker\n");
    redfin_wifi_fw_start();
}
void redfin_wifi_gui_stop(void)
{
    unsigned expected = 1;
    if (__atomic_compare_exchange_n(&wifi_gui_handoff, &expected, 2, false,
        __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE))
        printf("REDFIN WIFI GUI: shutdown revoked the worker lease; remote-visible state retained until reset\n");
}
