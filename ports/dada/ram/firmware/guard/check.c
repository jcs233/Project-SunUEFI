/* SPDX-License-Identifier: BSD-2-Clause
 * Plain function shared by the freestanding arm64 boot shim and host tests.
 * Arm64 boot protocol: x0 points to an aligned DTB, <= 2 MiB, in normal RAM.
 * Do not copy a foreign memory map into the DT. Only accept positive evidence
 * for the scratch windows that the pinned board firmware will actually use. */
#include <libfdt.h>
#include <stdint.h>

struct window { uint64_t lo, hi; };
static const struct window scratch[] = {
    {0xa7000000, 0xa8000000}, /* FD, page tables, stack and firmware scratch */
    {0xb90c0000, 0xd4e23000}, /* exact contiguous, audited DXE heap */
};
static int overlaps(uint64_t a, uint64_t b, uint64_t c, uint64_t d)
{ return a < b && c < d && a < d && c < b; }
static int busy(uint64_t lo, uint64_t size)
{
    if (size > UINT64_MAX-lo) return 1;
    for (unsigned i=0; i<2; ++i)
        if (overlaps(lo,lo+size,scratch[i].lo,scratch[i].hi)) return 1;
    return 0;
}
static uint64_t val(const fdt32_t *p)
{ return ((uint64_t)fdt32_to_cpu(p[0])<<32) | fdt32_to_cpu(p[1]); }
int dada_check(const void *fdt, uint64_t image, uint64_t end, uint64_t dtaddr)
{
    if (!fdt || (dtaddr & 7) || !dtaddr || fdt_check_header(fdt)) return 1;
    unsigned len = fdt_totalsize(fdt);
    if (len < 40 || len > 0x200000 || len > UINT64_MAX-dtaddr || fdt_check_full(fdt,len)) return 2;
    if ((image & 4095) || end <= image || end-image > 0x400000 ||
        busy(image,end-image) || busy(dtaddr,len) || overlaps(image,end,dtaddr,dtaddr+len)) return 3;
    if (fdt_node_check_compatible(fdt,0,"qcom,sun") || fdt_address_cells(fdt,0)!=2 || fdt_size_cells(fdt,0)!=2) return 4;
    int res=fdt_path_offset(fdt,"/reserved-memory"), l, n;
    if (res<0 || fdt_address_cells(fdt,res)!=2 || fdt_size_cells(fdt,res)!=2 ||
        !fdt_getprop(fdt,res,"ranges",&l) || l!=0) return 5;
    int covered=0;
    fdt_for_each_subnode(n,fdt,0) {
        const char *type=fdt_getprop(fdt,n,"device_type",&l);
        if (!type || l!=7 || memcmp(type,"memory",7)!=0) continue;
        const char *status=fdt_getprop(fdt,n,"status",&l);
        if (status && !(l==5 && !memcmp(status,"okay",5)) && !(l==3 && !memcmp(status,"ok",3))) continue;
        const fdt32_t *p=fdt_getprop(fdt,n,"reg",&l);
        if (!p || l<=0 || l%16) return 6;
        for (int i=0; i<l/4; i+=4) {
            uint64_t lo=val(p+i), bytes=val(p+i+2);
            if (bytes>UINT64_MAX-lo) return 7;
            for (unsigned j=0; j<2; ++j)
                if (lo<=scratch[j].lo && lo+bytes>=scratch[j].hi) covered |= 1<<j;
        }
    }
    if (covered!=3) return 8;
    int count=fdt_num_mem_rsv(fdt);
    if (count<0) return 9;
    for (int i=0; i<count; ++i) {
        uint64_t lo, bytes;
        if (fdt_get_mem_rsv(fdt,i,&lo,&bytes) || busy(lo,bytes)) return 10;
    }
    int splash=fdt_subnode_offset(fdt,res,"splash_region"), fb=0;
    fdt_for_each_subnode(n,fdt,res) {
        const fdt32_t *p=fdt_getprop(fdt,n,"reg",&l);
        if (!p) { if(l!=-FDT_ERR_NOTFOUND) return 11; continue; } /* Linux size-only allocation, not a fixed address */
        if (l%16) return 11;
        for (int i=0; i<l/4; i+=4) {
            uint64_t lo=val(p+i), bytes=val(p+i+2);
            if (busy(lo,bytes)) return 12;
            if (n==splash && lo==0xfc800000 && bytes==0x02b00000) fb=1;
        }
    }
    return fb ? 0 : 13;
}

/* Called only when the full tree passed validation. Do not issue platform
 * reset calls on the basis of an unvalidated or wrong-board tree. */
int dada_can_reset(const void *dt)
{
    if (fdt_node_check_compatible(dt,0,"qcom,sun")) return 0;
    int n=fdt_node_offset_by_compatible(dt,-1,"arm,psci-1.0"), len;
    if (n<0) return 0;
    const char *s=fdt_getprop(dt,n,"method",&len);
    return s && len==4 && !memcmp(s,"smc",4);
}
