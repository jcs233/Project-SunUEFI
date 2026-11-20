/* SPDX-License-Identifier: BSD-2-Clause. Only the string operations used by libfdt. */
#include <stddef.h>
void *memchr(const void *p,int c,size_t n) { const unsigned char *s=p; while(n--) { if(*s==(unsigned char)c) return (void*)s; ++s; } return NULL; }
int memcmp(const void *a,const void *b,size_t n) { const unsigned char *x=a,*y=b; while(n--) { if(*x!=*y) return *x-*y; ++x; ++y; } return 0; }
size_t strlen(const char *s) { const char *p=s; while(*p) ++p; return p-s; }
size_t strnlen(const char *s,size_t n) { size_t i=0; while(i<n && s[i]) ++i; return i; }
char *strrchr(const char *s,int c) { const char *v=NULL; do { if(*s==(char)c) v=s; } while(*s++); return (char*)v; }
