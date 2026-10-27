/* SPDX-License-Identifier: MIT */
/* Redfin side/volume transitions. Hardware reads and native HID delivery live
 * on the existing PMIC owner; this policy never invents repeats or holds. */
#ifndef REDFIN_CONTROLS_POLICY_H
#define REDFIN_CONTROLS_POLICY_H
#include <stdint.h>
#include <stdbool.h>
#include <string.h>

#define RF_KEYS_COUNT 3u
#define RF_KEYS_MASK 7u
#define RF_KEYS_DEBOUNCE_NS UINT64_C(15000000)
enum {RF_KEY_POWER,RF_KEY_VOLUME_UP,RF_KEY_VOLUME_DOWN};
typedef void (*rf_keys_emit)(void *,unsigned,bool,bool);
struct rf_keys_state {
    uint64_t epoch,last_sample,changed_at[RF_KEYS_COUNT];
    uint8_t sampled,candidate,armed,down;
};

static inline unsigned rf_keys_release(struct rf_keys_state *state,unsigned mask,
    rf_keys_emit emit,void *context)
{
    unsigned released=state->down&mask;
    for(unsigned key=0;key<RF_KEYS_COUNT;++key)
        if((released&(1u<<key))&&emit)emit(context,key,false,false);
    state->sampled&=(uint8_t)~mask;state->candidate&=(uint8_t)~mask;
    state->armed&=(uint8_t)~mask;state->down&=(uint8_t)~mask;
    return released;
}

/* epoch identifies the current native HID consumer, zero means absent.
 * A held-at-boot/reconnect key is ignored until a stable real release. Failed
 * inputs release only their own delivered keys and must be re-armed too. */
static inline unsigned rf_keys_sample(struct rf_keys_state *state,uint64_t now,
    uint64_t epoch,unsigned pressed,unsigned valid,rf_keys_emit emit,void *context)
{
    if(!state)return 0;
    unsigned changed=0;
    if(!epoch||state->epoch!=epoch||now<state->last_sample||
        (pressed&~RF_KEYS_MASK)||(valid&~RF_KEYS_MASK)) {
        changed=rf_keys_release(state,RF_KEYS_MASK,emit,context);
        memset(state,0,sizeof(*state));state->epoch=epoch;state->last_sample=now;
        if(!epoch||(pressed&~RF_KEYS_MASK)||(valid&~RF_KEYS_MASK))return changed;
    }
    state->last_sample=now;
    changed|=rf_keys_release(state,RF_KEYS_MASK&~valid,emit,context);
    for(unsigned key=0;key<RF_KEYS_COUNT;++key) {
        unsigned bit=1u<<key;
        if(!(valid&bit))continue;
        bool down=(pressed&bit)!=0;
        if(!(state->sampled&bit)||down!=((state->candidate&bit)!=0)) {
            state->sampled|=(uint8_t)bit;
            state->candidate=(uint8_t)((state->candidate&~bit)|(down?bit:0));
            state->changed_at[key]=now;continue;
        }
        if(now-state->changed_at[key]<RF_KEYS_DEBOUNCE_NS)continue;
        if(!(state->armed&bit)) {
            if(!down)state->armed|=(uint8_t)bit;
            continue;
        }
        if(down==((state->down&bit)!=0))continue;
        state->down=(uint8_t)((state->down&~bit)|(down?bit:0));changed|=bit;
        if(emit)emit(context,key,down,true);
    }
    return changed;
}

/* Source-verified normal range: approximately2..500nits, DBV4..1023.
 * HBM requires the panel's separate thermal/entry policy and is not silently
 * inferred from an excessive normal-brightness request. Values are16.16nits. */
#define RF_PANEL_NORMAL_NITS 500u
#define RF_PANEL_DBV_MIN 4u
#define RF_PANEL_DBV_MAX 1023u
static inline bool rf_panel_nits_to_dbv(uint64_t nits,uint32_t *level)
{
    if(!level||nits>((uint64_t)RF_PANEL_NORMAL_NITS<<16))return false;
    uint64_t raw=(nits*RF_PANEL_DBV_MAX+((uint64_t)RF_PANEL_NORMAL_NITS<<15))/
        ((uint64_t)RF_PANEL_NORMAL_NITS<<16);
    *level=(uint32_t)(raw<RF_PANEL_DBV_MIN?RF_PANEL_DBV_MIN:raw);
    return true;
}
#endif
