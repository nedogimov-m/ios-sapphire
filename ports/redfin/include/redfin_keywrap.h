/* SPDX-License-Identifier: MIT */
/* RFC3394 key wrapping, using the caller's existing AES block provider.
 * No key material, fixed wrapping secret, heap or SIMD implementation here. */
#ifndef REDFIN_KEYWRAP_H
#define REDFIN_KEYWRAP_H
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <string.h>
#include <sys/errno.h>

#define REDFIN_KW_KEY_MAX 64u
typedef int (*redfin_kw_block_fn)(void *, const uint8_t[16], uint8_t[16]);

static inline void redfin_kw_clear(void *memory, size_t bytes)
{
    volatile uint8_t *p = (volatile uint8_t *)memory;
    while (bytes--) *p++ = 0;
}
static inline void redfin_kw_counter(uint8_t a[8], uint64_t counter)
{
    for (unsigned i = 0; i < 8; ++i) {
        a[7-i] ^= (uint8_t)counter;
        counter >>= 8;
    }
}
static inline bool redfin_kw_length(size_t length)
{return length >= 16 && length <= REDFIN_KW_KEY_MAX && !(length & 7u);}

static inline int redfin_kw_wrap(redfin_kw_block_fn encrypt, void *context,
    const uint8_t iv[8], const void *input, size_t length, void *output, size_t capacity)
{
    if (!encrypt || !iv || !input || !output || !redfin_kw_length(length) || capacity < length+8)
        return EINVAL;
    uint8_t a[8], block[16], result[16];
    uint8_t *wrapped = (uint8_t *)output;
    memmove(wrapped+8, input, length);
    memcpy(a, iv, sizeof(a));
    unsigned n = (unsigned)(length/8);
    int error = 0;
    for (unsigned j = 0; j < 6 && !error; ++j) for (unsigned i = 1; i <= n; ++i) {
        memcpy(block, a, 8); memcpy(block+8, wrapped+8*i, 8);
        error = encrypt(context, block, result);
        if (error) break;
        memcpy(a, result, 8); redfin_kw_counter(a, (uint64_t)n*j+i);
        memcpy(wrapped+8*i, result+8, 8);
    }
    if (!error) memcpy(wrapped, a, 8);
    else redfin_kw_clear(wrapped, length+8);
    redfin_kw_clear(a,sizeof(a)); redfin_kw_clear(block,sizeof(block)); redfin_kw_clear(result,sizeof(result));
    return error;
}
static inline int redfin_kw_unwrap(redfin_kw_block_fn decrypt, void *context,
    const uint8_t iv[8], const void *input, size_t length, void *output, size_t capacity)
{
    if (!decrypt || !iv || !input || !output || length < 24 ||
        !redfin_kw_length(length-8) || capacity < length-8) return EINVAL;
    uint8_t a[8], block[16], result[16];
    const uint8_t *wrapped = (const uint8_t *)input;
    uint8_t *key = (uint8_t *)output;
    memcpy(a, wrapped, 8); memmove(key, wrapped+8, length-8);
    unsigned n = (unsigned)((length-8)/8);
    int error = 0;
    for (int j = 5; j >= 0 && !error; --j) for (unsigned i = n; i > 0; --i) {
        memcpy(block, a, 8); redfin_kw_counter(block, (uint64_t)n*(unsigned)j+i);
        memcpy(block+8, key+8*(i-1), 8);
        error = decrypt(context, block, result);
        if (error) break;
        memcpy(a, result, 8); memcpy(key+8*(i-1), result+8, 8);
    }
    unsigned difference = 0;
    for (unsigned i = 0; i < 8; ++i) difference |= a[i] ^ iv[i];
    if (!error && difference) error = EBADMSG;
    if (error) redfin_kw_clear(key,length-8);
    redfin_kw_clear(a,sizeof(a)); redfin_kw_clear(block,sizeof(block)); redfin_kw_clear(result,sizeof(result));
    return error;
}
static inline void redfin_kw_class_iv(uint32_t key_class, uint8_t iv[8])
{
    /* RFC3394 permits an application-specific initial value. Bind the
     * opaque wrapped key to its actual native class, with the same +8 ABI. */
    iv[0]='R'; iv[1]='D'; iv[2]='K'; iv[3]=1;
    for (unsigned i=0;i<4;++i) iv[4+i]=(uint8_t)(key_class>>(24-8*i));
}
#endif
