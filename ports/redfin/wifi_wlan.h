/* SPDX-License-Identifier: MIT
 * Read-only discovery of legacy ICNSS's five native CMD-DB VRM resources.
 * Include after redfin_rpmh.h. No RSC, PMIC, clock or WLAN write API here.
 */
#ifndef REDFIN_WIFI_WLAN_H
#define REDFIN_WIFI_WLAN_H
#define RF_WLAN_SUPPLIES 5u
static const uint8_t rf_wlan_supply_names[RF_WLAN_SUPPLIES][8] = {
    "ldoa1", "ldoa14", "ldoc2", "ldoc11", "ldoc10"};
struct rf_wlan_resources { struct rf_cmddb_resource supply[RF_WLAN_SUPPLIES]; };
static inline int rf_wlan_resources_read(const volatile uint8_t *db, struct rf_wlan_resources *out)
{
    if (!db || !out) return -1;
#ifdef __cplusplus
    struct rf_wlan_resources first = {}, second = {};
#else
    struct rf_wlan_resources first = {0}, second = {0};
#endif
    for (unsigned pass = 0; pass < 2; ++pass) {
        struct rf_wlan_resources *selected = pass ? &second : &first;
        for (unsigned i = 0; i < RF_WLAN_SUPPLIES; ++i) {
            struct rf_cmddb_resource *r = &selected->supply[i];
            if (rf_cmddb_lookup(db, RF_CMDDB_BYTES, rf_wlan_supply_names[i], RF_CMDDB_VRM, r) != RF_CMDDB_OK ||
                r->type != RF_CMDDB_VRM || !r->address || (r->address & 3u) || r->address > UINT32_MAX - 12u)
                return -1;
            for (unsigned j = 0; j < i; ++j) {
                uint32_t prior = selected->supply[j].address;
                if (r->address < prior + 16u && prior < r->address + 16u) return -1;
            }
        }
    }
    for (unsigned i = 0; i < RF_WLAN_SUPPLIES; ++i) {
        const struct rf_cmddb_resource *a = &first.supply[i], *b = &second.supply[i];
        if (a->address != b->address || a->type != b->type || a->aux_version != b->aux_version ||
            a->aux_bytes != b->aux_bytes || a->priority[0] != b->priority[0] || a->priority[1] != b->priority[1])
            return -1;
    }
    *out = first;
    return 0;
}
#endif
