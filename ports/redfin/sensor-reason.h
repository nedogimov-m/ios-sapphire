/* SPDX-License-Identifier: MIT */
/* Readonly native global SMEM423/ADSP subsystem failure reason. Google msm
 * 500b3a2059c1ee subsys-pil-tz.c and Redfin's qcom,smem-id binding. Include
 * after wifi_smem.h. No scan of arbitrary RAM, fault clear or restart. */
#ifndef REDFIN_SENSOR_REASON_H
#define REDFIN_SENSOR_REASON_H
#include <sys/errno.h>
#include <string.h>
#define RF_SENSOR_REASON_BYTES 256u
static inline int rf_sensor_reason(const volatile uint8_t *data,size_t bytes,
    char out[RF_SENSOR_REASON_BYTES])
{
    if(!data||bytes!=REDFIN_SMEM_BYTES||!out)return EINVAL;
    struct redfin_smem_report validated;
    if(redfin_smem_inspect_host(data,bytes,2,&validated)!=REDFIN_SMEM_OK)return EAGAIN;
    uint32_t toc=REDFIN_SMEM_BYTES-0x1000,offset=0,length=0,count=0;
    for(unsigned i=0;i<validated.partitions;++i) {
        const volatile uint8_t *entry=data+toc+32+48*i;
        if(redfin_smem_u32(entry+12)!=0xfffefffeu)continue;
        if(++count!=1)return EINVAL;
        offset=redfin_smem_u32(entry);length=redfin_smem_u32(entry+4);
    }
    if(!count)return ENOENT;
    if(offset<0x1000||length<32||offset>toc||length>toc-offset)return EINVAL;
    const volatile uint8_t *part=data+offset;
    uint32_t free_u=redfin_smem_u32(part+12),free_c=redfin_smem_u32(part+16);
    if(redfin_smem_u32(part)!=0x54525024u||redfin_smem_u32(part+4)!=0xfffefffeu||
        redfin_smem_u32(part+8)!=length||free_u<32||free_u>free_c||free_c>length)return EINVAL;
    uint32_t found=0,payload=0,available=0,items=0;
    for(uint32_t cursor=32;cursor<free_u;) {
        if(++items>REDFIN_SMEM_MAX_ITEMS||free_u-cursor<16)return EINVAL;
        const volatile uint8_t *entry=part+cursor;
        uint32_t size=redfin_smem_u32(entry+4),padding=redfin_smem_u16(entry+8),header=redfin_smem_u16(entry+10);
        if(redfin_smem_u16(entry)!=0xa5a5||!size||padding>=size||header>free_u-cursor-16||size>free_u-cursor-16-header)return EINVAL;
        if(redfin_smem_u16(entry+2)==423) {
            if(++found!=1)return EINVAL;
            payload=offset+cursor+16+header;available=size-padding;
        }
        cursor+=16+header+size;
    }
    if(!found)return ENOENT;
    uint8_t first[RF_SENSOR_REASON_BYTES],second[RF_SENSOR_REASON_BYTES];
    unsigned take=available<RF_SENSOR_REASON_BYTES-1?available:RF_SENSOR_REASON_BYTES-1;
    for(unsigned i=0;i<take;++i)first[i]=data[payload+i];
    for(unsigned i=0;i<take;++i)second[i]=data[payload+i];
    if(memcmp(first,second,take)||redfin_smem_u32(part+12)!=free_u||redfin_smem_u32(part+16)!=free_c||
        redfin_smem_u32(data+toc+8)!=validated.partitions)return EAGAIN;
    if(!take||!first[0])return ENOENT;
    unsigned n=0;
    while(n<take&&first[n]) {uint8_t c=first[n];out[n]=(c>=32&&c<=126)?(char)c:' ';++n;}
    out[n]=0;return 0;
}
#endif
