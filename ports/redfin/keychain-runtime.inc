/* SPDX-License-Identifier: MIT */
/* Preferred MiniAppleKeyStore's wrap/unwrap ABI, adapted for Redfin's
 * persistent HFSX root, actual20H392 calls and portable AES provider.
 * AES256/RFC3394 uses persistent private material, not a fixed mixing key.
 * This software device bag does not emulate a Secure Enclave. */
#include <libkern/c++/OSData.h>
#include <libkern/crypto/aes.h>
#include "RedfinKeywrap.h"

static aes_encrypt_ctx redfin_kc_encrypt;
static aes_decrypt_ctx redfin_kc_decrypt;
static uint8_t redfin_kc_uuid[16];
static bool redfin_kc_attempted, redfin_kc_ready, redfin_kc_notified;
static IOReturn sweet_aks_struct_out(IOExternalMethodArguments *, const void *, uint32_t);
static uint32_t sweet_aks_der_pair(uint8_t *, const char *, uint8_t);

/* Platform expert invokes this before any userspace can inspect IORegistry.
 * Retain before removal: DT-backed OSData need not outlive its dictionary. */
void RedfinKeychainPrepare(IORegistryEntry *chosen)
{
    if (!chosen || __atomic_exchange_n(&redfin_kc_attempted, true, __ATOMIC_ACQ_REL)) return;
    OSData *data = OSDynamicCast(OSData, chosen->getProperty("redfin-keychain-material"));
    if (!data) return;
    data->retain();
    uint8_t material[56] = {};
    bool valid = data->getLength() == sizeof(material);
    if (valid) memcpy(material, data->getBytesNoCopy(), sizeof(material));
    chosen->removeProperty("redfin-keychain-material");
    bool removed = chosen->getProperty("redfin-keychain-material") == NULL;
    data->release();
    const uint8_t version[8] = {1,0,0,0,1,0,0,0};
    unsigned key_nonzero = 0, uuid_nonzero = 0;
    for (unsigned i=8;i<40;++i) key_nonzero |= material[i];
    for (unsigned i=40;i<56;++i) uuid_nonzero |= material[i];
    valid = valid && removed && !memcmp(material, version, sizeof(version)) && key_nonzero && uuid_nonzero;
    if (valid) {
        valid = !aes_encrypt_key(material+8,32,&redfin_kc_encrypt) &&
            !aes_decrypt_key(material+8,32,&redfin_kc_decrypt);
        if (valid) memcpy(redfin_kc_uuid,material+40,sizeof(redfin_kc_uuid));
    }
    redfin_kw_clear(material,sizeof(material));
    if (!valid) {
        redfin_kw_clear(&redfin_kc_encrypt,sizeof(redfin_kc_encrypt));
        redfin_kw_clear(&redfin_kc_decrypt,sizeof(redfin_kc_decrypt));
        redfin_kw_clear(redfin_kc_uuid,sizeof(redfin_kc_uuid));
    }
    __atomic_store_n(&redfin_kc_ready,valid,__ATOMIC_RELEASE);
    IOLog("REDFIN KEYCHAIN: private material accepted=%u removed-from-registry=%u software-AES256-RFC3394=1 SEP=0\n",
        valid,removed);
}
static int redfin_kc_encrypt_block(void *context, const uint8_t in[16], uint8_t out[16])
{
    const uint8_t zero[16] = {};
    return aes_encrypt_cbc(in,zero,1,out,(aes_encrypt_ctx *)context);
}
static int redfin_kc_decrypt_block(void *context, const uint8_t in[16], uint8_t out[16])
{
    const uint8_t zero[16] = {};
    return aes_decrypt_cbc(in,zero,1,out,(aes_decrypt_ctx *)context);
}
static IOReturn redfin_kc_transform(IOExternalMethodArguments *args, bool unwrap)
{
    if (!__atomic_load_n(&redfin_kc_ready,__ATOMIC_ACQUIRE)) return kIOReturnNotReady;
    size_t length = args->structureInputDescriptor ? args->structureInputDescriptor->getLength() :
        args->structureInputSize;
    if (args->scalarInputCount != 2 || !args->scalarInput ||
        (!unwrap && (!args->scalarOutput || args->scalarOutputCount<1)) ||
        args->scalarInput[0] != SWEET_AKS_SYSTEM_HANDLE ||
        args->scalarInput[1] > UINT32_MAX || (!unwrap && !redfin_kw_length(length)) ||
        (unwrap && (length < 24 || length > 72 || !redfin_kw_length(length-8))))
        return kIOReturnBadArgument;
    uint8_t input[72] = {}, output[72] = {}, iv[8] = {};
    IOReturn result = kIOReturnBadArgument;
    if (args->structureInputDescriptor) {
        if (args->structureInputDescriptor->readBytes(0,input,length) != length) goto done;
    } else {
        if (!args->structureInput) goto done;
        memcpy(input,args->structureInput,length);
    }
    {
        uint32_t key_class = (uint32_t)args->scalarInput[1];
        redfin_kw_class_iv(key_class,iv);
        int error = unwrap ? redfin_kw_unwrap(redfin_kc_decrypt_block,&redfin_kc_decrypt,iv,
            input,length,output,sizeof(output)) :
            redfin_kw_wrap(redfin_kc_encrypt_block,&redfin_kc_encrypt,iv,input,length,output,sizeof(output));
        if (error) {
            result = error == EBADMSG ? kIOReturnNotPermitted : kIOReturnBadArgument;
            goto done;
        }
        result = sweet_aks_struct_out(args,output,(uint32_t)(unwrap ? length-8 : length+8));
        if (result == kIOReturnSuccess) {
            if (!unwrap && args->scalarOutputCount >= 1) {
                args->scalarOutput[0] = key_class; args->scalarOutputCount = 1;
            } else args->scalarOutputCount = 0;
        }
    }
done:
    redfin_kw_clear(input,sizeof(input)); redfin_kw_clear(output,sizeof(output)); redfin_kw_clear(iv,sizeof(iv));
    return result;
}
static IOReturn redfin_kc_bag_uuid(IOExternalMethodArguments *args)
{
    if (!__atomic_load_n(&redfin_kc_ready,__ATOMIC_ACQUIRE)) return kIOReturnNotReady;
    args->scalarOutputCount = 0;
    return sweet_aks_struct_out(args,redfin_kc_uuid,sizeof(redfin_kc_uuid));
}
static IOReturn redfin_kc_configuration(IOExternalMethodArguments *args)
{
    uint8_t der[128] = {}; uint32_t n = 2;
    n += sweet_aks_der_pair(der+n,"bd",0);
    n += sweet_aks_der_pair(der+n,"gp",0);
    n += sweet_aks_der_pair(der+n,"mua",10);
    der[0]=0x31; der[1]=(uint8_t)(n-2);
    args->scalarOutputCount=0;
    return sweet_aks_struct_out(args,der,n);
}
