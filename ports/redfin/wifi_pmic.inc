/* SPDX-License-Identifier: MIT
 * Included at the end of redfin_spmi.c, after the existing rail observer.
 * Google msm500b3a2: spmi-pmic-arb.c v5, qpnp-revid.h PM8150/PM8150L.
 * Qualcomm firmware20bb8ae: common LDO4000/stride100, pm_ldo_driver_init's
 * type4/subtype>=30 unified layout and pm_pwr_alg VSET_VALID42/43.
 * SID1 LDO ordering is already observed on Redfin. SID5 pages remain named
 * candidates until independently attributed; no readiness policy uses them.
 * Only the cached EE0 observer mapping is written, with EXT_READL commands.
 * No PMIC write channel, new mapping, IRQ acknowledge or power command.
 */
static const unsigned redfin_wp_ppids[7] = {0x001, 0x401, 0x140, 0x14d, 0x541, 0x54a, 0x549};
static struct {
 unsigned busy, next_phase;
 bool active, poisoned;
 void *child;
 int (*policy)(void *);
 struct redfin_rail_target targets[7];
} redfin_wp;
struct redfin_wp_sample { uint16_t header, configured, valid, mode_enable, status; };

static int
redfin_wp_check(void)
{
 if (!redfin_wp.active || redfin_wp.poisoned || !redfin_wp.child || !redfin_wp.policy ||
     !ml_get_interrupts_enabled() || __builtin_arm_rsr64("CurrentEL") != 4 ||
     (__builtin_arm_rsr64("MPIDR_EL1") & 0xff00ffffffULL) ||
     !redfin_spmi_return_ready() || !redfin_spmi_proof.ready ||
     !redfin_spmi_proof.core || !redfin_spmi_proof.observer || !redfin_spmi_proof.config ||
     redfin_spmi_proof.version < 0x50000000 || redfin_spmi_proof.version >= 0x70000000 ||
     redfin_rail_attempted || redfin_rail_snapshot_busy || redfin_rail_poisoned ||
     redfin_wp.policy(redfin_wp.child)) {
  redfin_wp.poisoned = true;
  return EPERM;
 }
 return 0;
}

static int
redfin_wp_read(const struct redfin_rail_target *t, unsigned offset, unsigned count, uint16_t *out)
{
 bool allowed = false;
 if (t) for (unsigned i = 0; i < 7; ++i) if (t == &redfin_wp.targets[i] && t->ppid == redfin_wp_ppids[i]) {
  allowed = i < 2 ? offset == 4 && count == 2 :
      ((offset == 4 || offset == 0x40 || offset == 0x42 || offset == 0x45) && count == 2) ||
      (offset == 8 && count == 1);
 }
 if (!out || !allowed || redfin_wp_check()) return EINVAL;
 if (!redfin_rail_mapping(t)) { redfin_wp.poisoned = true; return EAGAIN; }
 unsigned channel = t->apid * 0x80;
 uint32_t command = (1u << 27) | (offset << 4) | (count - 1u);
 __asm__ volatile("dmb oshst" ::: "memory");
 *(volatile uint32_t *)(redfin_spmi_proof.observer + channel) = command;
 __asm__ volatile("dsb osh" ::: "memory");
 for (unsigned us = 0; us < 1000; ++us) {
  if (redfin_wp_check() || !redfin_rail_mapping(t)) { redfin_wp.poisoned = true; return EAGAIN; }
  uint32_t status = redfin_spmi_rd(redfin_spmi_proof.observer, channel + 8);
  if (status & 1) {
   if (status & 0x0e) { redfin_wp.poisoned = true; return EIO; }
   uint32_t data = redfin_spmi_rd(redfin_spmi_proof.observer, channel + 0x18);
   if (redfin_wp_check() || !redfin_rail_mapping(t)) { redfin_wp.poisoned = true; return EAGAIN; }
   *out = (uint16_t)(data & (count == 1 ? 255u : 65535u));
   return 0;
  }
  delay(1);
 }
 redfin_wp.poisoned = true;
 return ETIMEDOUT; /* No channel reuse, cleanup or retry before full reset. */
}

static bool redfin_wp_unified(uint16_t header)
{ return (header & 255u) == 4 && (header >> 8) >= 0x30; }

static int
redfin_wp_sample(const struct redfin_rail_target *t, struct redfin_wp_sample *out)
{
 int error = redfin_wp_read(t, 4, 2, &out->header);
 if (error || !redfin_wp_unified(out->header)) return error;
 error = redfin_wp_read(t, 0x40, 2, &out->configured);
 if (!error) error = redfin_wp_read(t, 0x42, 2, &out->valid);
 if (!error) error = redfin_wp_read(t, 0x45, 2, &out->mode_enable);
 if (!error) error = redfin_wp_read(t, 8, 1, &out->status);
 return error;
}

