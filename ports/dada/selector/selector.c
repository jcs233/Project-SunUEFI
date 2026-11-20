/* SPDX-License-Identifier: BSD-2-Clause */
#include "BootRequest.h"
/* Compile the actual board gate; reuse its internal busy/overlaps predicates
 * so changing its scratch layout cannot silently desynchronise the selector. */
#include "check.c"  /* from RAM_ROOT/firmware/guard, selected by build.sh */

int dada_fields(const char *, size_t, int, int *);
int dada_bootconfig(const uint8_t *, size_t, int *);

/* Prove that each live interval is in one enabled RAM tuple, not an MMIO
 * hole or a static reservation. A RAM bank may contain reservations. Reject
 * reservations even if a bootloader reserves its own initrd (safe refusal). */
static int ordinary_ram(const void *dt, const struct window live[], unsigned count) {
    unsigned covered = 0;
    int n, l;
    fdt_for_each_subnode(n,dt,0) {
        const char *s = fdt_getprop(dt,n,"device_type",&l);
        if (!s || l != 7 || memcmp(s,"memory",7)) continue;
        s = fdt_getprop(dt,n,"status",&l);
        if (s && !(l == 5 && !memcmp(s,"okay",5)) && !(l == 3 && !memcmp(s,"ok",3))) continue;
        const fdt32_t *p = fdt_getprop(dt,n,"reg",&l);
        if (!p || l <= 0 || l % 16) return 0;
        if (fdt_getprop(dt,n,"linux,usable-memory",NULL)) return 0;
        for (int i=0; i<l/4; i+=4) {
            uint64_t lo = val(p+i), bytes = val(p+i+2);
            if (bytes > UINT64_MAX-lo) return 0;
            for (unsigned j=0; j<count; ++j)
                if (lo <= live[j].lo && lo+bytes >= live[j].hi) covered |= 1u<<j;
        }
    }
    if (covered != (1u<<count)-1) return 0;
    /* dada_check has already validated all tuples and their arithmetic. */
    int nr = fdt_num_mem_rsv(dt);
    for (int i=0; i<nr; ++i) {
        uint64_t lo, bytes;
        if (fdt_get_mem_rsv(dt,i,&lo,&bytes)) return 0;
        for (unsigned j=0; j<count; ++j)
            if (overlaps(lo,lo+bytes,live[j].lo,live[j].hi)) return 0;
    }
    int res = fdt_path_offset(dt,"/reserved-memory");
    fdt_for_each_subnode(n,dt,res) {
        const fdt32_t *p = fdt_getprop(dt,n,"reg",&l);
        if (!p) continue;
        for (int i=0; i<l/4; i+=4) {
            uint64_t lo = val(p+i), bytes = val(p+i+2);
            for (unsigned j=0; j<count; ++j)
                if (overlaps(lo,lo+bytes,live[j].lo,live[j].hi)) return 0;
        }
    }
    return 1;
}

/* Only these /chosen properties have defined semantics for this prototype.
 * In particular do not ignore secondary bootargs, bootconfig, memory limits
 * or unrecognised boot-mode properties. Reject duplicate properties/nodes. */
static int chosen_node(const void *dt) {
    int chosen = -1, n, len;
    fdt_for_each_subnode(n,dt,0) {
        const char *name = fdt_get_name(dt,n,&len);
        if (len >= 6 && !memcmp(name,"chosen",6) && (len == 6 || name[6] == '@')) {
            if (len != 6 || chosen >= 0) return -1;
            chosen = n;
        }
    }
    if (chosen < 0 || fdt_first_subnode(dt,chosen) != -FDT_ERR_NOTFOUND) return -1;
    static const char names[] = "bootargs\0linux,initrd-start\0linux,initrd-end\0stdout-path\0"
                                "linux,stdout-path\0phandle\0linux,phandle\0kaslr-seed\0rng-seed\0name\0";
    unsigned seen = 0;
    int off;
    fdt_for_each_property_offset(off,dt,chosen) {
        const char *name;
        const char *value = fdt_getprop_by_offset(dt,off,&name,&len);
        if (!value) return -1;
        if (strlen(name) == 4 && !memcmp(name,"name",4) &&
            (len != 7 || memcmp(value,"chosen",7))) return -1;
        const char *p = names;
        unsigned bit = 1;
        while (*p && (strlen(name) != strlen(p) || memcmp(p,name,strlen(p)))) {
            p += strlen(p)+1;
            bit <<= 1;
        }
        if (!*p || (seen & bit)) return -1;
        seen |= bit;
    }
    return chosen;
}

