/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_SSC_CLIENT_H
#define REDFIN_SSC_CLIENT_H
#include "ssc-protocol.h"
#include "sensor-assets.h"
#define RF_SSC_SENSORS 16u
enum {RF_SENSOR_ACCEL,RF_SENSOR_GYRO,RF_SENSOR_MAG,RF_SENSOR_LIGHT,RF_SENSOR_PROX,
    RF_SENSOR_PRESSURE,RF_SENSOR_TEMP,RF_SENSOR_GRAVITY,RF_SENSOR_LINEAR_ACCEL,
    RF_SENSOR_ROTATION,RF_SENSOR_GAME_ROTATION,RF_SENSOR_GEOMAG_ROTATION,RF_SENSOR_COUNT};
struct rf_ssc_sensor {
    struct rf_sns_suid uid;
    char name[80],vendor[80];
    uint32_t found,attributes,available,stream_type,rate,configured,attribute_sent,configure_sent;
    uint32_t samples,errors,status,values;
    uint32_t rate_count,rates[32],requested_interval;
    int32_t fixed[RF_SNS_VALUES_MAX];
    uint64_t ticks,last_received;
};
struct rf_ssc_ops {
    void *context;
    int (*check)(void *);
    int (*send)(void *,const uint8_t *,uint32_t);
    uint64_t (*now_ns)(void *);
    void (*sample)(void *,unsigned,const struct rf_ssc_sensor *);
    void (*withdraw)(void *,unsigned);
    void (*event)(void *,const char *,unsigned,unsigned);
};
struct rf_ssc_client {
    unsigned begun,failed,phase,registry_index,registry_verified,lookup_index,request_kind,request_sensor;
    uint16_t serial,pending;
    uint64_t deadline,client,registry_deadline;
    unsigned client_seen,registry_found,read_verified,registry_empty;
    struct rf_sns_suid registry;
    const struct rf_sensor_assets *assets;
    const struct rf_sensor_asset *fragment;
    struct rf_ssc_sensor sensor[RF_SSC_SENSORS];
    const struct rf_ssc_ops *ops;
    uint8_t request[RF_SNS_REQUEST_MAX+32];
};
#ifdef __cplusplus
extern "C" {
#endif
int rf_ssc_begin(struct rf_ssc_client *,const struct rf_ssc_ops *,const struct rf_sensor_assets *);
int rf_ssc_receive(struct rf_ssc_client *,const uint8_t *,uint32_t);
int rf_ssc_poll(struct rf_ssc_client *);
void rf_ssc_stop(struct rf_ssc_client *);
const char *rf_ssc_datatype(unsigned);
int rf_ssc_set_interval(struct rf_ssc_client *,unsigned,uint32_t microseconds);
#ifdef __cplusplus
}
#endif
#endif
