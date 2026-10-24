/* Adapted from oosexgang/hackios-xnu-kernel
 * 8e61187098f2c26c5daee8f9f72b6416aa64b9ab, xnu/files/iokit/Kernel/RedwoodWLAN.cpp.
 * Redfin uses its native ath10k-compatible station and separate hardware owner.
 */
/*
 * RedfinWLAN: the registry entries by which iOS finds the Wi-Fi interface.
 *
 * en0 is made with the BSD interface KPI (bsd/dev/redfin_net.c) and has no IOKit object behind
 * it of its own; iOS looks for two, as IO80211Family would have made them:
 *
 *   - wifid's device is whatever service has the property IO80211InterfaceRole =
 *     "Infrastructure", and IO80211.framework binds to an interface through a service whose
 *     IOInterfaceName is the interface's name. The service has no user client, on purpose:
 *     the framework's attempt to open one fails, it says "Falling back to IOCTL path", and
 *     from then on every request is an ioctl on a socket, which bsd/dev/redfin_apple80211.c
 *     answers.
 *   - SystemConfiguration (SCNetworkInterfaceCopyAll) lists the network interfaces it finds as
 *     objects of the class IONetworkInterface, and calls one a Wi-Fi interface when its parent
 *     is of the class IO80211Controller; type, unit, name and built-in-ness are properties of
 *     the interface, the hardware address one of the controller. configd makes a network
 *     service (DHCP and the rest) for an interface it has listed, and only an interface with a
 *     service can be the one the system routes through -- which wifid waits for after a join
 *     ("failed to become routable interface") before Settings ticks the network.
 *
 * So: a controller of the class IO80211Controller under the platform, and below it one object
 * that is both, an IONetworkInterface with wifid's properties. Both classes are ours, named as
 * IO80211Family and IONetworkingFamily name theirs; neither has anything but properties.
 */

#include <IOKit/IOLib.h>
#include <IOKit/IOKitKeys.h>
#include <sys/proc.h>
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IOService.h>
#include <IOKit/IOUserClient.h>
#include <libkern/c++/OSData.h>
#include <libkern/c++/OSNumber.h>

extern "C" void RedfinWLANStart(const char * interface, const uint8_t * address);

class IO80211Controller : public IOService
{
	OSDeclareDefaultStructors(IO80211Controller);
};

OSDefineMetaClassAndStructors(IO80211Controller, IOService);

class IONetworkInterface : public IOService
{
	OSDeclareDefaultStructors(IONetworkInterface);
};

OSDefineMetaClassAndStructors(IONetworkInterface, IOService);

class RedfinWLAN : public IONetworkInterface
{
	OSDeclareDefaultStructors(RedfinWLAN);

public:
	virtual IOReturn newUserClient(task_t owningTask, void * securityID, UInt32 type, OSDictionary * properties,
	    IOUserClient ** handler) APPLE_KEXT_OVERRIDE;
};

OSDefineMetaClassAndStructors(RedfinWLAN, IONetworkInterface);

/* There is none (see the top); that somebody asked shows that the service was found. */
IOReturn
RedfinWLAN::newUserClient(task_t owningTask, void * securityID, UInt32 type, OSDictionary * properties, IOUserClient ** handler)
{
	static unsigned said;

	if (said++ < 8) {
		IOLog("RedfinWLAN: a user client of type %u is asked for: there is none\n", (unsigned) type);
	}
	return kIOReturnUnsupported;
}

/* attach, start, register: the service, or NULL */
static IOService *
publish(IOService * service, IOService * provider, const char * name)
{
	if (service == NULL || !service->attach(provider)) {
		OSSafeReleaseNULL(service);
		return NULL;
	}
	service->setName(name);
	if (!service->start(provider)) {
		service->detach(provider);
		service->release();
		return NULL;
	}
	service->registerService();
	return service;
}

/* Adapted from the same pinned upstream's MiniIONetworkStack.cpp.
 * configd's InterfaceNamer opens this before publishing Plugin:InterfaceNamer
 * (*QUIET* or *TIMEOUT*). SCNetworkInterfaceCopyAll waits for that key, so
 * the missing service blocks wifid and Settings even with a healthy en0.
 * Redfin already assigns its interface's BSD name through the native KPI;
 * unsupported renaming is refused without publishing a synthetic ready key.
 */
class IONetworkStack : public IOService
{
	OSDeclareDefaultStructors(IONetworkStack);

public:
	virtual bool start(IOService * provider) APPLE_KEXT_OVERRIDE;
};

OSDefineMetaClassAndStructors(IONetworkStack, IOService);

