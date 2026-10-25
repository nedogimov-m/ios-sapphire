/* SPDX-License-Identifier: MIT */
/* Native SEE/SSC client wire format. This codec contains no firmware, sensor
 * identity, calibration or fabricated samples. All numbers come from the
 * discovered SSC service and its actual protobuf messages. */
#ifndef REDFIN_SSC_PROTOCOL_H
#define REDFIN_SSC_PROTOCOL_H
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#define RF_SNS_SERVICE 400u
#define RF_SNS_VERSION 1u
#define RF_SNS_REQUEST_MAX 1000u
#define RF_SNS_REPORT_MAX 62000u
#define RF_SNS_EVENT_MAX 512u
#define RF_SNS_VALUES_MAX 16u
enum { RF_SNS_QMI_REQUEST=0x20, RF_SNS_QMI_REPORT=0x21, RF_SNS_QMI_JUMBO=0x22 };
enum { RF_SNS_ATTR_REQUEST=1,RF_SNS_DISABLE_REQUEST=10,RF_SNS_ATTR_EVENT=128,
    RF_SNS_ERROR_EVENT=130,RF_SNS_LOOKUP_REQUEST=512,RF_SNS_CONFIG_REQUEST=513,
    RF_SNS_ON_CHANGE_REQUEST=514,RF_SNS_LOOKUP_EVENT=768,
    RF_SNS_PROXIMITY_EVENT=769,RF_SNS_SAMPLE_EVENT=1025 };
enum { RF_SNS_OK,RF_SNS_ARGUMENT,RF_SNS_TRUNCATED,RF_SNS_FORMAT,RF_SNS_LIMIT,
    RF_SNS_RANGE,RF_SNS_CALLBACK };
struct rf_sns_slice {const uint8_t *data;uint32_t bytes;};
struct rf_sns_suid {uint64_t low,high;};
struct rf_sns_pb {struct rf_sns_slice input;uint32_t offset,fields;};
struct rf_sns_field {uint32_t number,wire;uint64_t scalar;struct rf_sns_slice data;};
struct rf_sns_event {uint32_t id;uint64_t ticks;struct rf_sns_slice payload;};
struct rf_sns_sample {uint32_t bits[RF_SNS_VALUES_MAX],count,status;};
struct rf_sns_proximity {uint32_t near,adc,status;};
struct rf_sns_attribute {uint32_t id;struct rf_sns_slice value;};
struct rf_sns_qmi {
    uint16_t transaction,message,result,error;
    uint8_t indication,has_client,has_sensor_result;
    uint64_t client;
    uint32_t sensor_result;
    struct rf_sns_slice payload;
};
typedef int (*rf_sns_event_fn)(void *,const struct rf_sns_suid *,const struct rf_sns_event *);
typedef int (*rf_sns_attribute_fn)(void *,const struct rf_sns_attribute *);

#ifdef __cplusplus
extern "C" {
#endif
/* next returns 1 for a field, 0 at the exact end, or a negative RF_SNS error. */
int rf_sns_next(struct rf_sns_pb *,struct rf_sns_field *);
int rf_sns_suid_decode(struct rf_sns_slice,struct rf_sns_suid *);
int rf_sns_lookup_decode(struct rf_sns_slice,struct rf_sns_slice *datatype,
    struct rf_sns_suid *,uint32_t capacity,uint32_t *count);
int rf_sns_events(struct rf_sns_slice,rf_sns_event_fn,void *);
int rf_sns_attributes(struct rf_sns_slice,rf_sns_attribute_fn,void *);
int rf_sns_sample_decode(struct rf_sns_slice,struct rf_sns_sample *);
int rf_sns_proximity_decode(struct rf_sns_slice,struct rf_sns_proximity *);
/* Integer-only IEEE754 conversion, usable in a kernel without FP state. It
 * refuses nonfinite/overflow input instead of wrapping or inventing a value. */
int rf_sns_float_fixed(uint32_t bits,uint32_t numerator,uint32_t denominator,int32_t *);

/* Encoders return the positive encoded length, or a negative RF_SNS error. */
int rf_sns_lookup_body(uint8_t *,uint32_t,const char *,bool updates,bool default_only);
int rf_sns_rate_body(uint8_t *,uint32_t,uint32_t ieee754_rate);
int rf_sns_request(uint8_t *,uint32_t,const struct rf_sns_suid *,uint32_t message,
    const uint8_t *body,uint32_t body_bytes);
int rf_sns_qmi_request(uint8_t *,uint32_t,uint16_t transaction,const uint8_t *,uint32_t,bool jumbo);
int rf_sns_qmi_decode(const uint8_t *,uint32_t,struct rf_sns_qmi *);
/* Validate an actual registry read response contains every named item in a
 * previously written fragment. Item ordering/extra native items are allowed. */
int rf_sns_registry_contains(struct rf_sns_slice actual,struct rf_sns_slice expected);
#ifdef __cplusplus
}
#endif
#endif
