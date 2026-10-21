#pragma once
#include <stdint.h>

#define MAX_BANKS 16
#define MAX_RESERVED 128
struct region { uint64_t base, size; };
struct hardware {
    struct region memory[MAX_BANKS], splash;
    unsigned banks;
    int redfin, psci_smc;
    struct region reserved[MAX_RESERVED];
    unsigned reservations;
    struct region watchdog;
};

/* Parse only bounded FDT blocks; never dereference physical reg values. */
int redfin_fdt(const void *blob, struct hardware *hw);
