/* SPDX-License-Identifier: MIT
 * One bounded HLOS3 -> HLOS3/MSS15 RW assignment, for the owned RMTFS buffer.
 * Google msm 500b3a2059c1eec0fec08ec56add06320ea901a8 secure_buffer.c/scm.c.
 * Include after redfin_scm_query.h and wifi_rmtfs.h. All memory is retained
 * until platform reset after either success or an uncertain result.
 */
#ifndef REDFIN_WIFI_HYP_H
#define REDFIN_WIFI_HYP_H
static inline int rf_rm_hyp_prepare(uint8_t *scratch, uint64_t physical, uint64_t shared)
{
    if (!scratch || physical < UINT64_C(0x180000000) || physical > UINT64_C(0x200000000) - 16384u ||
        physical % 16384u || shared < UINT64_C(0x80000000) || shared > UINT64_C(0x100000000) - RF_RM_SHARED ||
        shared % 16384u) return EINVAL;
    memset(scratch, 0, 16384);
    rf_rm_put(scratch, shared, 8); rf_rm_put(scratch + 8, RF_RM_SHARED, 8);
    rf_rm_put(scratch + 0x40, 3, 4);
    rf_rm_put(scratch + 0x80, 3, 4); rf_rm_put(scratch + 0x84, 6, 4);
    rf_rm_put(scratch + 0x98, 15, 4); rf_rm_put(scratch + 0x9c, 6, 4);
    rf_rm_put(scratch + 0x100, 4, 8); rf_rm_put(scratch + 0x108, physical + 0x80, 8);
    rf_rm_put(scratch + 0x110, 48, 8);
    return 0;
}
static inline int rf_rm_hyp_run(const struct rf_sq_ops *o, uint64_t scratch, struct rf_sq_report *report)
{
    if (!o || !report || !o->valid || !o->invoke || !o->time_ns || !o->delay_us ||
        scratch < UINT64_C(0x180000000) || scratch > UINT64_C(0x200000000) - 16384u || scratch % 16384u)
        return EINVAL;
    struct rf_sq_regs request = {{UINT64_C(0x42000c16), 0x1117, scratch, 16, scratch + 0x40, scratch + 0x100, 0, 0}};
    struct rf_sq_regs live = request;
#ifdef __cplusplus
    *report = {};
#else
    *report = (struct rf_sq_report){0};
#endif
    report->convention = 64; report->function = request.x[0];
    if (!o->valid(o->context)) return ECANCELED;
    uint64_t first = o->time_ns(o->context);
    for (;;) {
        if (!o->valid(o->context)) return ECANCELED;
        uint64_t now = o->time_ns(o->context);
        if (now < first || now - first > UINT64_C(2000000000)) return ETIMEDOUT;
        live.x[7] = 0;
        int error = o->invoke(o->context, &live); ++report->calls;
        if (error) return error;
        if (!o->valid(o->context)) return ECANCELED;
        now = o->time_ns(o->context);
        if (now < first || now - first > UINT64_C(2000000000)) return ETIMEDOUT;
        report->elapsed_ns = now - first; report->status = (int64_t)live.x[0];
        for (unsigned i = 0; i < 3; ++i) report->value[i] = live.x[i + 1];
        if (report->status == 1) { if (++report->resumes > 16) return ETIMEDOUT; continue; }
        if (report->status == -12) {
            if (report->busy_retries++ >= 3) return EBUSY;
            o->delay_us(o->context, 30000); live = request; continue;
        }
        report->completed = true;
        return report->status || report->value[0] ? EIO : 0;
    }
}
#endif
