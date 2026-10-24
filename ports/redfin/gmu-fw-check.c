/* SPDX-License-Identifier: MIT */
/* Host-side use of the exact kernel firmware planner. No device access. */
#include <stdio.h>
#include <stdlib.h>
#include "include/redfin_gmu_firmware.h"
int main(int argc, char **argv)
{
    if (argc != 2) return 2;
    FILE *f = fopen(argv[1], "rb");
    if (!f) return 3;
    uint8_t *data = malloc(REDFIN_GMU_MAX_FILE_BYTES + 1);
    if (!data) return 4;
    size_t bytes = fread(data, 1, REDFIN_GMU_MAX_FILE_BYTES + 1, f);
    if (ferror(f)) return 5;
    fclose(f);
    struct redfin_gmu_fw_plan plan;
    int error = redfin_gmu_fw_plan_make(REDFIN_GMU_CHIP_ID, data, bytes, &plan);
    free(data);
    if (error) { fprintf(stderr, "GMU firmware planner refused: %d\n", error); return 6; }
    printf("GMU firmware: %u bytes, %u payloads, %u memory regions, %u DMA bytes\n",
           plan.file_bytes, plan.payload_count, plan.region_count, plan.dma_bytes);
    return 0;
}
