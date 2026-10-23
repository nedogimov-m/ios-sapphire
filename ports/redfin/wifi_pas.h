/* SPDX-License-Identifier: MIT
 * Native PAS4 executor. Include after redfin_scm_query.h. The native platform
 * must bind every invocation to its own power/reset/copy/authentication phase.
 */
#ifndef REDFIN_WIFI_PAS_H
#define REDFIN_WIFI_PAS_H
static inline int rf_wifi_pas_run(const struct rf_sq_ops *ops, unsigned convention,
    unsigned command, uint64_t address, uint64_t bytes, struct rf_sq_report *report)
{
    struct rf_sq_regs request = {{0}}, live;
    if (!ops || !report || !ops->valid || !ops->invoke || !ops->time_ns || !ops->delay_us ||
        (convention != 32 && convention != 64) ||
        (command != 1 && command != 2 && command != 5 && command != 6) ||
        (command == 1 && (address != UINT64_C(0x8c000000) || bytes)) ||
        (command == 2 && (address != UINT64_C(0x8c000000) || bytes != UINT64_C(0x11800000))) ||
        ((command == 5 || command == 6) && (address || bytes))) return EINVAL;
    request.x[0] = UINT64_C(0x02000200) | command | (convention == 64 ? UINT64_C(0x40000000) : 0);
    request.x[1] = command == 1 ? 0x82u : command == 2 ? 3u : 1u;
    request.x[2] = 4; request.x[3] = address; request.x[4] = bytes;
#ifdef __cplusplus
    *report = {};
#else
    *report = (struct rf_sq_report){0};
#endif
    report->convention = convention; report->kind = command;
    report->function = request.x[0]; report->argument = 4;
    if (!ops->valid(ops->context)) return ECANCELED;
    uint64_t first = ops->time_ns(ops->context);
    live = request;
    for (;;) {
        if (!ops->valid(ops->context)) return ECANCELED;
        uint64_t now = ops->time_ns(ops->context);
        if (now < first || now - first > UINT64_C(2000000000)) return ETIMEDOUT;
        if (live.x[0] != request.x[0] && live.x[0] != 1) return EINVAL;
        live.x[7] = 0;
        int error = ops->invoke(ops->context, &live);
        ++report->calls;
        if (error) return error;
        if (!ops->valid(ops->context)) return ECANCELED;
        now = ops->time_ns(ops->context);
        if (now < first || now - first > UINT64_C(2000000000)) return ETIMEDOUT;
        report->elapsed_ns = now - first;
        report->status = convention == 32 ? (int64_t)(int32_t)(uint32_t)live.x[0] : (int64_t)live.x[0];
        for (unsigned i = 0; i < 3; ++i)
            report->value[i] = convention == 32 ? (uint32_t)live.x[i + 1] : live.x[i + 1];
        if (report->status == 1) {
            if (++report->resumes > 16) return ETIMEDOUT;
            continue;
        }
        if (report->status == -12) {
            if (report->busy_retries >= 3) return EBUSY;
            ++report->busy_retries;
            if (!ops->valid(ops->context)) return ECANCELED;
            ops->delay_us(ops->context, 30000);
            live = request;
            continue;
        }
        report->completed = true;
        return report->status || report->value[0] ? EIO : 0;
    }
}
#endif
