/* SPDX-License-Identifier: MIT */
#include "ssc-protocol.h"
#include <string.h>

static uint32_t le32(const uint8_t *p)
{return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static uint64_t le64(const uint8_t *p)
{return le32(p)|(uint64_t)le32(p+4)<<32;}
static uint16_t le16(const uint8_t *p)
{return (uint16_t)p[0]|(uint16_t)p[1]<<8;}
static void put16(uint8_t *p,uint16_t n){p[0]=(uint8_t)n;p[1]=(uint8_t)(n>>8);}
static void put32(uint8_t *p,uint32_t n)
{for(unsigned i=0;i<4;++i)p[i]=(uint8_t)(n>>(8*i));}
static void put64(uint8_t *p,uint64_t n)
{for(unsigned i=0;i<8;++i)p[i]=(uint8_t)(n>>(8*i));}
static int varint(struct rf_sns_pb *p,uint64_t *out)
{
    uint64_t v=0;
    for(unsigned i=0;i<10;++i) {
        if(p->offset>=p->input.bytes)return -RF_SNS_TRUNCATED;
        unsigned b=p->input.data[p->offset++];
        if(i==9 && (b&0xfe))return -RF_SNS_RANGE;
        v|=(uint64_t)(b&127)<<(7*i);
        if(!(b&128)){*out=v;return 0;}
    }
    return -RF_SNS_FORMAT;
}
int rf_sns_next(struct rf_sns_pb *p,struct rf_sns_field *f)
{
    if(!p||!f||!p->input.data||p->input.bytes>RF_SNS_REPORT_MAX||p->offset>p->input.bytes)
        return -RF_SNS_ARGUMENT;
    if(p->offset==p->input.bytes)return 0;
    if(++p->fields>8192)return -RF_SNS_LIMIT;
    uint64_t key=0;int error=varint(p,&key);if(error)return error;
    if(!(key>>3)||key>>3>0x1fffffff)return -RF_SNS_FORMAT;
    memset(f,0,sizeof(*f));f->number=(uint32_t)(key>>3);f->wire=(uint32_t)(key&7);
    if(!f->wire){error=varint(p,&f->scalar);return error?error:1;}
    uint64_t bytes=0;
    if(f->wire==1)bytes=8;
    else if(f->wire==5)bytes=4;
    else if(f->wire==2){error=varint(p,&bytes);if(error)return error;}
    else return -RF_SNS_FORMAT; /* Deprecated groups have no SSC use. */
    if(bytes>p->input.bytes-p->offset)return -RF_SNS_TRUNCATED;
    f->data=(struct rf_sns_slice){p->input.data+p->offset,(uint32_t)bytes};
    if(f->wire==1)f->scalar=le64(f->data.data);
    if(f->wire==5)f->scalar=le32(f->data.data);
    p->offset+=(uint32_t)bytes;return 1;
}
int rf_sns_suid_decode(struct rf_sns_slice input,struct rf_sns_suid *out)
{
    if(!out)return RF_SNS_ARGUMENT;
    struct rf_sns_suid v={0};struct rf_sns_pb p={input,0,0};struct rf_sns_field f;
    unsigned seen=0;int next;
    while((next=rf_sns_next(&p,&f))>0) {
        if(f.number!=1&&f.number!=2)continue;
        unsigned bit=1u<<(f.number-1);
        if(f.wire!=1||(seen&bit))return RF_SNS_FORMAT;
        seen|=bit;if(f.number==1)v.low=f.scalar;else v.high=f.scalar;
    }
    if(next<0)return -next;
    if(seen!=3||!(v.low|v.high))return RF_SNS_FORMAT;
    *out=v;return 0;
}
int rf_sns_lookup_decode(struct rf_sns_slice input,struct rf_sns_slice *datatype,
    struct rf_sns_suid *uids,uint32_t capacity,uint32_t *count)
{
    if(!datatype||!uids||!count||!capacity||capacity>64)return RF_SNS_ARGUMENT;
    struct rf_sns_pb p={input,0,0};struct rf_sns_field f;unsigned found=0,n=0;int next;
    struct rf_sns_slice type={0};
    /* Validate before exposing any discovered sensor to the caller. */
    while((next=rf_sns_next(&p,&f))>0) {
        if(f.number==1) {
            if(found||f.wire!=2||!f.data.bytes||f.data.bytes>64)return RF_SNS_FORMAT;
            for(unsigned i=0;i<f.data.bytes;++i)
                if(f.data.data[i]<32||f.data.data[i]>126)return RF_SNS_FORMAT;
            found=1;type=f.data;
        } else if(f.number==2) {
            struct rf_sns_suid uid;
            if(f.wire!=2)return RF_SNS_FORMAT;
            int error=rf_sns_suid_decode(f.data,&uid);if(error)return error;
            if(++n>capacity)return RF_SNS_LIMIT;
        }
    }
    if(next<0)return -next;
    if(!found)return RF_SNS_FORMAT;
    p=(struct rf_sns_pb){input,0,0};n=0;
    while(rf_sns_next(&p,&f)>0)if(f.number==2) {
        struct rf_sns_suid uid;int error=rf_sns_suid_decode(f.data,&uid);if(error)return error;
        for(unsigned i=0;i<n;++i)if(uids[i].low==uid.low&&uids[i].high==uid.high)return RF_SNS_FORMAT;
        uids[n++]=uid;
    }
    *datatype=type;*count=n;return 0;
}
static int event_decode(struct rf_sns_slice input,struct rf_sns_event *event)
{
    struct rf_sns_pb p={input,0,0};struct rf_sns_field f;
    struct rf_sns_event v={0};unsigned seen=0;int next;
    while((next=rf_sns_next(&p,&f))>0) {
        if(f.number>3)continue;
        unsigned bit=1u<<(f.number-1);if(seen&bit)return RF_SNS_FORMAT;
        seen|=bit;
        if(f.number==1){if(f.wire!=5||!f.scalar||f.scalar>4095)return RF_SNS_FORMAT;v.id=(uint32_t)f.scalar;}
        else if(f.number==2){if(f.wire!=1)return RF_SNS_FORMAT;v.ticks=f.scalar;}
        else {if(f.wire!=2)return RF_SNS_FORMAT;v.payload=f.data;}
    }
    if(next<0)return -next;
    if(seen!=7)return RF_SNS_FORMAT;
    *event=v;return 0;
}
int rf_sns_events(struct rf_sns_slice input,rf_sns_event_fn callback,void *context)
{
    if(!callback)return RF_SNS_ARGUMENT;
    struct rf_sns_pb p={input,0,0};struct rf_sns_field f;
    struct rf_sns_suid uid={0};unsigned seen=0,events=0;int next;
    while((next=rf_sns_next(&p,&f))>0) {
        if(f.number==1) {
            if(seen||f.wire!=2)return RF_SNS_FORMAT;
            int error=rf_sns_suid_decode(f.data,&uid);if(error)return error;seen=1;
        } else if(f.number==2) {
            struct rf_sns_event event;
            if(f.wire!=2)return RF_SNS_FORMAT;
            int error=event_decode(f.data,&event);if(error)return error;
            if(++events>RF_SNS_EVENT_MAX)return RF_SNS_LIMIT;
        }
    }
    if(next<0)return -next;
    if(!seen)return RF_SNS_FORMAT;
    p=(struct rf_sns_pb){input,0,0};
    while(rf_sns_next(&p,&f)>0)if(f.number==2) {
        struct rf_sns_event event;int error=event_decode(f.data,&event);if(error)return error;
        if(callback(context,&uid,&event))return RF_SNS_CALLBACK;
    }
    return 0;
}
static int attribute_decode(struct rf_sns_slice input,struct rf_sns_attribute *out)
{
    struct rf_sns_pb p={input,0,0};struct rf_sns_field f;struct rf_sns_attribute v={0};unsigned seen=0;int next;
    while((next=rf_sns_next(&p,&f))>0) {
        if(f.number>2)continue;
        unsigned bit=1u<<(f.number-1);if(seen&bit)return RF_SNS_FORMAT;seen|=bit;
        if(f.number==1){if(f.wire||f.scalar>INT32_MAX)return RF_SNS_RANGE;v.id=(uint32_t)f.scalar;}
        else {if(f.wire!=2)return RF_SNS_FORMAT;v.value=f.data;}
    }
    if(next<0)return -next;
    if(seen!=3)return RF_SNS_FORMAT;
    *out=v;return 0;
}
int rf_sns_attributes(struct rf_sns_slice input,rf_sns_attribute_fn callback,void *context)
{
    if(!callback)return RF_SNS_ARGUMENT;
    struct rf_sns_pb p={input,0,0};struct rf_sns_field f;unsigned count=0;int next;
    while((next=rf_sns_next(&p,&f))>0)if(f.number==1) {
        struct rf_sns_attribute value;if(f.wire!=2)return RF_SNS_FORMAT;
        int error=attribute_decode(f.data,&value);if(error)return error;
        if(++count>256)return RF_SNS_LIMIT;
    }
    if(next<0)return -next;
    p=(struct rf_sns_pb){input,0,0};
    while(rf_sns_next(&p,&f)>0)if(f.number==1) {
        struct rf_sns_attribute value;int error=attribute_decode(f.data,&value);if(error)return error;
        if(callback(context,&value))return RF_SNS_CALLBACK;
    }
    return 0;
}
static bool finite_float(uint32_t bits){return (bits&0x7f800000u)!=0x7f800000u;}
int rf_sns_sample_decode(struct rf_sns_slice input,struct rf_sns_sample *out)
{
    if(!out)return RF_SNS_ARGUMENT;
    struct rf_sns_sample v={0};struct rf_sns_pb p={input,0,0};struct rf_sns_field f;unsigned seen=0;int next;
    while((next=rf_sns_next(&p,&f))>0) {
        if(f.number==1) {
            if(f.wire!=5&&f.wire!=2)return RF_SNS_FORMAT;
            unsigned n=f.wire==5?1:f.data.bytes/4;
            if((f.wire==2&&f.data.bytes%4)||n>RF_SNS_VALUES_MAX-v.count)return RF_SNS_LIMIT;
            for(unsigned i=0;i<n;++i) {
                uint32_t bits=f.wire==5?(uint32_t)f.scalar:le32(f.data.data+i*4);
                if(!finite_float(bits))return RF_SNS_RANGE;
                v.bits[v.count++]=bits;
            }
        } else if(f.number==2) {
            if(seen||f.wire||f.scalar>3)return RF_SNS_FORMAT;
            seen=1;v.status=(uint32_t)f.scalar;
        }
    }
    if(next<0)return -next;
    if(!seen||!v.count)return RF_SNS_FORMAT;
    *out=v;return 0;
}
int rf_sns_proximity_decode(struct rf_sns_slice input,struct rf_sns_proximity *out)
{
    if(!out)return RF_SNS_ARGUMENT;
    struct rf_sns_proximity v={0};struct rf_sns_pb p={input,0,0};struct rf_sns_field f;unsigned seen=0;int next;
    while((next=rf_sns_next(&p,&f))>0) {
        if(f.number>3)continue;
        unsigned bit=1u<<(f.number-1);
        if((seen&bit)||f.wire||f.scalar>UINT32_MAX)return RF_SNS_FORMAT;
        seen|=bit;
        if(f.number==1){if(f.scalar>1)return RF_SNS_RANGE;v.near=(uint32_t)f.scalar;}
        else if(f.number==2)v.adc=(uint32_t)f.scalar;
        else {if(f.scalar>3)return RF_SNS_RANGE;v.status=(uint32_t)f.scalar;}
    }
    if(next<0)return -next;
    if(seen!=7)return RF_SNS_FORMAT;
    *out=v;return 0;
}
int rf_sns_float_fixed(uint32_t bits,uint32_t num,uint32_t den,int32_t *out)
{
    if(!out||!num||num>1000000||!den||den>1000000)return RF_SNS_ARGUMENT;
    if(!finite_float(bits))return RF_SNS_RANGE;
    uint64_t mantissa=bits&0x7fffffu;unsigned exponent=(bits>>23)&255;
    int shift=(exponent? (int)exponent:1)-134;
    if(exponent)mantissa|=0x800000u;
    uint64_t numerator=mantissa*num,denominator=den;
    if(shift>=0) {
        if(shift>40||numerator>(UINT64_MAX>>shift))return RF_SNS_RANGE;
        numerator<<=shift;
    } else {
        unsigned right=(unsigned)-shift;
        if(right>63||denominator>(UINT64_MAX>>right)){*out=0;return 0;}
        denominator<<=right;
    }
    uint64_t value=numerator/denominator,remainder=numerator%denominator;
    if(remainder>=denominator-remainder)++value;
    uint64_t limit=(bits>>31)?UINT64_C(2147483648):INT32_MAX;
    if(value>limit)return RF_SNS_RANGE;
    *out=(bits>>31)?(value==UINT64_C(2147483648)?INT32_MIN:-(int32_t)value):(int32_t)value;
    return 0;
}
struct writer {uint8_t *data;uint32_t bytes,at;int error;};
static void append(struct writer *w,const void *data,uint32_t bytes)
{
    if(w->error)return;
    if(bytes>w->bytes-w->at){w->error=RF_SNS_LIMIT;return;}
    if(bytes)memcpy(w->data+w->at,data,bytes);w->at+=bytes;
}
static void scalar(struct writer *w,uint64_t value)
{
    do{uint8_t b=(uint8_t)(value&127);value>>=7;if(value)b|=128;append(w,&b,1);}while(value&&!w->error);
}
static void field_bytes(struct writer *w,unsigned field,const void *data,unsigned bytes)
{scalar(w,field*8u+2u);scalar(w,bytes);append(w,data,bytes);}
int rf_sns_lookup_body(uint8_t *out,uint32_t capacity,const char *name,bool updates,bool default_only)
{
    if(!out||!name||capacity>RF_SNS_REQUEST_MAX)return -RF_SNS_ARGUMENT;
    unsigned bytes=0;while(bytes<64&&name[bytes]) {
        unsigned c=(uint8_t)name[bytes];
        if(!((c>='a'&&c<='z')||(c>='0'&&c<='9')||c=='_'))return -RF_SNS_ARGUMENT;
        ++bytes;
    }
    if(!bytes||bytes==64)return -RF_SNS_ARGUMENT;
    struct writer w={out,capacity,0,0};field_bytes(&w,1,name,bytes);
    scalar(&w,16);scalar(&w,updates);scalar(&w,24);scalar(&w,default_only);
    return w.error?-w.error:(int)w.at;
}
int rf_sns_rate_body(uint8_t *out,uint32_t capacity,uint32_t rate)
{
    if(!out||capacity<5||!finite_float(rate)||(rate>>31)||!(rate&0x7fffffff)||rate>0x43c80000)
        return -RF_SNS_ARGUMENT;
    out[0]=13;put32(out+1,rate);return 5;
}
int rf_sns_request(uint8_t *out,uint32_t capacity,const struct rf_sns_suid *uid,uint32_t message,
    const uint8_t *body,uint32_t bytes)
{
    if(!out||!uid||!(uid->low|uid->high)||!message||message>4095||capacity>RF_SNS_REQUEST_MAX||
        bytes>RF_SNS_REQUEST_MAX-64||(bytes&&!body))return -RF_SNS_ARGUMENT;
    uint8_t encoded_uid[18]={9},standard[RF_SNS_REQUEST_MAX];
    put64(encoded_uid+1,uid->low);encoded_uid[9]=17;put64(encoded_uid+10,uid->high);
    struct writer request={standard,sizeof(standard),0,0};
    field_bytes(&request,2,body,bytes);
    const uint8_t suspend[4]={8,1,16,0}; /* native APSS / wakeup delivery */
    struct writer w={out,capacity,0,0};field_bytes(&w,1,encoded_uid,sizeof(encoded_uid));
    scalar(&w,21);uint8_t id[4];put32(id,message);append(&w,id,4);
    field_bytes(&w,3,suspend,sizeof(suspend));field_bytes(&w,4,standard,request.at);
    return w.error?-w.error:request.error?-request.error:(int)w.at;
}
int rf_sns_qmi_request(uint8_t *out,uint32_t capacity,uint16_t transaction,const uint8_t *payload,
    uint32_t bytes,bool jumbo)
{
    if(!out||!transaction||!payload||!bytes||bytes>RF_SNS_REQUEST_MAX)return -RF_SNS_ARGUMENT;
    uint32_t total=12+bytes+(jumbo?4u:0u);if(capacity<total)return -RF_SNS_LIMIT;
    out[0]=0;put16(out+1,transaction);put16(out+3,RF_SNS_QMI_REQUEST);put16(out+5,(uint16_t)(total-7));
    out[7]=1;put16(out+8,(uint16_t)(bytes+2));put16(out+10,(uint16_t)bytes);memcpy(out+12,payload,bytes);
    if(jumbo){out[12+bytes]=16;put16(out+13+bytes,1);out[15+bytes]=1;}
    return (int)total;
}
int rf_sns_qmi_decode(const uint8_t *data,uint32_t bytes,struct rf_sns_qmi *out)
{
    if(!data||!out||bytes<7||bytes>RF_SNS_REPORT_MAX+32||le16(data+5)!=bytes-7)
        return RF_SNS_ARGUMENT;
    struct rf_sns_qmi v={0};v.transaction=le16(data+1);v.message=le16(data+3);
    if(data[0]==2&&v.message==RF_SNS_QMI_REQUEST&&v.transaction)v.indication=0;
    else if(data[0]==4&&(v.message==RF_SNS_QMI_REPORT||v.message==RF_SNS_QMI_JUMBO))v.indication=1;
    else return RF_SNS_FORMAT;
    uint32_t seen=0;
    for(uint32_t at=7;at<bytes;) {
        if(bytes-at<3)return RF_SNS_TRUNCATED;
        uint32_t type=data[at],length=le16(data+at+1);at+=3;
        if(length>bytes-at)return RF_SNS_TRUNCATED;
        const uint8_t *value=data+at;at+=length;
        uint32_t bit=type==1?1u:type==2?2u:type==16?4u:type==17?8u:0u;
        if(seen&bit)return RF_SNS_FORMAT;seen|=bit;
        if(v.indication) {
            if(type==1){if(length!=8)return RF_SNS_FORMAT;v.client=le64(value);v.has_client=1;}
            else if(type==2) {
                if(length<2||le16(value)!=length-2||length-2>(v.message==RF_SNS_QMI_JUMBO?RF_SNS_REPORT_MAX:1000u))
                    return RF_SNS_FORMAT;
                v.payload=(struct rf_sns_slice){value+2,length-2};
            }
        } else {
            if(type==2){if(length!=4)return RF_SNS_FORMAT;v.result=le16(value);v.error=le16(value+2);}
            else if(type==16){if(length!=8)return RF_SNS_FORMAT;v.client=le64(value);v.has_client=1;}
            else if(type==17){if(length!=4)return RF_SNS_FORMAT;v.sensor_result=le32(value);v.has_sensor_result=1;}
        }
    }
    if(v.indication) {if((seen&3)!=3||!v.payload.bytes)return RF_SNS_FORMAT;}
    else if(!(seen&2)||v.result>1||(!v.result&&v.error))return RF_SNS_FORMAT;
    *out=v;return 0;
}
static int registry_parts(struct rf_sns_slice input,struct rf_sns_slice *name,struct rf_sns_slice *items)
{
    struct rf_sns_pb p={input,0,0};struct rf_sns_field f;unsigned seen=0;int next;
    while((next=rf_sns_next(&p,&f))>0)if(f.number==1||f.number==2) {
        unsigned bit=1u<<(f.number-1);if((seen&bit)||f.wire!=2)return RF_SNS_FORMAT;
        seen|=bit;if(f.number==1)*name=f.data;else *items=f.data;
    }
    return next<0?-next:seen==3?0:RF_SNS_FORMAT;
}
struct registry_item {struct rf_sns_slice name,value;uint32_t version,kind,wire;uint64_t scalar;};
static int registry_item_decode(struct rf_sns_slice input,struct registry_item *out)
{
    struct registry_item v={0};struct rf_sns_pb p={input,0,0};struct rf_sns_field f;unsigned seen=0;int next;
    while((next=rf_sns_next(&p,&f))>0) {
        unsigned bit=f.number==1?1u:f.number==2?2u:f.number>=10&&f.number<=13?4u:0u;
        if(seen&bit)return RF_SNS_FORMAT;seen|=bit;
        if(f.number==1){if(f.wire!=2||!f.data.bytes)return RF_SNS_FORMAT;v.name=f.data;}
        else if(f.number==2){if(f.wire!=5)return RF_SNS_FORMAT;v.version=(uint32_t)f.scalar;}
        else if(bit==4) {
            if(((f.number==10||f.number==11)&&f.wire!=2)||(f.number==12&&f.wire!=5)||(f.number==13&&f.wire!=1))return RF_SNS_FORMAT;
            v.kind=f.number;v.wire=f.wire;v.value=f.data;v.scalar=f.scalar;
        }
    }
    if(next<0)return -next;
    if((seen&5)!=5)return RF_SNS_FORMAT;
    *out=v;return 0;
}
static int registry_subset(struct rf_sns_slice actual,struct rf_sns_slice expected,unsigned depth)
{
    if(depth>=16)return RF_SNS_LIMIT;
    struct rf_sns_pb p={expected,0,0};struct rf_sns_field f;unsigned count=0;int next;
    while((next=rf_sns_next(&p,&f))>0)if(f.number==3) {
        if(f.wire!=2||++count>1024)return RF_SNS_FORMAT;
        struct registry_item e;int error=registry_item_decode(f.data,&e);if(error)return error;
        struct rf_sns_pb a={actual,0,0};struct rf_sns_field g;unsigned found=0;int step;
        while((step=rf_sns_next(&a,&g))>0)if(g.number==3) {
            if(g.wire!=2)return RF_SNS_FORMAT;
            struct registry_item v;error=registry_item_decode(g.data,&v);if(error)return error;
            if(v.name.bytes!=e.name.bytes||memcmp(v.name.data,e.name.data,e.name.bytes))continue;
            if(++found>1||v.version<e.version||v.kind!=e.kind)return RF_SNS_FORMAT;
            if(v.kind==10)error=registry_subset(v.value,e.value,depth+1);
            else if(v.wire==2)error=v.value.bytes!=e.value.bytes||memcmp(v.value.data,e.value.data,e.value.bytes)?RF_SNS_FORMAT:0;
            else error=v.scalar!=e.scalar?RF_SNS_FORMAT:0;
            if(error)return error;
        }
        if(step<0)return -step;
        if(!found)return RF_SNS_FORMAT;
    }
    return next<0?-next:!count?RF_SNS_FORMAT:0;
}
int rf_sns_registry_contains(struct rf_sns_slice actual,struct rf_sns_slice expected)
{
    struct rf_sns_slice an={0},ai={0},en={0},ei={0};
    int error=registry_parts(actual,&an,&ai);if(!error)error=registry_parts(expected,&en,&ei);
    if(error)return error;
    if(an.bytes!=en.bytes||memcmp(an.data,en.data,en.bytes))return RF_SNS_FORMAT;
    return registry_subset(ai,ei,0);
}
