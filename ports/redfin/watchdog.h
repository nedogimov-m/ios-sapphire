#pragma once
#include "fdt.h"

/* Arm the FDT-identified Redfin watchdog for 10..29 seconds before bark;
 * bite occurs three seconds after bark (20-bit hardware counter limit).
 * Call before leaving the shim while identity MMIO is available. No pet loop.
 */
int redfin_watchdog(const struct hardware *hw, unsigned seconds);
