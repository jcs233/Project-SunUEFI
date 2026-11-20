/* SPDX-License-Identifier: MIT
 * AArch64 PID 1 for the firmware-volume size budget. No libc, block-device
 * access, persistent filesystem, or EFI variable writes. /dev/console is
 * opened as stdio by the kernel before it execs init. */
#include <asm/unistd.h>
#include <linux/reboot.h>
#include <linux/utsname.h>

static long sc(long n, long a, long b, long c, long d, long e)
{
    register long x0 asm("x0") = a, x1 asm("x1") = b, x2 asm("x2") = c;
    register long x3 asm("x3") = d, x4 asm("x4") = e, x8 asm("x8") = n;
    asm volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x3), "r"(x4), "r"(x8) : "memory", "cc");
    return x0;
}
static void say(const char *s)
{
    long len = 0;
    while (s[len]) ++len;
    while (len) {
        long r = sc(__NR_write, 1, (long)s, len, 0, 0);
        if (r <= 0) break;
        s += r; len -= r;
    }
}
static long ropen(const char *s) { return sc(__NR_openat, -100, (long)s, 0, 0, 0); }
void __attribute__((noreturn)) _start(void)
{
    static struct new_utsname u;
    static char model[256];
    static const long delay[] = {90, 0};
    long sys = sc(__NR_mount, (long)"sysfs", (long)"/sys", (long)"sysfs", 1, 0);
    long f = ropen("/sys/firmware/devicetree/base/model");
    long n = f < 0 ? -1 : sc(__NR_read, f, (long)model, sizeof(model)-1, 0, 0);
    sc(__NR_uname, (long)&u, 0, 0, 0, 0);
    say("DADA_RAM_PROBE kernel="); say(u.release);
    say(sys == 0 && ropen("/sys/firmware/efi") >= 0 ? " efi=yes model=" : " efi=no model=");
    say(n > 0 ? model : "unknown"); say("\nRAM only. Restart requested in 90 seconds.\n");
    for (;;) {
        sc(__NR_nanosleep, (long)delay, 0, 0, 0, 0);
        sc(__NR_reboot, LINUX_REBOOT_MAGIC1, LINUX_REBOOT_MAGIC2, LINUX_REBOOT_CMD_RESTART, 0, 0);
    }
}
