/* Inserted before PID1's heartbeat loop by --ufs-root-probe.
 * Reads only the exposed raw partition device. Never prints disk contents.
 */

	adr	x0, ufs_path
	mov	x1, #0              /* O_RDONLY */
	mov	x2, #0
	mov	x16, #5             /* open */
	svc	#0x80
	b.cs	ufs_open_failed
	mov	x20, x0
	sub	sp, sp, #4096
	mov	x1, sp
	mov	x2, #4096
	mov	x16, #3             /* read */
	svc	#0x80
	b.cs	ufs_read_failed
	cmp	x0, #4096
	b.ne	ufs_read_failed
	adr	x21, ufs_read_ok
	adr	x22, ufs_read_ok_end
	b	ufs_read_finish
ufs_read_failed:
	adr	x21, ufs_read_error
	adr	x22, ufs_read_error_end
ufs_read_finish:
	add	sp, sp, #4096
	mov	x0, x20
	mov	x16, #6             /* close */
	svc	#0x80
	mov	x1, x21
	sub	x2, x22, x21
	bl	write_console
	/* An open requesting write access must fail before any I/O is issued. */
	adr	x0, ufs_path
	mov	x1, #1              /* O_WRONLY; no write syscall follows */
	mov	x2, #0
	mov	x16, #5
	svc	#0x80
	b.cs	ufs_check_readonly
	mov	x16, #6
	svc	#0x80
	b	ufs_not_readonly
ufs_check_readonly:
	cmp	x0, #30             /* EROFS */
	b.ne	ufs_not_readonly
	adr	x1, ufs_readonly_ok
	adr	x2, ufs_readonly_ok_end
	b	ufs_report
ufs_not_readonly:
	adr	x1, ufs_readonly_error
	adr	x2, ufs_readonly_error_end
	b	ufs_report
ufs_open_failed:
	adr	x1, ufs_open_error
	adr	x2, ufs_open_error_end
ufs_report:
	sub	x2, x2, x1
	bl	write_console
	b	tick

ufs_path:
	.asciz	"/dev/rufsroot0"
ufs_read_ok:
	.ascii	"REDFIN UFS userspace: read 4096 bytes OK\n"
ufs_read_ok_end:
ufs_read_error:
	.ascii	"REDFIN UFS userspace: read failed\n"
ufs_read_error_end:
ufs_readonly_ok:
	.ascii	"REDFIN UFS userspace: write-open rejected EROFS\n"
ufs_readonly_ok_end:
ufs_readonly_error:
	.ascii	"REDFIN UFS userspace: write-open guard failed\n"
ufs_readonly_error_end:
ufs_open_error:
	.ascii	"REDFIN UFS userspace: open failed\n"
ufs_open_error_end:
	.p2align 2
