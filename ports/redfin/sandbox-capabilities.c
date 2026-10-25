/* SPDX-License-Identifier: MIT
 * Opaque HMAC-authenticated capabilities for native Sandbox issue/consume/
 * release. Only the kernel's real TCC manager may issue one. Tokens preserve
 * class/resource/uid/process scope and remain valid for this boot; active
 * references have actual generation-bound handles and process-exit cleanup.
 * No permission/profile/entitlement answer is manufactured by this transport.
 */
#include "sandbox-capabilities.h"
#include <string.h>
#if defined(KERNEL)
#include <sys/errno.h>
#else
#include <errno.h>
#endif
#define HEADER 68u
#define PAYLOAD_MAX (HEADER+RF_SBX_CLASS_BYTES-1+RF_SBX_PATH_BYTES-1+32)
_Static_assert(4*((PAYLOAD_MAX+2)/3)+7<=RF_SBX_TOKEN_BYTES,"native token output bound");
static int operations(const struct rf_sbx_ops *o)
{return o&&o->random&&o->mac&&o->lock&&o->unlock;}
static int actor(const struct rf_sbx_actor *p){return p&&p->pid&&p->version;}
static int equal(const uint8_t *a,const uint8_t *b,unsigned n)
{unsigned diff=0;for(unsigned i=0;i<n;++i)diff|=a[i]^b[i];return !diff;}
static int terminated(const char *s,unsigned max)
{
    if(!s)return -1;
    for(unsigned i=0;i<max;++i){if(!s[i])return (int)i;if((uint8_t)s[i]<32||(uint8_t)s[i]>126)return -1;}
    return -1;
}
static int prefix(const char *s,const char *p){return !strncmp(s,p,strlen(p));}
static int path_valid(const char *s)
{
    int n=terminated(s,RF_SBX_PATH_BYTES);
    if(n<1||s[0]!='/')return 0;
    const char *root=prefix(s,"/private/var/mobile/Media")?"/private/var/mobile/Media":
        prefix(s,"/var/mobile/Media")?"/var/mobile/Media":NULL;
    if(!root)return 0;
    size_t r=strlen(root);if(s[r]&&s[r]!='/')return 0;
    for(int i=0;i<n;) {
        int start=++i;while(i<n&&s[i]!='/')++i;int count=i-start;
        if(!count||(count==1&&s[start]=='.')||(count==2&&s[start]=='.'&&s[start+1]=='.'))return 0;
    }
    return 1;
}
static int request_valid(const struct rf_sbx_request *q)
{
    if(!q||terminated(q->class_name,RF_SBX_CLASS_BYTES)<1||terminated(q->resource,RF_SBX_PATH_BYTES)<0||
       (q->flags&~(RF_SBX_TARGET_PID|RF_SBX_TARGET_VERSION))||
       ((q->flags&RF_SBX_TARGET_VERSION)&&!(q->flags&RF_SBX_TARGET_PID))||
       (!!(q->flags&RF_SBX_TARGET_PID)!=!!q->target_pid)||
       (!!(q->flags&RF_SBX_TARGET_VERSION)!=!!q->target_version))return EINVAL;
    bool tcc=prefix(q->class_name,"com.apple.tcc.")&&q->class_name[14];
    if(q->kind==3)return tcc&&!q->resource[0]?0:EACCES;
    if(q->kind==0) {
        /* This installed TCCD uses issue_file(TCC-class,"/",0) when the
         * service does not use its generic variant. The service class still
         * scopes the capability; it is not an app-sandbox root-file grant. */
        if(tcc&&!strcmp(q->resource,"/"))return 0;
        bool access=tcc||!strcmp(q->class_name,"com.apple.app-sandbox.read")||!strcmp(q->class_name,"com.apple.app-sandbox.read-write");
        return access&&path_valid(q->resource)?0:EACCES;
    }
    return ENOTSUP;
}
static void put32(uint8_t *p,uint32_t n){for(unsigned i=0;i<4;++i)p[i]=(uint8_t)(n>>(8*i));}
static uint32_t get32(const uint8_t *p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static void put16(uint8_t *p,unsigned n){p[0]=(uint8_t)n;p[1]=(uint8_t)(n>>8);}
static unsigned get16(const uint8_t *p){return (unsigned)p[0]|(unsigned)p[1]<<8;}
static const char alphabet[]="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
static void encode(const uint8_t *raw,unsigned bytes,char out[RF_SBX_TOKEN_BYTES])
{
    memcpy(out,"rfsb1:",6);unsigned n=6;
    for(unsigned i=0;i<bytes;i+=3) {
        unsigned left=bytes-i,v=(unsigned)raw[i]<<16;
        if(left>1)v|=(unsigned)raw[i+1]<<8;
        if(left>2)v|=raw[i+2];
        out[n++]=alphabet[(v>>18)&63];out[n++]=alphabet[(v>>12)&63];
        out[n++]=left>1?alphabet[(v>>6)&63]:'=';out[n++]=left>2?alphabet[v&63]:'=';
    }
    out[n]=0;
}
static int base64_value(unsigned c)
{
    if(c>='A'&&c<='Z')return (int)c-'A';
    if(c>='a'&&c<='z')return (int)c-'a'+26;
    if(c>='0'&&c<='9')return (int)c-'0'+52;
    if(c=='-')return 62;
    if(c=='_')return 63;
    return -1;
}
static int decode(const char *token,size_t bytes,uint8_t raw[PAYLOAD_MAX],unsigned *length)
{
    if(!token||bytes<7||bytes>RF_SBX_TOKEN_BYTES||memcmp(token,"rfsb1:",6)||token[bytes-1]||(bytes-7)%4)return EINVAL;
    unsigned n=0;
    for(size_t i=6;i<bytes-1;i+=4) {
        int a=base64_value((uint8_t)token[i]),b=base64_value((uint8_t)token[i+1]);
        int c=token[i+2]=='='?0:base64_value((uint8_t)token[i+2]),d=token[i+3]=='='?0:base64_value((uint8_t)token[i+3]);
        unsigned pad=token[i+2]=='='?2:token[i+3]=='='?1:0;
        if(a<0||b<0||c<0||d<0||(pad&&(i+4!=bytes-1||token[i+3]!='='))||
            (pad==2&&(b&15))||(pad==1&&(c&3))||n+3-pad>PAYLOAD_MAX)return EINVAL;
        unsigned v=(unsigned)a<<18|(unsigned)b<<12|(unsigned)c<<6|(unsigned)d;
        raw[n++]=(uint8_t)(v>>16);if(pad<2)raw[n++]=(uint8_t)(v>>8);if(!pad)raw[n++]=(uint8_t)v;
    }
    if(n<HEADER+33)return EINVAL;
    *length=n;return 0;
}
static int payload_request(const uint8_t *raw,unsigned bytes,struct rf_sbx_request *q,uint32_t *uid)
{
    if(bytes<HEADER+33||memcmp(raw,"RFSBX01\0",8)||get32(raw+28))return EINVAL;
    unsigned cn=get16(raw+64),rn=get16(raw+66);
    if(!cn||cn>=RF_SBX_CLASS_BYTES||rn>=RF_SBX_PATH_BYTES||bytes!=HEADER+cn+rn+32)return EINVAL;
    memset(q,0,sizeof(*q));q->kind=get32(raw+8);q->flags=get32(raw+12);*uid=get32(raw+16);
    q->target_pid=get32(raw+20);q->target_version=get32(raw+24);
    memcpy(q->class_name,raw+HEADER,cn);memcpy(q->resource,raw+HEADER+cn,rn);
    /* Embedded NULs cannot change the authenticated string's meaning. */
    if(terminated(q->class_name,sizeof(q->class_name))!=(int)cn||terminated(q->resource,sizeof(q->resource))!=(int)rn)return EINVAL;
    return request_valid(q);
}
static int find(struct rf_sbx_registry *r,const uint8_t tag[32])
{
    int found=-1;
    for(unsigned i=0;i<RF_SBX_ENTRIES;++i)if(r->entry[i].used&&equal(r->entry[i].tag,tag,32))found=(int)i;
    return found;
}
int rf_sbx_issue(struct rf_sbx_registry *r,const struct rf_sbx_ops *o,const struct rf_sbx_actor *p,
    const struct rf_sbx_request *q,char token[RF_SBX_TOKEN_BYTES])
{
    if(!r||!operations(o)||!actor(p)||!token)return EINVAL;
    if(!p->issuer)return EACCES;
    int error=request_valid(q);if(error)return error;
    unsigned cn=(unsigned)strlen(q->class_name),rn=(unsigned)strlen(q->resource),bytes=HEADER+cn+rn;
    uint8_t raw[PAYLOAD_MAX]={0};memcpy(raw,"RFSBX01\0",8);put32(raw+8,q->kind);put32(raw+12,q->flags);
    put32(raw+16,p->uid);put32(raw+20,q->target_pid);put32(raw+24,q->target_version);put16(raw+64,cn);put16(raw+66,rn);
    if(o->random(o->context,raw+32,32))return EIO;
    memcpy(raw+HEADER,q->class_name,cn);memcpy(raw+HEADER+cn,q->resource,rn);
    if(o->mac(o->context,raw,bytes,raw+bytes))error=EIO;
    if(!error)encode(raw,bytes+32,token);
    memset(raw,0,sizeof(raw));return error;
}
int rf_sbx_consume(struct rf_sbx_registry *r,const struct rf_sbx_ops *o,const struct rf_sbx_actor *p,
    const char *token,size_t bytes,uint64_t *handle)
{
    if(!r||!operations(o)||!actor(p)||!handle)return EINVAL;
    uint8_t raw[PAYLOAD_MAX],tag[32];unsigned length=0;int error=decode(token,bytes,raw,&length);if(error)return error;
    if(o->mac(o->context,raw,length-32,tag)||!equal(tag,raw+length-32,32)){memset(raw,0,sizeof(raw));return EACCES;}
    struct rf_sbx_request q;uint32_t uid=0;error=payload_request(raw,length,&q,&uid);memset(raw,0,sizeof(raw));if(error)return error;
    if((q.flags&RF_SBX_TARGET_PID)?q.target_pid!=p->pid||((q.flags&RF_SBX_TARGET_VERSION)&&q.target_version!=p->version):uid!=p->uid)return EACCES;
    uint64_t value=0;if(o->random(o->context,(uint8_t *)&value,sizeof(value)))return EIO;
    value&=UINT64_C(0x7fffffffffffffff);if(!value)return EIO;
    o->lock(o->context);int index=find(r,tag),entry=-1,slot=-1;
    for(unsigned i=0;i<RF_SBX_ENTRIES;++i)if(!r->entry[i].used){entry=(int)i;break;}
    for(unsigned i=0;i<RF_SBX_HANDLES;++i) {
        if(r->handle[i].value==value){error=EAGAIN;break;}
        if(!r->handle[i].value&&slot<0)slot=(int)i;
    }
    if(!error&&(slot<0||(index<0&&(entry<0||r->generation==UINT64_MAX))))error=ENOSPC;
    if(!error&&index<0) {
        index=entry;struct rf_sbx_entry *e=&r->entry[index];memset(e,0,sizeof(*e));
        e->used=1;e->generation=++r->generation;e->issuer_uid=uid;e->kind=q.kind;e->flags=q.flags;
        e->target_pid=q.target_pid;e->target_version=q.target_version;
        memcpy(e->tag,tag,32);memcpy(e->class_name,q.class_name,sizeof(e->class_name));memcpy(e->resource,q.resource,sizeof(e->resource));
    }
    if(!error) {
        struct rf_sbx_entry *e=&r->entry[index];
        if(e->references==UINT32_MAX)error=ENOSPC;
        else {struct rf_sbx_handle *h=&r->handle[slot];h->value=value;h->generation=e->generation;h->entry=(uint32_t)index;
            h->pid=p->pid;h->version=p->version;++e->references;*handle=value;}
    }
    o->unlock(o->context);memset(tag,0,sizeof(tag));memset(&q,0,sizeof(q));return error;
}
static void drop(struct rf_sbx_registry *r,struct rf_sbx_handle *h)
{
    if(h->entry<RF_SBX_ENTRIES) {
        struct rf_sbx_entry *e=&r->entry[h->entry];
        if(e->used&&e->generation==h->generation&&e->references) {
            --e->references;if(!e->references)memset(e,0,sizeof(*e));
        }
    }
    memset(h,0,sizeof(*h));
}
int rf_sbx_release(struct rf_sbx_registry *r,const struct rf_sbx_ops *o,const struct rf_sbx_actor *p,uint64_t handle)
{
    if(!r||!operations(o)||!actor(p)||!handle)return EINVAL;
    int error=ENOENT;o->lock(o->context);
    for(unsigned i=0;i<RF_SBX_HANDLES;++i)if(r->handle[i].value==handle) {
        if(r->handle[i].pid!=p->pid||r->handle[i].version!=p->version)error=EACCES;
        else {drop(r,&r->handle[i]);error=0;}break;
    }
    o->unlock(o->context);return error;
}
void rf_sbx_exit(struct rf_sbx_registry *r,const struct rf_sbx_ops *o,const struct rf_sbx_actor *p)
{
    if(!r||!operations(o)||!actor(p))return;
    o->lock(o->context);
    for(unsigned i=0;i<RF_SBX_HANDLES;++i)if(r->handle[i].value&&r->handle[i].pid==p->pid&&r->handle[i].version==p->version)drop(r,&r->handle[i]);
    o->unlock(o->context);
}
