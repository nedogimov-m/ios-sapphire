/* SPDX-License-Identifier: MIT
 * The boot ADT stays pinned for this firmware epoch. Cache its traversal,
 * never its property values: every guard still rereads and compares the
 * original bytes. Only the serialized owner can populate/use these slots.
 * A missing/oversized/full-cache entry uses the original native lookup.
 */
static thread_t fw_dt_owner;
static struct {char path[96];DTEntry node;} fw_dt_nodes[32];
static struct {DTEntry node;char key[64];const void *value;unsigned bytes;} fw_dt_values[128];
static uint64_t fw_dt_hits,fw_dt_misses;

static bool fw_dt_owned(void)
{
    thread_t owner=__atomic_load_n(&fw_dt_owner,__ATOMIC_ACQUIRE);
    return owner && owner==current_thread();
}
static inline void fw_dt_begin(void)
{
    memset(fw_dt_nodes,0,sizeof(fw_dt_nodes));memset(fw_dt_values,0,sizeof(fw_dt_values));
    fw_dt_hits=fw_dt_misses=0;
    __atomic_store_n(&fw_dt_owner,current_thread(),__ATOMIC_RELEASE);
}
static int fw_dt_lookup(const char *path,DTEntry *out)
{
    if(!fw_dt_owned() || !path || !out || strlen(path)>=sizeof(fw_dt_nodes[0].path))
        return SecureDTLookupEntry(NULL,path,out);
    unsigned free_slot=32;
    for(unsigned i=0;i<32;i++) {
        if(fw_dt_nodes[i].node && !strcmp(path,fw_dt_nodes[i].path)) {
            *out=fw_dt_nodes[i].node;fw_dt_hits++;return kSuccess;
        }
        if(!fw_dt_nodes[i].node && free_slot==32)free_slot=i;
    }
    fw_dt_misses++;int result=SecureDTLookupEntry(NULL,path,out);
    if(result==kSuccess && *out && free_slot<32) {
        memcpy(fw_dt_nodes[free_slot].path,path,strlen(path)+1);
        fw_dt_nodes[free_slot].node=*out;
    }
    return result;
}
static int fw_dt_property(DTEntry node,const char *key,const void **value,unsigned *bytes)
{
    if(!fw_dt_owned() || !node || !key || !value || !bytes || strlen(key)>=sizeof(fw_dt_values[0].key))
        return SecureDTGetProperty(node,key,value,bytes);
    uint32_t hash=(uint32_t)((uintptr_t)node>>3);
    for(const char *p=key;*p;p++)hash=(hash^(unsigned char)*p)*16777619u;
    unsigned free_slot=128;
    for(unsigned i=0;i<128;i++) {
        unsigned at=(hash+i)&127u;
        if(!fw_dt_values[at].node){free_slot=at;break;}
        if(node==fw_dt_values[at].node && !strcmp(key,fw_dt_values[at].key)) {
            *value=fw_dt_values[at].value;*bytes=fw_dt_values[at].bytes;fw_dt_hits++;return kSuccess;
        }
    }
    fw_dt_misses++;int result=SecureDTGetProperty(node,key,value,bytes);
    if(result==kSuccess && *value && free_slot<128) {
        fw_dt_values[free_slot].node=node;
        memcpy(fw_dt_values[free_slot].key,key,strlen(key)+1);
        fw_dt_values[free_slot].value=*value;fw_dt_values[free_slot].bytes=*bytes;
    }
    return result;
}
