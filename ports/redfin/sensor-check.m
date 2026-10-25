/* SPDX-License-Identifier: MIT
 * Unattended native CoreMotion/HID observations, only for a nonce-bound GUI3
 * capture. Native availability/authorization/results are left unchanged. */
#import <Foundation/Foundation.h>
#import <CoreMotion/CoreMotion.h>
#include <IOKit/IOKitLib.h>
#include <CoreFoundation/CoreFoundation.h>
#include <sys/sysctl.h>
#include <unistd.h>
#include <stdio.h>
#include "gui-profile.h"
static void hid_inventory(void)
{
    io_iterator_t iterator=0;
    if(IOServiceGetMatchingServices(kIOMainPortDefault,IOServiceMatching("RedfinSensorHID"),&iterator)!=KERN_SUCCESS)return;
    unsigned count=0;io_object_t service;
    while((service=IOIteratorNext(iterator))) {
        CFTypeRef type=IORegistryEntryCreateCFProperty(service,CFSTR("SensorDataType"),kCFAllocatorDefault,0);
        CFTypeRef source=IORegistryEntryCreateCFProperty(service,CFSTR("SensorSource"),kCFAllocatorDefault,0);
        CFTypeRef calibrated=IORegistryEntryCreateCFProperty(service,CFSTR("SensorCalibrationVerified"),kCFAllocatorDefault,0);
        char name[80]={0},origin[80]={0};
        if(type&&CFGetTypeID(type)==CFStringGetTypeID())CFStringGetCString(type,name,sizeof(name),kCFStringEncodingUTF8);
        if(source&&CFGetTypeID(source)==CFStringGetTypeID())CFStringGetCString(source,origin,sizeof(origin),kCFStringEncodingUTF8);
        printf("REDFIN SENSOR CHECK: native-HID type=%s source=%s registry-readback=%u\n",name,origin,calibrated==kCFBooleanTrue);++count;
        if(type)CFRelease(type);if(source)CFRelease(source);if(calibrated)CFRelease(calibrated);IOObjectRelease(service);
    }
    IOObjectRelease(iterator);printf("REDFIN SENSOR CHECK: native-HID services=%u\n",count);
}
int main(void)
{
    @autoreleasepool {
        char args[608]={0};size_t size=sizeof(args);uint64_t nonce=0;
        if(sysctlbyname("kern.bootargs",args,&size,NULL,0)||!size||size>sizeof(args)||args[size-1]||
            !redfin_gpu_gui_profile(args,(unsigned)size,&nonce))return 0;
        setbuf(stdout,NULL);
        CMMotionManager *manager=[CMMotionManager new];NSOperationQueue *queue=[NSOperationQueue new];
        queue.maxConcurrentOperationCount=1;
        __block unsigned accelerometer=0,gyro=0,magnetometer=0,device_motion=0,pressure=0,errors=0;
        manager.accelerometerUpdateInterval=0.05;manager.gyroUpdateInterval=0.05;manager.magnetometerUpdateInterval=0.1;
        [manager startAccelerometerUpdatesToQueue:queue withHandler:^(CMAccelerometerData *data,NSError *error) {
            if(error){++errors;return;}if(data&&accelerometer++==0)printf("REDFIN SENSOR CHECK: native-CoreMotion accel-first=1 value=%g,%g,%g timestamp=%g\n",data.acceleration.x,data.acceleration.y,data.acceleration.z,data.timestamp);
        }];
        [manager startGyroUpdatesToQueue:queue withHandler:^(CMGyroData *data,NSError *error) {
            if(error){++errors;return;}if(data)++gyro;
        }];
        [manager startMagnetometerUpdatesToQueue:queue withHandler:^(CMMagnetometerData *data,NSError *error) {
            if(error){++errors;return;}if(data)++magnetometer;
        }];
        [manager startDeviceMotionUpdatesToQueue:queue withHandler:^(CMDeviceMotion *data,NSError *error) {
            if(error){++errors;return;}if(data)++device_motion;
        }];
        CMAltimeter *altimeter=[CMAltimeter new];
        if(CMAltimeter.isRelativeAltitudeAvailable)[altimeter startRelativeAltitudeUpdatesToQueue:queue withHandler:^(CMAltitudeData *data,NSError *error) {
            if(error){++errors;return;}if(data)++pressure;
        }];
        for(unsigned second=0;second<240;++second) {
            @autoreleasepool {
                if(second%20==0) {
                    printf("REDFIN SENSOR CHECK: boot=%016llx second=%u available=%u/%u/%u/%u altitude=%u authorization=%ld samples=%u/%u/%u/%u/%u errors=%u\n",
                        (unsigned long long)nonce,second,manager.accelerometerAvailable,manager.gyroAvailable,manager.magnetometerAvailable,
                        manager.deviceMotionAvailable,CMAltimeter.isRelativeAltitudeAvailable,(long)CMAltimeter.authorizationStatus,
                        accelerometer,gyro,magnetometer,device_motion,pressure,errors);
                    hid_inventory();
                }
                [[NSRunLoop currentRunLoop]runUntilDate:[NSDate dateWithTimeIntervalSinceNow:1.0]];
            }
        }
        [manager stopAccelerometerUpdates];[manager stopGyroUpdates];[manager stopMagnetometerUpdates];[manager stopDeviceMotionUpdates];
        [altimeter stopRelativeAltitudeUpdates];
    }
    return 0;
}
