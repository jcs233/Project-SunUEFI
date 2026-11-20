/* SPDX-License-Identifier: BSD-2-Clause */
/* Negative signals win across ALL supported sources. Do not interpret board
 * buttons, a diagnostic cmdline override or a boot *reason* as a request. */
#include <stdint.h>
#include <stddef.h>
#include <string.h>

typedef struct { const char *s; size_t n; } text;
#define IS(t, literal) ((t).n == sizeof(literal)-1 && !memcmp((t).s, literal, sizeof(literal)-1))
static int blank(char c) { return c == ' ' || c == '\t'; }
static int keychar(char c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
           (c >= '0' && c <= '9') || c == '_' || c == '.' || c == '-';
}
static int contains(text t, const char *s) {
    size_t n = strlen(s);
    for (size_t i = 0; i+n <= t.n; ++i) {
        size_t j = 0;
        while (j < n) {
            char c = t.s[i+j];
            if (c >= 'A' && c <= 'Z') c += 'a'-'A';
            if (c != s[j]) break;
            ++j;
        }
        if (j == n) return 1;
    }
    return 0;
}
static int field(text k, text v, int *normal) {
    /* Match decision keys, not substrings of arbitrary vendor settings. In
     * particular charge_boot_mode=0 is present on a normal dada boot. */
    if (IS(k,"mca_log.charge_boot_mode") && !IS(v,"0")) return 0;
    if (IS(k,"silent_boot.mode") && !IS(v,"nonsilent")) return 0;
    if (IS(k,"mtdoops.boot_mode") && !IS(v,"0")) return 0;
    if ((IS(k,"recovery") || IS(k,"charger") || IS(k,"fastboot") ||
         IS(k,"androidboot.recovery") || IS(k,"androidboot.charger_mode") ||
         IS(k,"androidboot.fastboot")) && !IS(v,"0")) return 0;
    if ((IS(k,"androidboot.bootreason") || IS(k,"androidboot.boot_reason") || IS(k,"bootreason") ||
         IS(k,"androidboot.reboot_reason")) &&
        (contains(v,"recovery") || contains(v,"charg") || contains(v,"poweroff_cg") || contains(v,"fastboot"))) return 0;
    if (IS(k,"bootmonitor.bootmode")) {
        if (!IS(v,"normal") || *normal) return 0;
        *normal = 1;
    }
    if ((IS(k,"androidboot.mode") || IS(k,"androidboot.bootmode") || IS(k,"androidboot.boot_mode") ||
         IS(k,"bootmode") || IS(k,"boot_mode")) && !IS(v,"normal")) return 0;
    if (IS(k,"androidboot.force_normal_boot") && !IS(v,"1")) return 0;
    if (IS(k,"androidboot.product.hardware.sku") && !IS(v,"dada")) return 0;
    return 1;
}
/* Parse entire fields, never substrings of other fields. Accept simple quoted
 * values and flat bootconfig assignments; reject unsupported grammar rather
 * than skipping a line which could hide a conflicting decision key. */
int dada_fields(const char *s, size_t n, int config, int *normal) {
    size_t i = 0;
    while (i < n) {
        if (blank(s[i]) || (config && s[i] == '\n')) { ++i; continue; }
        if (config && s[i] == '#') {
            while (i < n && s[i] != '\n') { if (!s[i++]) return 0; }
            continue;
        }
        size_t start = i;
        while (i < n && keychar(s[i])) ++i;
        text k = {s+start, i-start}, v = {"",0};
        if (!k.n || IS(k,"--")) return 0;
        if (config && ((k.n >= 7 && !memcmp(k.s,"kernel.",7)) ||
                       (k.n >= 5 && !memcmp(k.s,"init.",5)))) return 0;
        if (config) while (i < n && blank(s[i])) ++i;
        if (i < n && s[i] == '=') {
            ++i;
            if (config) while (i < n && blank(s[i])) ++i;
            char quote = 0;
            if (i < n && (s[i] == '"' || (config && s[i] == '\''))) quote = s[i++];
            start = i;
            while (i < n) {
                char c = s[i];
                if (quote ? c == quote : (blank(c) || (config && (c == '\n' || c == '#')))) break;
                if (c < ' ' || c > '~' || c == '\\' || (!quote &&
                    (c == '"' || c == '\'' || (config && (c == ';' || c == '{' || c == '}'))))) return 0;
                ++i;
            }
            v = (text){s+start,i-start};
            if (quote && i++ == n) return 0;
        } else if (config) return 0;
        if (!field(k,v,normal)) return 0;
        if (config) {
            while (i < n && blank(s[i])) ++i;
            if (i < n && s[i] == '#') continue;
            if (i < n && s[i++] != '\n') return 0;
        } else if (i < n && !blank(s[i])) return 0;
    }
    return 1;
}
static uint32_t le32(const uint8_t *p) {
    return (uint32_t)p[0] | (uint32_t)p[1]<<8 | (uint32_t)p[2]<<16 | (uint32_t)p[3]<<24;
}
/* Caller first proves the ENTIRE initrd is live normal RAM and disjoint from
 * all protected intervals. No cpio traversal/decompression or APP execution. */
int dada_bootconfig(const uint8_t *p, size_t n, int *normal) {
    static const char magic[] = "#BOOTCONFIG\n";
    for (unsigned pad = 0; pad <= 3 && n >= 20; ++pad, --n) {
        if (!memcmp(p+n-12,magic,12)) {
            uint32_t len = le32(p+n-20), sum = 0;
            if (!len || len > 32767 || len > n-20) return 0;
            const uint8_t *data = p+n-20-len;
            for (unsigned i = 0; i < len; ++i) sum += data[i];
            if (sum != le32(p+n-16)) return 0;
            while (len && !data[len-1]) --len;
            return len && dada_fields((const char *)data,len,1,normal);
        }
        if (p[n-1]) break;
    }
    return 0;
}
