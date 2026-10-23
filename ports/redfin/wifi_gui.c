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
extern int redfin_touch_rail_ready(void);
extern void redfin_wifi_fw_start(void);
static unsigned wifi_gui_handoff;

bool redfin_wifi_gui_requested(void)
{
    const char *args = PE_boot_args();
    unsigned bytes = 0;
    if (!args) return false;
    while (bytes < 608 && args[bytes]) ++bytes;
    return bytes < 608 && redfin_wifi_gui_profile(args, bytes + 1, NULL);
}
bool redfin_wifi_gui_ready(void)
{
    return __atomic_load_n(&wifi_gui_handoff, __ATOMIC_ACQUIRE) == 1 &&
        redfin_gui_cpu0() && redfin_wifi_gui_requested() && redfin_touch_boot_lease_valid(2);
}
bool redfin_wifi_return_held(void)
{ return redfin_spmi_return_ready() == 1 || redfin_wifi_gui_ready(); }
void redfin_wifi_gui_start(void)
{
    if (!redfin_wifi_gui_requested() || !redfin_gui_cpu0() ||
        !redfin_touch_boot_lease_valid(2) || redfin_touch_rail_ready() != 1) return;
    unsigned expected = 0;
    if (!__atomic_compare_exchange_n(&wifi_gui_handoff, &expected, 1, false, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) return;
    printf("REDFIN WIFI GUI: touch DRV2 setup complete; starting the serialized native radio worker\n");
    redfin_wifi_fw_start();
}
