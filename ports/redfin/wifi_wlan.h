/* SPDX-License-Identifier: MIT
 * Read-only discovery of legacy ICNSS's five native CMD-DB VRM resources.
 * Include after redfin_rpmh.h. No RSC, PMIC, clock or WLAN write API here.
 */
#ifndef REDFIN_WIFI_WLAN_H
#define REDFIN_WIFI_WLAN_H
#define RF_WLAN_SUPPLIES 5u
static const uint8_t rf_wlan_supply_names[RF_WLAN_SUPPLIES][8] = {
    "ldoa1", "ldoa14", "ldoc2", "ldoc11", "ldoc10"};
static const uint32_t rf_wlan_supply_addresses[RF_WLAN_SUPPLIES] = {
    0x40800, 0x42100, 0x41d00, 0x41a00, 0x41900};
static const uint32_t rf_wlan_supply_mv[RF_WLAN_SUPPLIES] = {352, 1800, 1304, 3000, 3000};
#define RF_WLAN_MAX_VOTES (RF_WLAN_SUPPLIES * 3u)
struct rf_wlan_resources { struct rf_cmddb_resource supply[RF_WLAN_SUPPLIES]; };
struct rf_wlan_vote { uint32_t address, value, supply, parameter; };
struct rf_wlan_plan { uint32_t votes, chain1; struct rf_wlan_vote vote[RF_WLAN_MAX_VOTES]; };
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
/* Native provider initialization supplies voltage/mode before enabling a
 * consumer. The CX consumer's 0/0 override preserves its provider's352mV
 * initialization; the other final requests follow the captured native DT.
 * No PMIC command is sent by this planner. parameter0=mv,1=en,2=mode. */
static inline int rf_wlan_power_plan(const struct rf_wlan_resources *resources,
    unsigned chain_present, uint32_t chain, struct rf_wlan_plan *out)
{
    if (!resources || !out || chain_present > 1 || (chain_present && chain > 2)) return -1;
#ifdef __cplusplus
    struct rf_wlan_plan plan = {};
#else
    struct rf_wlan_plan plan = {0};
#endif
    plan.chain1 = !chain_present || chain != 1;
    for (unsigned i = 0; i < RF_WLAN_SUPPLIES; ++i) {
        const struct rf_cmddb_resource *r = &resources->supply[i];
        if (r->address != rf_wlan_supply_addresses[i] || r->type != RF_CMDDB_VRM ||
            r->aux_version != 0x100 || r->aux_bytes != 4 || r->priority[0] || r->priority[1]) return -1;
        if (i == 3 && !plan.chain1) continue;
        const uint32_t parameter[3] = {0, 2, 1};
        const uint32_t value[3] = {rf_wlan_supply_mv[i], 4, 1};
        for (unsigned j = 0; j < 3; ++j) {
            struct rf_wlan_vote *vote = &plan.vote[plan.votes++];
            vote->address = r->address + 4u * parameter[j]; vote->value = value[j];
            vote->supply = i; vote->parameter = parameter[j];
        }
    }
    *out = plan;
    return 0;
}
#endif
