/* SPDX-License-Identifier: MIT
 * Native HID publication from actual, validated SEE samples. Each sensor owns
 * its workloop/event cache. Failed/replaced sources terminate their service. */
#include <IOKit/IOLib.h>
#include <IOKit/IOWorkLoop.h>
#include <IOKit/IOService.h>
#include <IOKit/IOPlatformExpert.h>
#include <libkern/c++/OSNumber.h>
#include "hid/IOHIDEventService.h"
#include "hid/IOHIDEvent.h"
#include "hid/IOHIDEventFieldDefs.h"
#include "hid/IOHIDKeys.h"
#include "ssc-client.h"
#include <kern/clock.h>
static uint32_t intervals[RF_SENSOR_COUNT];
class RedfinSensorHID : public IOHIDEventService {
    OSDeclareDefaultStructors(RedfinSensorHID);
public:
    unsigned kind;
    IOWorkLoop *loop;
    IOLock *cache_lock;
    IOHIDEvent *cached;
    char native_name[80],native_vendor[80];
    bool initSensor(unsigned index,const rf_ssc_sensor *s) {
        if(!IOHIDEventService::init()||index>=RF_SENSOR_COUNT)return false;
        kind=index;strlcpy(native_name,s->name,sizeof(native_name));strlcpy(native_vendor,s->vendor,sizeof(native_vendor));
        loop=IOWorkLoop::workLoop();cache_lock=IOLockAlloc();
        return loop&&cache_lock;
    }
    IOWorkLoop *getWorkLoop() const override {return loop;}
    OSString *getProduct() override {return OSString::withCString(native_name);}
    OSString *getTransport() override {return OSString::withCString("SPU");}
    UInt32 getVendorID() override {return 0x18d1;}
    UInt32 getProductID() override {return 0x7250+kind;}
    UInt32 getReportInterval() override {uint32_t n=__atomic_load_n(&intervals[kind],__ATOMIC_ACQUIRE);return n?n:20000;}
    UInt32 getPrimaryUsagePage() override {return 0x20;}
    UInt32 getPrimaryUsage() override {
        static const UInt32 usages[RF_SENSOR_COUNT]={0x73,0x76,0x83,0x41,0x12,0x31,0x33,0x73,0x73,0x8a,0x8a,0x8a};
        return usages[kind];
    }
    bool start(IOService *provider) override {
        if(!IOHIDEventService::start(provider))return false;
        setProperty(kIOHIDManufacturerKey,native_vendor);
        setProperty("SensorDataType",rf_ssc_datatype(kind));
        setProperty("SensorSource","native-adsp-ssc");
        setProperty("SensorCalibrationVerified",kOSBooleanTrue);
        setProperty("EventType",eventType(),32);
        return true;
    }
    UInt32 eventType() const {
        static const UInt32 types[RF_SENSOR_COUNT]={kIOHIDEventTypeAccelerometer,kIOHIDEventTypeGyro,kIOHIDEventTypeCompass,
            kIOHIDEventTypeAmbientLightSensor,kIOHIDEventTypeProximity,kIOHIDEventTypeAtmosphericPressure,
            kIOHIDEventTypeTemperature,kIOHIDEventTypeAccelerometer,kIOHIDEventTypeAccelerometer,
            kIOHIDEventTypeOrientation,kIOHIDEventTypeOrientation,kIOHIDEventTypeOrientation};
        return types[kind];
    }
    IOReturn setProperties(OSObject *object) override {
        OSDictionary *d=OSDynamicCast(OSDictionary,object);if(!d)return kIOReturnBadArgument;
        OSObject *value=d->getObject(kIOHIDReportIntervalKey);
        if(value) {
            OSNumber *n=OSDynamicCast(OSNumber,value);if(!n||n->unsigned64BitValue()<2500||n->unsigned64BitValue()>10000000)return kIOReturnBadArgument;
            __atomic_store_n(&intervals[kind],n->unsigned32BitValue(),__ATOMIC_RELEASE);
            setProperty(kIOHIDReportIntervalKey,n);
        }
        return kIOReturnSuccess;
    }
    IOHIDEvent *copyEvent(IOHIDEventType type,IOHIDEvent * =0,IOOptionBits=0) override {
        if(type&&type!=eventType())return NULL;
        IOLockLock(cache_lock);IOHIDEvent *event=cached;if(event)event->retain();IOLockUnlock(cache_lock);return event;
    }
    IOHIDEvent *copyMatchingEvent(OSDictionary *matching) override {
        OSNumber *type=matching?OSDynamicCast(OSNumber,matching->getObject("EventType")):NULL;
        return copyEvent(type?type->unsigned32BitValue():0);
    }
    void sample(const rf_ssc_sensor *s) {
        uint64_t raw=__builtin_arm_rsr64("CNTPCT_EL0"),now=mach_absolute_time(),elapsed=0;
        if(s->ticks>raw)return;
        uint64_t delta=raw-s->ticks;
        uint64_t ns=(delta/19200000u)*1000000000u+(delta%19200000u)*1000000000u/19200000u;
        nanoseconds_to_absolutetime(ns,&elapsed);if(elapsed>now)return;
        uint64_t time=now-elapsed;
        IOHIDEvent *event=NULL;
        if(kind==RF_SENSOR_ACCEL||kind==RF_SENSOR_GRAVITY||kind==RF_SENSOR_LINEAR_ACCEL)
            event=IOHIDEvent::accelerometerEvent(time,s->fixed[0],s->fixed[1],s->fixed[2],0,0,s->samples);
        else if(kind==RF_SENSOR_GYRO)event=IOHIDEvent::gyroEvent(time,s->fixed[0],s->fixed[1],s->fixed[2],0,0,s->samples);
        else if(kind==RF_SENSOR_MAG)event=IOHIDEvent::compassEvent(time,s->fixed[0],s->fixed[1],s->fixed[2],0,0,s->samples);
        else if(kind==RF_SENSOR_LIGHT) {
            if(s->fixed[0]<0)return;
            event=IOHIDEvent::ambientLightSensorEvent(time,(UInt32)s->fixed[0]);
        }else if(kind==RF_SENSOR_PROX)event=IOHIDEvent::proximityEvent(time,s->fixed[0]?kIOHIDProximityDetectionLargeBodyContact:0,(UInt32)s->fixed[0]);
        else if(kind==RF_SENSOR_PRESSURE)event=IOHIDEvent::atmosphericPressureEvent(time,s->fixed[0],s->samples);
        else if(kind==RF_SENSOR_TEMP)event=IOHIDEvent::temperatureEvent(time,s->fixed[0]);
        else if(kind>=RF_SENSOR_ROTATION) {
            event=IOHIDEvent::orientationEvent(time,kIOHIDOrientationTypeQuaternion);
            if(event){event->setFixedValue(kIOHIDEventFieldOrientationQuatX,s->fixed[0]);event->setFixedValue(kIOHIDEventFieldOrientationQuatY,s->fixed[1]);
                event->setFixedValue(kIOHIDEventFieldOrientationQuatZ,s->fixed[2]);event->setFixedValue(kIOHIDEventFieldOrientationQuatW,s->fixed[3]);}
        }
        if(!event)return;
        IOLockLock(cache_lock);IOHIDEvent *previous=cached;cached=event;event->retain();IOLockUnlock(cache_lock);
        OSSafeReleaseNULL(previous);dispatchEvent(event);event->release();
    }
    void free() override {
        OSSafeReleaseNULL(cached);
        if(cache_lock){IOLockFree(cache_lock);cache_lock=NULL;}
        /* The started base holds its own retain until its gate is removed. */
        OSSafeReleaseNULL(loop);
        IOHIDEventService::free();
    }
};
OSDefineMetaClassAndStructors(RedfinSensorHID,IOHIDEventService);
static RedfinSensorHID *services[RF_SENSOR_COUNT];
extern "C" uint32_t redfin_sensor_hid_interval(unsigned kind)
{return kind<RF_SENSOR_COUNT?__atomic_load_n(&intervals[kind],__ATOMIC_ACQUIRE):0;}
extern "C" void redfin_sensor_hid_sample(unsigned kind,const rf_ssc_sensor *sample)
{
    if(kind>=RF_SENSOR_COUNT||!sample||!sample->samples||!sample->name[0]||!sample->vendor[0])return;
    RedfinSensorHID *service=services[kind];
    if(!service) {
        service=OSTypeAlloc(RedfinSensorHID);
        IOService *provider=IOService::getPlatform();
        if(!service||!provider||!service->initSensor(kind,sample)||!service->attach(provider)||!service->start(provider)) {
            if(service){if(service->getProvider())service->detach(provider);service->release();}return;
        }
        services[kind]=service;service->setName(sample->name);service->registerService();
        IOLog("REDFIN SENSORS: native HID published datatype=%s name=%.79s service=%llu\n",rf_ssc_datatype(kind),sample->name,service->getRegistryEntryID());
    }
    service->sample(sample);
}
extern "C" void redfin_sensor_hid_withdraw(unsigned kind)
{
    if(kind>=RF_SENSOR_COUNT)return;RedfinSensorHID *service=services[kind];services[kind]=NULL;
    if(service){service->terminate();service->release();}
}