int dada_environment(const void *dt, uint64_t dtaddr, uint64_t base, uint64_t end,
                     uint64_t shim, uint64_t guard_end) {
    if (!dt || !dtaddr || (dtaddr & 7) || dtaddr > UINT64_MAX-40 || end <= base ||
        overlaps(dtaddr,dtaddr+40,base,end) || busy(base,end-base)) return 0;
    if (fdt_magic(dt) != FDT_MAGIC) return 0;
    unsigned len = fdt_totalsize(dt);
    if (len < 40 || len > 0x200000 || len > UINT64_MAX-dtaddr ||
        overlaps(base,end,dtaddr,dtaddr+len) || busy(dtaddr,len)) return 0;
    if (dada_check(dt,shim,guard_end,dtaddr)) return 0;
    if (fdt_path_offset(dt,"/firmware/android") != -FDT_ERR_NOTFOUND) return 0; /* legacy argument source */

    int c = chosen_node(dt), a, b, normal = 0;
    if (c < 0) return 0;
    struct window live[] = {{base,end},{dtaddr,dtaddr+len},{0,0}};
    unsigned count = 2;
    const fdt32_t *sp = fdt_getprop(dt,c,"linux,initrd-start",&a);
    const fdt32_t *ep = fdt_getprop(dt,c,"linux,initrd-end",&b);
    if (a != -FDT_ERR_NOTFOUND || b != -FDT_ERR_NOTFOUND) {
        if (!sp || !ep || a != b || (a != 4 && a != 8)) return 0;
        uint64_t lo = a == 8 ? val(sp) : fdt32_to_cpu(*sp);
        uint64_t hi = a == 8 ? val(ep) : fdt32_to_cpu(*ep);
        if (!lo || hi <= lo || busy(lo,hi-lo) || overlaps(lo,hi,base,end) ||
            overlaps(lo,hi,dtaddr,dtaddr+len)) return 0;
        live[count++] = (struct window){lo,hi};
    }
    if (!ordinary_ram(dt,live,count)) return 0;
    const char *cmd = fdt_getprop(dt,c,"bootargs",&a);
    if (!cmd || a <= 0 || a > 8192 || cmd[a-1] || !dada_fields(cmd,a-1,0,&normal) || !normal) return 0;
    if (count == 3 && !dada_bootconfig((const void *)(uintptr_t)live[2].lo,
                                       live[2].hi-live[2].lo,&normal)) return 0;
    return normal;
}

/* Fixed-width SPLITv1 fields, little endian on the only target (AArch64 LE).
 * Assembly validated the stock continuation and selector/span relationship. */
struct split {
    uint8_t tag[16]; uint32_t version, size; uint64_t selector, span;
    uint32_t code0, code1;
    uint64_t shim, shim_size, fd_size, app, app_size, total;
    uint8_t sha[32];
};
_Static_assert(sizeof(struct split)==128 && offsetof(struct split,sha)==96,"SPLIT ABI");
static int fits(uint64_t off, uint64_t len, uint64_t total) {
    return off <= total && len <= total-off;
}
uintptr_t linux_target(const void *dt, uintptr_t base, const struct split *m, size_t mem) {
    uint64_t total = m->total, sh = m->shim, size = m->shim_size;
    if (total >= 0x6000000 || (total & 4095) || total > UINTPTR_MAX-base ||
        !fits(m->selector,mem,total) || sh != m->selector+mem ||
        size < 64 || size > 0x100000 || (size & 15) || m->fd_size != 0x300000 ||
        !fits(sh,size+0x300000,total) || m->app != sh+size+0x300000 ||
        m->app_size < 64 || !fits(m->app,m->app_size,total)) return 0;
    if (PianoBootRequestSelect((const void *)(base+m->selector-8192),m->sha) != PIANO_BOOT_REQUEST_LINUX) return 0;
    const uint8_t *guard = (const void *)(base+sh);
    uint64_t guard_size = size+0x300000;
    if (memcmp(guard+56,"ARMd",4) || memcmp(guard+16,&guard_size,8)) return 0;
    return dada_environment(dt,(uintptr_t)dt,base,base+total,base+sh,base+sh+guard_size) ? base+sh : 0;
}
