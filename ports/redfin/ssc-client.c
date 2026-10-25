/* SPDX-License-Identifier: MIT
 * Actual SSC service discovery, persisted-registry readback, attributes and
 * samples. No configured name alone can publish an iOS sensor. */
#include "ssc-client.h"
#include <string.h>
static const char *const datatype[RF_SENSOR_COUNT]={"accel","gyro","mag","ambient_light","proximity",
    "pressure","sensor_temperature","gravity","linear_accel","rotation_vector","game_rv","geomag_rv"};
const char *rf_ssc_datatype(unsigned i){return i<RF_SENSOR_COUNT?datatype[i]:NULL;}
static bool uid_equal(const struct rf_sns_suid *a,const struct rf_sns_suid *b)
{return a->low==b->low&&a->high==b->high;}
static int gate(struct rf_ssc_client *s)
{return !s||!s->begun||s->failed||!s->ops||s->ops->check(s->ops->context)?-1:0;}
void rf_ssc_stop(struct rf_ssc_client *s)
{
    if(!s||s->failed)return;s->failed=1;
    if(s->ops)for(unsigned i=0;i<RF_SENSOR_COUNT;++i)if(s->sensor[i].samples)s->ops->withdraw(s->ops->context,i);
}
static int fail(struct rf_ssc_client *s,const char *why,unsigned a,unsigned b)
{s->ops->event(s->ops->context,why,a,b);rf_ssc_stop(s);return -1;}
static int request(struct rf_ssc_client *s,const struct rf_sns_suid *uid,unsigned msg,
    const uint8_t *body,unsigned bytes,unsigned kind,unsigned sensor)
{
    if(gate(s)||s->pending||s->serial==65535)return -1;
    uint8_t payload[RF_SNS_REQUEST_MAX];int n=rf_sns_request(payload,sizeof(payload),uid,msg,body,bytes);
    if(n<0)return fail(s,"encode",msg,(unsigned)-n);
    s->pending=++s->serial;s->request_kind=kind;s->request_sensor=sensor;
    n=rf_sns_qmi_request(s->request,sizeof(s->request),s->pending,payload,(unsigned)n,true);
    if(n<0||s->ops->send(s->ops->context,s->request,(unsigned)n))return fail(s,"send",msg,n<0?(unsigned)-n:0);
    s->deadline=s->ops->now_ns(s->ops->context)+UINT64_C(5000000000);return 0;
}
static int lookup(struct rf_ssc_client *s,const char *name,unsigned kind,unsigned sensor)
{
    uint8_t body[128];int n=rf_sns_lookup_body(body,sizeof(body),name,true,true);
    const struct rf_sns_suid well={UINT64_C(0xabababababababab),UINT64_C(0xabababababababab)};
    return n<0?-1:request(s,&well,RF_SNS_LOOKUP_REQUEST,body,(unsigned)n,kind,sensor);
}
int rf_ssc_begin(struct rf_ssc_client *s,const struct rf_ssc_ops *o,const struct rf_sensor_assets *assets)
{
    if(!s||!o||!assets||s->begun||!o->check||!o->send||!o->sample||!o->withdraw||!o->event||!o->now_ns)return -1;
    s->begun=1;s->ops=o;s->assets=assets;s->phase=1;
    return lookup(s,"registry",1,0);
}
struct attr_context {struct rf_ssc_sensor *sensor;const char *datatype;};
static int attribute(void *context,const struct rf_sns_attribute *a)
{
    struct attr_context *context_info=context;
    struct rf_ssc_sensor *s=context_info->sensor;
    struct rf_sns_pb p={a->value,0,0};struct rf_sns_field f;unsigned count=0;int next;
    while((next=rf_sns_next(&p,&f))>0)if(f.number==1) {
        if(f.wire!=2||++count>128)return -1;
        struct rf_sns_pb v={f.data,0,0};struct rf_sns_field x;unsigned seen=0;int n;
        while((n=rf_sns_next(&v,&x))>0) {
            if(++seen>1)return -1;
            if(a->id<=2) {
                if(x.number!=2||x.wire!=2||!x.data.bytes||x.data.bytes>=80)return -1;
                char *dest=a->id==0?s->name:a->id==1?s->vendor:NULL;
                unsigned bytes=x.data.bytes;
                if(bytes&&x.data.data[bytes-1]==0)--bytes;
                for(unsigned i=0;i<bytes;++i)if(x.data.data[i]<32||x.data.data[i]>126)return -1;
                if(a->id==2&&(strlen(context_info->datatype)!=bytes||memcmp(x.data.data,context_info->datatype,bytes)))return -1;
                if(dest){memcpy(dest,x.data.data,bytes);dest[bytes]=0;}
                s->attributes|=1u<<a->id;
            } else if(a->id==3) {
                if(x.number!=5||x.wire||x.scalar>1)return -1;
                s->available=(uint32_t)x.scalar;s->attributes|=8;
            } else if(a->id==16) {
                if(x.number!=4||x.wire!=1||x.scalar>2)return -1;
                s->stream_type=(uint32_t)x.scalar;s->attributes|=16;
            } else if(a->id==6) {
                if(x.number!=3||x.wire!=5)return -1;
                uint32_t bits=(uint32_t)x.scalar;
                if((bits>>31)||!bits||bits>=0x7f800000)return -1;
                if(s->rate_count<32)s->rates[s->rate_count++]=bits;
                if(!(bits>>31)&&bits&&bits<=0x43c80000&&((bits<=0x42480000&&bits>s->rate)||!s->rate))s->rate=bits;
            }
        }
        if(n<0)return -1;
    }
    return next<0?-1:0;
}
static int event(void *context,const struct rf_sns_suid *uid,const struct rf_sns_event *e)
{
    struct rf_ssc_client *s=context;
    if(e->id==RF_SNS_LOOKUP_EVENT&&uid->low==UINT64_C(0xabababababababab)&&uid->high==uid->low) {
        struct rf_sns_slice type={0};struct rf_sns_suid uids[16];uint32_t count=0;
        int error=rf_sns_lookup_decode(e->payload,&type,uids,16,&count);if(error)return fail(s,"lookup-decode",error,0);
        unsigned i;
        if(type.bytes==8&&!memcmp(type.data,"registry",8)) {
            if(count!=1)return fail(s,"registry-unavailable",count,0);
            if(s->registry_found&&!uid_equal(&s->registry,&uids[0]))return fail(s,"registry-changed",0,0);
            s->registry=uids[0];s->registry_found=1;return 0;
        }
        for(i=0;i<RF_SENSOR_COUNT;++i)if(strlen(datatype[i])==type.bytes&&!memcmp(datatype[i],type.data,type.bytes))break;
        if(i==RF_SENSOR_COUNT)return 0;
        struct rf_ssc_sensor *sensor=&s->sensor[i];
        if(!count){if(sensor->samples)s->ops->withdraw(s->ops->context,i);memset(sensor,0,sizeof(*sensor));return 0;}
        if(count!=1)return fail(s,"ambiguous-default",i,count);
        if(sensor->found&&!uid_equal(&sensor->uid,&uids[0]))return fail(s,"sensor-replaced",i,0);
        sensor->uid=uids[0];sensor->found=1;s->ops->event(s->ops->context,"discovered",i,count);return 0;
    }
    if(s->registry_found&&uid_equal(uid,&s->registry)) {
        if(e->id==514&&s->phase==4&&s->fragment) {
            struct rf_sns_slice expected={s->fragment->data,s->fragment->bytes};
            if(rf_sns_registry_contains(e->payload,expected))return fail(s,"registry-readback",s->registry_index,0);
            s->read_verified=1;
        } else if(e->id==RF_SNS_ERROR_EVENT)return fail(s,"registry-error",e->id,0);
        return 0;
    }
    unsigned index;for(index=0;index<RF_SENSOR_COUNT;++index)if(s->sensor[index].found&&uid_equal(uid,&s->sensor[index].uid))break;
    if(index==RF_SENSOR_COUNT)return 0;
    struct rf_ssc_sensor *sensor=&s->sensor[index];
    if(e->id==RF_SNS_ATTR_EVENT) {
        struct attr_context a={sensor,datatype[index]};int error=rf_sns_attributes(e->payload,attribute,&a);
        if(error)return fail(s,"attributes",index,error);
        if(!sensor->available&&sensor->samples)s->ops->withdraw(s->ops->context,index);
        return 0;
    }
    if(e->id==RF_SNS_ERROR_EVENT){++sensor->errors;sensor->configured=0;s->ops->withdraw(s->ops->context,index);return 0;}
    if(!sensor->configured||!sensor->available)return 0;
    if((index==RF_SENSOR_PROX&&e->id!=RF_SNS_PROXIMITY_EVENT)||(index!=RF_SENSOR_PROX&&e->id!=RF_SNS_SAMPLE_EVENT))return 0;
    uint64_t now=s->ops->now_ns(s->ops->context);
    /* SSC and APSS use the same native 19.2MHz architectural counter. Reject
     * repeats, future times and stale data; the backend preserves that epoch. */
    uint64_t seconds=e->ticks/19200000u,remainder=e->ticks%19200000u;
    if(seconds>UINT64_MAX/1000000000u)return fail(s,"timestamp-overflow",index,0);
    uint64_t sample_ns=seconds*1000000000u+remainder*1000000000u/19200000u;
    if(!e->ticks||e->ticks<=sensor->ticks||sample_ns>now+UINT64_C(100000000)||now>sample_ns+UINT64_C(10000000000))
        return fail(s,"timestamp",index,0);
    if(index==RF_SENSOR_PROX) {
        struct rf_sns_proximity v;int error=rf_sns_proximity_decode(e->payload,&v);if(error)return fail(s,"proximity",error,0);
        sensor->fixed[0]=(int32_t)v.near;sensor->fixed[1]=(int32_t)v.adc;sensor->values=2;sensor->status=v.status;
    } else {
        struct rf_sns_sample v;int error=rf_sns_sample_decode(e->payload,&v);if(error)return fail(s,"sample",index,error);
        unsigned wanted=index<=RF_SENSOR_MAG||index==RF_SENSOR_GRAVITY||index==RF_SENSOR_LINEAR_ACCEL?3:
            index>=RF_SENSOR_ROTATION?4:1;
        if(v.count<wanted||v.count>6)return fail(s,"sample-dimensions",index,v.count);
        for(unsigned i=0;i<v.count;++i) {
            uint32_t num=1,den=1;
            if(index==RF_SENSOR_ACCEL||index==RF_SENSOR_GRAVITY||index==RF_SENSOR_LINEAR_ACCEL){num=100000;den=980665;}
            /* SEE pressure is hPa, native HID exposes kPa. */
            if(index==RF_SENSOR_PRESSURE)den=10;
            if(index==RF_SENSOR_LIGHT)den=65536; /* Native HID ALS is integer lux. */
            error=rf_sns_float_fixed(v.bits[i],num,den,&sensor->fixed[i]);if(error)return fail(s,"sample-range",index,error);
        }
        sensor->values=v.count;sensor->status=v.status;
    }
    sensor->ticks=e->ticks;sensor->last_received=now;++sensor->samples;
    s->ops->sample(s->ops->context,index,sensor);return 0;
}
int rf_ssc_receive(struct rf_ssc_client *s,const uint8_t *data,uint32_t bytes)
{
    if(gate(s))return -1;
    struct rf_sns_qmi q;int error=rf_sns_qmi_decode(data,bytes,&q);if(error)return fail(s,"qmi-decode",error,bytes);
    if(q.has_client) {
        if(s->client_seen&&q.client!=s->client)return fail(s,"client-changed",0,0);
        s->client=q.client;s->client_seen=1;
    }
    if(q.indication)return rf_sns_events(q.payload,event,s)?fail(s,"events",0,0):0;
    if(!s->pending||q.transaction!=s->pending)return fail(s,"unexpected-response",q.transaction,s->pending);
    if(q.result||q.error||(q.has_sensor_result&&q.sensor_result))return fail(s,"native-request-error",q.error,q.sensor_result);
    unsigned kind=s->request_kind;s->pending=0;
    if(kind==2)s->phase=3; /* Write ACK; now request actual registry readback. */
    if(kind==5)++s->lookup_index;
    if(kind==7)s->sensor[s->request_sensor].configured=1;
    return 0;
}
int rf_ssc_set_interval(struct rf_ssc_client *s,unsigned index,uint32_t us)
{
    if(gate(s)||index>=RF_SENSOR_COUNT||us<2500||us>10000000)return -1;
    struct rf_ssc_sensor *sensor=&s->sensor[index];
    if(sensor->requested_interval==us)return 0;
    sensor->requested_interval=us;
    if(!sensor->rate_count||sensor->stream_type)return 0;
    /* Select a real advertised rate, without kernel floating-point state. */
    uint32_t selected=0;int32_t desired=(int32_t)((UINT64_C(1000000)<<16)/us);
    for(unsigned i=0;i<sensor->rate_count;++i) {
        int32_t rate=0;if(rf_sns_float_fixed(sensor->rates[i],1,1,&rate)||rate<=0||rate>400*65536)continue;
        if(!selected)selected=sensor->rates[i];
        int32_t chosen=0;rf_sns_float_fixed(selected,1,1,&chosen);
        if((rate>=desired&&chosen<desired)||(rate>=desired&&rate<chosen)||(rate<desired&&chosen<desired&&rate>chosen))
            selected=sensor->rates[i];
    }
    if(selected&&selected!=sensor->rate){sensor->rate=selected;sensor->configure_sent=0;}
    return 0;
}
int rf_ssc_poll(struct rf_ssc_client *s)
{
    if(gate(s))return -1;
    uint64_t now=s->ops->now_ns(s->ops->context);
    if(s->pending)return now>s->deadline?fail(s,"request-timeout",s->request_kind,s->pending):0;
    if(s->phase==1) {
        if(!s->registry_found)return now>s->deadline?fail(s,"registry-timeout",0,0):0;
        s->phase=2;
    }
    if(s->phase==2) {
        char name[8]="reg/000";unsigned i=s->registry_index;
        if(i>=400)return fail(s,"registry-bound",i,0);
        name[4]=(char)('0'+i/100);name[5]=(char)('0'+i/10%10);name[6]=(char)('0'+i%10);
        s->fragment=rf_sensor_asset_find(s->assets,name);
        if(!s->fragment) {
            if(!i)return fail(s,"registry-empty",0,0);
            s->phase=5;s->ops->event(s->ops->context,"registry-verified",s->registry_verified,0);
        } else return request(s,&s->registry,513,s->fragment->data,s->fragment->bytes,2,0);
    }
    if(s->phase==3) {
        struct rf_sns_pb p={{s->fragment->data,s->fragment->bytes},0,0};struct rf_sns_field f;
        if(rf_sns_next(&p,&f)!=1||f.number!=1||f.wire!=2||f.data.bytes>100)return fail(s,"registry-name",0,0);
        uint8_t body[104];body[0]=10;body[1]=(uint8_t)f.data.bytes;memcpy(body+2,f.data.data,f.data.bytes);
        s->phase=4;s->read_verified=0;
        return request(s,&s->registry,512,body,f.data.bytes+2,3,0);
    }
    if(s->phase==4) {
        if(!s->read_verified)return now>s->deadline?fail(s,"registry-read-timeout",s->registry_index,0):0;
        ++s->registry_index;++s->registry_verified;s->phase=2;return 0;
    }
    if(s->phase==5&&s->lookup_index<RF_SENSOR_COUNT)return lookup(s,datatype[s->lookup_index],5,s->lookup_index);
    for(unsigned i=0;i<RF_SENSOR_COUNT;++i) {
        struct rf_ssc_sensor *sensor=&s->sensor[i];
        if(!sensor->found)continue;
        if(!sensor->attribute_sent){sensor->attribute_sent=1;return request(s,&sensor->uid,1,NULL,0,6,i);}
        if((sensor->attributes&31)==31&&sensor->available&&!sensor->configure_sent) {
            if(sensor->stream_type>1)continue;
            uint8_t body[8];unsigned bytes=0;
            if(!sensor->stream_type) {
                if(!sensor->rate)continue;
                int n=rf_sns_rate_body(body,sizeof(body),sensor->rate);if(n<0)return fail(s,"rate",i,0);
                bytes=(unsigned)n;
            }
            sensor->configure_sent=1;
            return request(s,&sensor->uid,sensor->stream_type?514:513,body,bytes,7,i);
        }
        if(sensor->samples&&sensor->configured&&!sensor->stream_type&&now-sensor->last_received>UINT64_C(10000000000)) {
            sensor->configured=0;s->ops->withdraw(s->ops->context,i);s->ops->event(s->ops->context,"stream-stale",i,0);
        }
    }
    return 0;
}
