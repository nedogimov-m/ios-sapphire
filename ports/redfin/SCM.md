# Redfin SCM capability audit

`--scm-probe --return-bootloader` builds a separate CPU0/md0 diagnostic.
It queries the native Qualcomm SCM calling convention, availability of PAS
functions and `PAS_SUPPORTED` for MPSS4 and GPU-zap13. It does not initialize,
authenticate, reset or shut down a peripheral, assign memory, or pass a
metadata/DMA pointer to TrustZone. A positive capability result would not
establish successful firmware authentication or GPU execution.

The reference is Google msm commit
`500b3a2059c1eec0fec08ec56add06320ea901a8`,
`drivers/soc/qcom/scm.c` (`is_scm_armv8`, the ARMv8 wrappers and
`scm_is_call_available`) and `include/soc/qcom/scm.h`. Detection uses the
native legacy-SCM atomic INFO query, then the chosen32/64-bit convention
uses standard queries. Firmware calls are checked for availability only.
The executor preserves the native interrupted x1..x6 state/cookie, bounds
continuations/busy retries and elapsed time, normalizes SMC32 status, and
rechecks the frozen CPU0/EL1/argument/ADT/return lease around every call.
Its allowlist accepts only the described read-only queries.

`include/redfin_scm_query.h` is the host-tested callback executor.
`scm-query.c` supplies the kernel adapter; the diagnostic translation unit
includes it once so adding this audit does not regenerate BSD configuration.
The separate ADT leaf contains only the query version, PAS IDs and exact
function list. Startup refuses competing observers. Native inherited modem,
Wi-Fi and GPU backends remain disabled by the exact argument profile.

Five actual-executor host tests pass: exact registers, invalid/mutating
targets, native resume state, bounded busy/interrupt paths, SMC32 errors,
elapsed-time and ownership failures. Local ARM64 build045451 passes.
`scm-query-v1` passes complete real payload/ADT/live-FDT validation and
the compiled shim plus kernel return policy. No hardware query result is
available for that original image. A later hardware run is recorded below.

New GPU/GMU/native-Wi-Fi/SCM diagnostic images prearm the proven shim's
PMIC/IMEM bootloader reason before payload or XNU initialization. Kernel
return verification remains required. The host cycle binds this to the
exact config/image hashes, arguments, nonce and isolated md0 profile;
modern-probe images lacking prearm are rejected. This changes the software
failure boundary; the combined new profiles still require a device test.

Hardware observation, 2026-10-23: `scm-query-v2` on local build053033 returns
authenticated, image/nonce-matched logs, static PID1 heartbeats and verified
fastboot return. ABI detection selects64bit. Each of the five availability
queries returns status0/value1 in one call, without busy/interrupt retries.
`PAS_SUPPORTED` for4 and13 returns status0/value0. That is a negative
capability response, not evidence that firmware authentication will work.
No INIT/MEM_SETUP/AUTH_RESET/SHUTDOWN/assignment was attempted. HFSX remains
clean/unmounted with its existing write count. Exact image/kernel/arguments
are recorded in `NOTES.md`; device logs stay private.
