/* Host-only inspector for an exact 2 MiB regular SMEM snapshot. */
#define _POSIX_C_SOURCE 200809L
#if defined(__APPLE__)
#define _DARWIN_C_SOURCE 1
#endif
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>
#include "wifi_smem.h"

int main(int argc, char **argv)
{
    struct stat before, after;
    if (argc != 2) { fprintf(stderr, "usage: wifi-smem SMEM-SNAPSHOT\n"); return 2; }
    if (lstat(argv[1], &before) || !S_ISREG(before.st_mode) || before.st_size != REDFIN_SMEM_BYTES) {
        fprintf(stderr, "requires an exact 2 MiB regular snapshot, not a device or symlink\n"); return 2;
    }
    int fd = open(argv[1], O_RDONLY | O_NOFOLLOW | O_NONBLOCK);
    if (fd < 0) return 2;
    if (fstat(fd, &after) || !S_ISREG(after.st_mode) ||
        before.st_dev != after.st_dev || before.st_ino != after.st_ino ||
        after.st_size != REDFIN_SMEM_BYTES) { close(fd); return 2; }
    FILE *stream = fdopen(fd, "rb");
    if (!stream) { close(fd); return 2; }
    uint8_t *data = malloc(REDFIN_SMEM_BYTES);
    if (!data) { fclose(stream); return 2; }
    size_t count = fread(data, 1, REDFIN_SMEM_BYTES, stream);
    int extra = fgetc(stream), error = ferror(stream);
    fclose(stream);
    if (count != REDFIN_SMEM_BYTES || extra != EOF || error) { free(data); return 2; }
    struct redfin_smem_report report;
    enum redfin_smem_status status = redfin_smem_inspect(data, count, &report);
    free(data);
    printf("{\"status\":%u,\"version\":%u,\"partitions\":%u,\"modem_partition\":%u,"
           "\"partition_offset\":%u,\"partition_bytes\":%u,\"uncached_items\":%u,"
           "\"cached_uninspected\":%u,\"descriptor\":%u,\"tx_bytes\":%u,\"rx_bytes\":%u,"
           "\"tx_pending\":%u,\"rx_pending\":%u,\"remote_running_proven\":false,"
           "\"wlfw_observed\":false}\n", status, report.version, report.partitions,
           report.modem_partition, report.partition_offset, report.partition_bytes,
           report.uncached_items, report.cached_uninspected, report.descriptor,
           report.tx_bytes, report.rx_bytes, report.tx_pending, report.rx_pending);
    return status == REDFIN_SMEM_OK ? 0 : 1;
}