int redfin_wifi_wlan_pmic_observe(unsigned phase, void *child, int (*policy)(void *));
int
redfin_wifi_wlan_pmic_observe(unsigned phase, void *child, int (*policy)(void *))
{
 if (phase > 2 || !child || !policy || redfin_wp.poisoned || phase != redfin_wp.next_phase ||
     (phase && (child != redfin_wp.child || policy != redfin_wp.policy))) return EINVAL;
 if (__atomic_exchange_n(&redfin_wp.busy, 1, __ATOMIC_ACQUIRE)) return EBUSY;
 redfin_wp.child = child; redfin_wp.policy = policy; redfin_wp.active = true;
 int error = redfin_wp_check();
 if (error || !redfin_rail_platform()) { if (!error) error = ENXIO; goto out; }
 if (!phase) {
  for (unsigned i = 0; i < 7; ++i)
   redfin_wp.targets[i] = (struct redfin_rail_target){redfin_wp_ppids[i], 512, 0, 0};
  for (unsigned apid = 0; apid < 512; ++apid) {
   if (redfin_wp_check()) { error = EPERM; goto out; }
   uint32_t mapping = redfin_spmi_rd(redfin_spmi_proof.core, 0x900 + 4 * apid);
   unsigned ppid = (mapping >> 8) & 0xfff;
   if (!mapping) continue;
   for (unsigned i = 0; i < 7; ++i) if (ppid == redfin_wp_ppids[i]) {
    unsigned owner = redfin_spmi_rd(redfin_spmi_proof.config, 0x700 + 4 * apid) & 7;
    if (redfin_wp.targets[i].apid == 512 || owner == 0)
     redfin_wp.targets[i] = (struct redfin_rail_target){ppid, apid, owner, mapping};
   }
  }
  for (unsigned i = 0; i < 7; ++i) if (redfin_wp.targets[i].apid == 512) {
   printf("REDFIN WIFI PMIC: candidate PPID=%#x has no APID; physical absence unproven\n", redfin_wp_ppids[i]);
   error = ENXIO; goto out;
  }
 }
 for (unsigned i = 0; i < 2; ++i) {
  uint16_t model = 0;
  error = redfin_wp_read(&redfin_wp.targets[i], 4, 2, &model);
  printf("REDFIN WIFI PMIC: phase=%u SID%u REVID=%#x result=%d\n", phase, i * 4u, model, error);
  if (error) goto out;
  if (model != (i ? 0x1f51 : 0x1e51)) { error = ENOTSUP; goto out; }
 }
 for (unsigned i = 2; i < 7; ++i) {
  const struct redfin_rail_target *t = &redfin_wp.targets[i];
  struct redfin_wp_sample a = {0}, b = {0};
  error = redfin_wp_sample(t, &a);
  if (!error) {
   if (redfin_wp_check()) { error = EPERM; goto out; }
   delay(100);
   error = redfin_wp_sample(t, &b);
  }
  if (error) goto out;
  bool stable = a.header == b.header && a.configured == b.configured && a.valid == b.valid &&
      a.mode_enable == b.mode_enable && a.status == b.status;
  printf("REDFIN WIFI PMIC: phase=%u candidate PPID=%#x APID=%u owner=%u header=%#x unified=%u stable=%u configured_mV=%u valid_mV=%u MODE=%#x ENABLE=%#x STATUS=%#x ready=%u\n",
      phase, t->ppid, t->apid, t->owner, a.header, redfin_wp_unified(a.header), stable,
      a.configured, a.valid, a.mode_enable & 255u, a.mode_enable >> 8, a.status, !!(a.status & 0x80));
  if (!stable) { error = EAGAIN; goto out; }
 }
 for (unsigned i = 0; i < 2; ++i) {
  uint16_t model = 0;
  error = redfin_wp_read(&redfin_wp.targets[i], 4, 2, &model);
  if (error) goto out;
  if (model != (i ? 0x1f51 : 0x1e51)) { error = EAGAIN; goto out; }
 }
 ++redfin_wp.next_phase;
out:
 printf("REDFIN WIFI PMIC: phase=%u observation=%d; no PMIC writes, no supply-readiness claim\n", phase, error);
 if (error) redfin_wp.poisoned = true;
 redfin_wp.active = false;
 __atomic_store_n(&redfin_wp.busy, 0, __ATOMIC_RELEASE);
 return error;
}
