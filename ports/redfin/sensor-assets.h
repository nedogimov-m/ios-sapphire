/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_SENSOR_ASSETS_H
#define REDFIN_SENSOR_ASSETS_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#define RF_SENSOR_BASE UINT64_C(0x89200000)
#define RF_SENSOR_MEMORY 0x02800000u
#define RF_SENSOR_ASSETS_MAX 512u
struct rf_sensor_asset {char name[80];const uint8_t *data;uint32_t bytes;};
struct rf_sensor_assets {uint32_t count;struct rf_sensor_asset file[RF_SENSOR_ASSETS_MAX];};
typedef int (*rf_sensor_sha_fn)(void *,const uint8_t *,size_t,uint8_t[32]);
static inline uint32_t rf_sa32(const uint8_t *p)
{return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static inline uint64_t rf_sa64(const uint8_t *p){return rf_sa32(p)|(uint64_t)rf_sa32(p+4)<<32;}
static inline int rf_sensor_assets_open(struct rf_sensor_assets *out,const uint8_t *data,size_t bytes,
    const uint8_t expected[32],rf_sensor_sha_fn sha,void *context)
{
    if(!out||!data||!expected||!sha||bytes<64||bytes>32u*1024u*1024u)return -1;
    out->count=0;uint8_t digest[32];
    if(sha(context,data,bytes,digest)||memcmp(digest,expected,32)||memcmp(data,"RFSSC01\0",8)||
        rf_sa32(data+8)!=1||rf_sa64(data+16)!=bytes)return -1;
    for(unsigned i=24;i<64;++i)if(data[i])return -1;
    unsigned count=rf_sa32(data+12);if(!count||count>RF_SENSOR_ASSETS_MAX||64+count*128>bytes)return -1;
    uint64_t cursor=64+count*128;
    for(unsigned i=0;i<count;++i) {
        const uint8_t *r=data+64+i*128;unsigned name=0;
        while(name<80&&r[name]) {
            unsigned c=r[name++];
            if(c=='.'&&name>=2&&r[name-2]=='.')return -1;
            if(!((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='/'||c=='_'||c=='.'||c=='-'))return -1;
        }
        if(!name||name>=80||r[0]=='/')return -1;
        for(unsigned j=name;j<80;++j)if(r[j])return -1;
        uint64_t at=rf_sa64(r+80),n=rf_sa64(r+88);
        if(at!=cursor||!n||n>16u*1024u*1024u||at>bytes||n>bytes-at)return -1;
        for(unsigned j=0;j<i;++j)if(!memcmp(out->file[j].name,r,80))return -1;
        if(sha(context,data+at,(size_t)n,digest)||memcmp(digest,r+96,32))return -1;
        memcpy(out->file[i].name,r,80);out->file[i].data=data+at;out->file[i].bytes=(uint32_t)n;
        cursor=(at+n+15)&~UINT64_C(15);if(cursor>bytes)return -1;
        for(uint64_t j=at+n;j<cursor;++j)if(data[j])return -1;
    }
    if(cursor!=bytes)return -1;
    out->count=count;return 0;
}
static inline const struct rf_sensor_asset *rf_sensor_asset_find(const struct rf_sensor_assets *s,const char *name)
{
    if(!s||!name||s->count>RF_SENSOR_ASSETS_MAX)return NULL;
    for(unsigned i=0;i<s->count;++i)if(!strcmp(s->file[i].name,name))return &s->file[i];
    return NULL;
}
struct rf_sensor_segment {uint32_t physical,bytes,memory;const uint8_t *data;};
struct rf_sensor_image {const uint8_t *metadata;uint32_t metadata_bytes,count;struct rf_sensor_segment segment[64];};
static inline int rf_sensor_image_open(struct rf_sensor_image *image,const struct rf_sensor_assets *assets)
{
    if(!image)return -1;
    const struct rf_sensor_asset *a=rf_sensor_asset_find(assets,"fw/adsp.mdt");
    if(!a||a->bytes<52||a->bytes>16384||memcmp(a->data,"\x7f" "ELF\1\1\1",7)||
       rf_sa32(a->data+28)!=52||a->data[40]!=52||a->data[41]||a->data[42]!=32||a->data[43])return -1;
    unsigned ph=a->data[44]|(unsigned)a->data[45]<<8;
    if(ph<2||ph>64||52+ph*32>a->bytes)return -1;
    image->metadata=a->data;image->metadata_bytes=a->bytes;image->count=0;
    uint32_t lowest=UINT32_MAX,highest=0;
    for(unsigned i=0;i<ph;++i) {
        const uint8_t *p=a->data+52+i*32;
        uint32_t pa=rf_sa32(p+12),n=rf_sa32(p+16),memory=rf_sa32(p+20),flags=rf_sa32(p+24);
        if(rf_sa32(p)!=1||(flags&0x7000000)==0x2000000||!memory)continue;
        if(pa<RF_SENSOR_BASE||pa>=RF_SENSOR_BASE+RF_SENSOR_MEMORY||memory>RF_SENSOR_BASE+RF_SENSOR_MEMORY-pa||n>memory)return -1;
        for(unsigned j=0;j<image->count;++j)if(pa<image->segment[j].physical+image->segment[j].memory&&
            image->segment[j].physical<pa+memory)return -1;
        const struct rf_sensor_asset *part=NULL;
        if(n) {
            char name[12]="fw/adsp.b00";name[9]=(char)('0'+i/10);name[10]=(char)('0'+i%10);
            part=rf_sensor_asset_find(assets,name);if(!part||part->bytes!=n)return -1;
        }
        struct rf_sensor_segment *s=&image->segment[image->count++];
        s->physical=pa;s->bytes=n;s->memory=memory;s->data=part?part->data:NULL;
        if(pa<lowest)lowest=pa;if(pa+memory>highest)highest=pa+memory;
    }
    return !image->count||lowest!=RF_SENSOR_BASE||highest!=RF_SENSOR_BASE+RF_SENSOR_MEMORY?-1:0;
}
#endif
