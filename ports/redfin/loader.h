#pragma once
#include <stdint.h>
#include "fdt.h"

/* Return a diagnostic on rejection; successful handoff does not return. */
const char *redfin_boot(uint64_t dtb, const struct hardware *hw);