bool
IONetworkStack::start(IOService * provider)
{
	if (!IOService::start(provider)) {
		return false;
	}
	setProperty(kIOUserClientClassKey, "IONetworkStackUserClient");
	setName("IONetworkStack");
	registerService();
	return true;
}

class IONetworkStackUserClient : public IOUserClient
{
	OSDeclareDefaultStructors(IONetworkStackUserClient);

public:
	virtual bool start(IOService * provider) APPLE_KEXT_OVERRIDE;
	virtual IOReturn clientClose(void) APPLE_KEXT_OVERRIDE;
	virtual IOReturn setProperties(OSObject * properties) APPLE_KEXT_OVERRIDE;
};

OSDefineMetaClassAndStructors(IONetworkStackUserClient, IOUserClient);

bool
IONetworkStackUserClient::start(IOService * provider)
{
	char who[32] = "?";

	if (!IOUserClient::start(provider)) {
		return false;
	}
	/* whether the registry is quiet at this moment is what the namer goes on to ask */
	proc_selfname(who, sizeof(who));
	IOLog("RedfinNetworkStack: opened by %s; the registry's busy state is %u\n", who,
	    (unsigned) IOService::getServiceRoot()->getBusyState());
	return true;
}

IOReturn
IONetworkStackUserClient::clientClose(void)
{
	if (!isInactive()) {
		terminate();
	}
	return kIOReturnSuccess;
}

/* "Name this interface" (a dictionary: IONetworkStackUserCommand, IOPathMatch, IOInterfaceUnit). */
IOReturn
IONetworkStackUserClient::setProperties(OSObject * properties)
{
	static unsigned said;

	if (said++ < 4) {
		IOLog("RedfinNetworkStack: asked to name an interface: there are none of that kind\n");
	}
	return kIOReturnUnsupported;
}

/* * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * */

static void
redfin_network_stack_start(void)
{
	/* where the real one is: IOService:/IOResources/IONetworkStack */
	IOService * resources = IOService::getResourceService();
	IONetworkStack * stack = OSTypeAlloc(IONetworkStack);

	if (resources == NULL || stack == NULL || !stack->init() || !stack->attach(resources)) {
		OSSafeReleaseNULL(stack);
		IOLog("RedfinNetworkStack: cannot create the service\n");
		return;
	}
	if (!stack->start(resources)) {
		stack->detach(resources);
	}
	stack->release();
}

/* Once, when the interface of a radio exists. */
void
RedfinWLANStart(const char * interface, const uint8_t * address)
{
	redfin_network_stack_start();
	IOService * platform = IOService::getPlatform();
	IO80211Controller * controller = OSTypeAlloc(IO80211Controller);
	RedfinWLAN * wlan = OSTypeAlloc(RedfinWLAN);
	OSData * mac;
	OSNumber * number;

	if (platform == NULL || controller == NULL || wlan == NULL || !controller->init() || !wlan->init()) {
		OSSafeReleaseNULL(controller);
		OSSafeReleaseNULL(wlan);
		IOLog("RedfinWLAN: cannot create the services\n");
		return;
	}
	if ((mac = OSData::withBytes(address, 6)) != NULL) {
		controller->setProperty("IOMACAddress", mac);
		mac->release();
	}
	controller->setProperty("IOBuiltin", true);
	if ((controller = (IO80211Controller *) publish(controller, platform, "RedfinWLANController")) == NULL) {
		wlan->release();
		IOLog("RedfinWLAN: the controller did not start\n");
		return;
	}

	wlan->setProperty("IOInterfaceName", interface);
	wlan->setProperty("BSD Name", interface);
	wlan->setProperty("IOInterfaceNamePrefix", "en");
	if ((number = OSNumber::withNumber(6ULL, 32)) != NULL) {        /* IFT_ETHER */
		wlan->setProperty("IOInterfaceType", number);
		number->release();
	}
    unsigned unit = 0;
    for (const char *p = interface + 2; *p >= '0' && *p <= '9'; ++p) unit = unit * 10u + (unsigned)(*p - '0');
	if ((number = OSNumber::withNumber((unsigned long long)unit, 32)) != NULL) {
		wlan->setProperty("IOInterfaceUnit", number);
		number->release();
	}
	wlan->setProperty("IOBuiltin", true);
	wlan->setProperty("IOPrimaryInterface", true);
	wlan->setProperty("IO80211InterfaceRole", "Infrastructure");
	if (publish(wlan, controller, "RedfinWLAN") == NULL) {
		IOLog("RedfinWLAN: the service did not start\n");
	} else {
		wlan->release();
	}
	controller->release();
}
