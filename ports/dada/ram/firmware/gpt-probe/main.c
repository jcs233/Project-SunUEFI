// SPDX-License-Identifier: BSD-2-Clause
// Report metadata on *already published* Block I/O handles. No ConnectController,
// filesystem, variable, or disk write calls. A valid result is not a resize plan.
#include <Uefi.h>
#include <Protocol/BlockIo.h>

static EFI_SYSTEM_TABLE *st;
static EFI_GUID block_io = EFI_BLOCK_IO_PROTOCOL_GUID;
static UINT8 *ha, *hb, *ta, *tb;
enum { MAX_ENTRIES = 256, ENTRY = 128, PAGE = 4096, ARRAY_PAGES = MAX_ENTRIES * ENTRY / PAGE };
struct extent { UINT64 start, end; };
static struct extent ranges[MAX_ENTRIES];

static VOID text(CHAR16 *s) { st->ConOut->OutputString(st->ConOut, s); }
static VOID number(UINT64 n) {
    CHAR16 buf[21]; UINTN i=20; buf[i]=0;
    do {buf[--i]=(CHAR16)('0'+n%10); n/=10;} while(n);
    text(buf+i);
}
static BOOLEAN equal(const UINT8 *a, const UINT8 *b, UINTN n) {
    while(n--) if(*a++!=*b++) return FALSE;
    return TRUE;
}
static BOOLEAN zero(const UINT8 *p, UINTN n) { while(n--) if(*p++) return FALSE; return TRUE; }
static UINT32 u32(const UINT8 *p) {return p[0] | (UINT32)p[1]<<8 | (UINT32)p[2]<<16 | (UINT32)p[3]<<24;}
static UINT64 u64(const UINT8 *p) {return u32(p) | (UINT64)u32(p+4)<<32;}
static BOOLEAN name_is(const UINT8 *p,const char *s) {
    for(UINTN i=0;i<36;i++){ if(p[2*i]!=(UINT8)*s || p[2*i+1])return FALSE; if(!*s)return TRUE; s++; }
    return FALSE;
}
static BOOLEAN crc(const UINT8 *buf,UINTN size,UINT32 expected) {
    UINT32 v=0; return !EFI_ERROR(st->BootServices->CalculateCrc32((VOID *)buf,size,&v)) && v==expected;
}
static BOOLEAN header(UINT8 *b,UINT64 here,UINT64 peer) {
    if(!equal(b,(const UINT8 *)"EFI PART",8)||u32(b+8)!=0x10000||u32(b+12)!=92||u32(b+20)||
       u64(b+24)!=here||u64(b+32)!=peer||zero(b+56,16)||u32(b+84)!=ENTRY)return FALSE;
    UINT32 saved=u32(b+16); for(UINTN i=16;i<20;i++)b[i]=0;
    return crc(b,92,saved);
}
static BOOLEAN read_at(EFI_BLOCK_IO_PROTOCOL *io,UINT32 id,UINT64 lba,UINTN bytes,VOID *dst) {
    return !EFI_ERROR(io->ReadBlocks(io,id,lba,bytes,dst));
}
static BOOLEAN inspect(EFI_BLOCK_IO_PROTOCOL *io) {
    EFI_BLOCK_IO_MEDIA *m=io->Media; UINT32 bs=m->BlockSize, id=m->MediaId; UINT64 last=m->LastBlock;
    if((bs!=512 && bs!=4096)||m->IoAlign>PAGE||(m->IoAlign && (m->IoAlign&(m->IoAlign-1)))||last<6||last==MAX_UINT64)return FALSE;
    if(!read_at(io,id,1,bs,ha)||!read_at(io,id,last,bs,hb)||!header(ha,1,last)||!header(hb,last,1))return FALSE;
    UINT64 first=u64(ha+40),end=u64(ha+48),pa=u64(ha+72),pb=u64(hb+72); UINT32 n=u32(ha+80);
    if(!n||n>MAX_ENTRIES||first>end||end>=last||pa<2||pa>=first||pb<=end||pb>=last||
       !equal(ha+40,hb+40,32)||!equal(ha+80,hb+80,12))return FALSE;
    UINTN arr=n*ENTRY, blocks=(arr+bs-1)/bs;
    if(blocks>first-pa||blocks>last-pb||!read_at(io,id,pa,blocks*bs,ta)||!read_at(io,id,pb,blocks*bs,tb)||
       !crc(ta,arr,u32(ha+88))||!equal(ta,tb,arr))return FALSE;
    UINTN count=0,nu=0,ne=0,nr=0; UINT64 us=0,ue=0;
    for(UINTN i=0;i<n;i++) {
        const UINT8 *p=ta+i*ENTRY; if(zero(p,16))continue;
        UINT64 a=u64(p+32),b=u64(p+40); if(a<first||a>b||b>end||zero(p+16,16))return FALSE;
        for(UINTN k=0;k<i;k++){const UINT8 *q=ta+k*ENTRY;if(!zero(q,16)&&equal(q+16,p+16,16))return FALSE;}
        UINTN j=count; while(j && a<ranges[j-1].start){ranges[j]=ranges[j-1];j--;}
        ranges[j].start=a;ranges[j].end=b;count++;
        if(name_is(p+56,"userdata")){nu++;us=a;ue=b;}
        ne+=name_is(p+56,"sunuefi_esp"); nr+=name_is(p+56,"sunuefi_root");
    }
    UINT64 next=first,gap=0;
    for(UINTN j=0;j<count;j++){ if(ranges[j].start<next)return FALSE; UINT64 g=ranges[j].start-next;if(g>gap)gap=g; next=ranges[j].end+1; }
    if(end+1-next>gap)gap=end+1-next;
    if(nu>1||ne>1||nr>1)return FALSE;
    text(L"DADA_GPT_OK sector=");number(bs);text(L" entries_used=");number(count);text(L" userdata=");number(nu);
    text(L" esp=");number(ne);text(L" root=");number(nr);text(L" max_gap_lbas=");number(gap);
    if(nu){text(L" userdata_first=");number(us);text(L" userdata_last=");number(ue);}
    text(L"\r\n"); return TRUE;
}
EFI_STATUS EFIAPI efi_main(EFI_HANDLE image,EFI_SYSTEM_TABLE *system) {
    (void)image;st=system;EFI_HANDLE *handles=NULL; UINTN nh=0,checked=0,rejected=0;
    EFI_PHYSICAL_ADDRESS mem=0; EFI_BOOT_SERVICES *bs=st->BootServices;
    EFI_STATUS status=bs->AllocatePages(AllocateAnyPages,EfiLoaderData,2+2*ARRAY_PAGES,&mem);
    if(EFI_ERROR(status))return status;
    ha=(UINT8 *)(UINTN)mem;hb=ha+PAGE;ta=hb+PAGE;tb=ta+ARRAY_PAGES*PAGE;
    text(L"DADA_GPT_BEGIN\r\n"); status=bs->LocateHandleBuffer(ByProtocol,&block_io,NULL,&nh,&handles);
    if(!EFI_ERROR(status)){
        for(UINTN i=0;i<nh;i++){
            EFI_BLOCK_IO_PROTOCOL *io=NULL;
            if(EFI_ERROR(bs->HandleProtocol(handles[i],&block_io,(VOID **)&io))||!io||!io->Media){rejected++;continue;}
            if(io->Media->LogicalPartition || !io->Media->MediaPresent)continue;
            if(inspect(io))checked++;else {rejected++;text(L"DADA_GPT_UNVERIFIED\r\n");}
        }
        bs->FreePool(handles);
    }
    bs->FreePages(mem,2+2*ARRAY_PAGES);
    text(L"DADA_GPT_DONE verified=");number(checked);text(L" unverified=");number(rejected);text(L"\r\n");
    return checked && !rejected ? EFI_SUCCESS : EFI_NOT_READY;
}
