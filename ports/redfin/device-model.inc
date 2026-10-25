/* SPDX-License-Identifier: MIT */
/* Physical model/SKU is separate from the installed iPhone10,3 userland ABI. */
static void redfin_publish_model(IOService *platform, IOService *provider)
{
    IORegistryEntry *root = IORegistryEntry::fromPath("/",gIODTPlane);
    IORegistryEntry *chosen = IORegistryEntry::fromPath("/chosen",gIODTPlane);
    if (root && chosen) {
        OSData *model = OSDynamicCast(OSData,root->getProperty("model-number"));
        OSData *mirror = OSDynamicCast(OSData,chosen->getProperty("model-number"));
        OSData *marker = OSDynamicCast(OSData,chosen->getProperty("redfin-identity-version"));
        uint32_t version = 0;
        if (marker && marker->getLength() == sizeof(version))
            memcpy(&version,marker->getBytesNoCopy(),sizeof(version));
        if (version == 1 && (model || mirror)) {
            bool valid = model && mirror && model->getLength() == mirror->getLength() &&
                model->getLength() >= 5 && model->getLength() <= 17;
            const uint8_t *bytes = valid ? (const uint8_t *)model->getBytesNoCopy() : NULL;
            if (valid) {
                valid = !bytes[model->getLength()-1] &&
                    !memcmp(bytes,mirror->getBytesNoCopy(),model->getLength());
                for (unsigned i=0; valid && i+1<model->getLength(); ++i)
                    valid = (bytes[i]>='0' && bytes[i]<='9') || (bytes[i]>='A' && bytes[i]<='Z');
            }
            bool published = valid && provider &&
                platform->setProperty("IOPlatformModelNumber",(const char *)bytes) &&
                provider->setProperty("IOPlatformModelNumber",(const char *)bytes);
            IOLog("REDFIN MODEL: physical-model-published=%u valid=%u\n",published,valid);
        }
    }
    if (chosen) chosen->release();
    if (root) root->release();
}
