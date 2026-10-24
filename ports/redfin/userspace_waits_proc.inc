/* Read-only diagnostics require the existing native GUI8 policy plus an
 * explicit chosen property. No scheduler instrumentation or thread stops.
 */
extern void redfin_wait_task(const char *, int, task_t, uint64_t);
extern int redfin_gui_selected(void);
extern int redfin_gui_ready(void);
void redfin_userspace_waits_poll(unsigned final);
void
redfin_userspace_waits_poll(unsigned final)
{
    static uint64_t sample_at;
    static unsigned sampled;
    uint32_t cpus = 0, gui = 0;
    DTEntry chosen;
    const void *property;
    unsigned bytes;
    if (!PE_parse_boot_argn("cpus", &cpus, sizeof(cpus)) || cpus != 8 ||
        !PE_parse_boot_argn("redfingui", &gui, sizeof(gui)) || (gui != 2 && gui != 3) ||
        !redfin_gui_selected() || !redfin_gui_ready() ||
        SecureDTLookupEntry(NULL, "/chosen", &chosen) != kSuccess ||
        SecureDTGetProperty(chosen, "redfin-user-waits", &property, &bytes) != kSuccess ||
        bytes != sizeof(uint32_t) || *(const uint32_t *)property != 1) return;
    uint64_t now = mach_absolute_time(), interval;
    if (!sample_at) {
        nanoseconds_to_absolutetime(90ULL * NSEC_PER_SEC, &interval);
        if (now > UINT64_MAX - interval) return;
        sample_at = now + interval;
    }
    if (!final && (sampled || now < sample_at)) return;
    if (sampled >= 2) return;
    ++sampled;
    nanoseconds_to_absolutetime(200ULL * NSEC_PER_MSEC, &interval);
    if (now > UINT64_MAX - interval) return;
    uint64_t deadline = now + interval;
    const char *wifi_names[4] = { "Preferences", "wifid", "configd", "securityd" };
    const char *graphics_names[4] = { "MobilePhone", "MobileSlideShow", "callservicesd", "photolibraryd" };
    const char *const *names = gui == 3 ? graphics_names : wifi_names;
    proc_t selected[4] = { PROC_NULL, PROC_NULL, PROC_NULL, PROC_NULL };
    if (!lck_mtx_try_lock(&proc_list_mlock)) return;
    proc_t p;
    unsigned scanned = 0;
    ALLPROC_FOREACH(p) {
        if (scanned++ == 512) break;
        for (unsigned i = 0; i < 4; ++i) {
            if (selected[i] != PROC_NULL || strncmp(p->p_comm, names[i], sizeof(p->p_comm))) continue;
            uint32_t bits = proc_ref_try_fast(p);
            if (!bits) continue;
            if (proc_ref_needs_wait_for_exec(bits)) { proc_rele(p); continue; }
            selected[i] = p;
        }
    }
    proc_list_unlock();
    printf("RWSTACK BEGIN sample=%u final=%u processes=4 threads=16 frames=16 budget_ms=200 waiting_only=1 resident_only=1\n", sampled, final);
    for (unsigned i = 0; i < 4; ++i) {
        p = selected[i];
        if (p == PROC_NULL) { printf("RWSTACK SKIP name=%s reason=not-found-or-exec\n", names[i]); continue; }
        redfin_wait_task(names[i], proc_pid(p), proc_task(p), deadline);
        proc_rele(p);
    }
    printf("RWSTACK DONE\n");
}
