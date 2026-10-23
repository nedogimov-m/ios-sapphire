/* Adapted from oosexgang/hackios-xnu-kernel
 * 8e61187098f2c26c5daee8f9f72b6416aa64b9ab, xnu/files/bsd/sys/redwood_sta.h.
 * Redfin uses its native ath10k-compatible station and separate hardware owner.
 */
/*
 * Darwin-on-redfin: the station boundary.
 *
 * On one side whatever does the scanning and the joining with a radio: the station logic over
 * ath11k on the phone (wifi/lx in the repository). On the other whoever wants a network: the
 * Apple80211 requests of iOS's Wi-Fi side, answered in bsd/dev/redfin_apple80211.c, and the
 * kernel's own join of the network it was given in a file (bsd/dev/redfin_wifi.c). Frames do
 * not pass here, and neither does "the link is up": those go through bsd/sys/redfin_net.h,
 * which the station side calls itself.
 *
 * Between the two stands bsd/dev/redfin_sta.c: one thread, on which every call into the station
 * side is made, one at a time, and what the last scan heard, kept for whoever asks.
 *
 * Nothing but C's own types here: the station side is not compiled as XNU's code.
 */
#ifndef _SYS_REDFIN_STA_H_
#define _SYS_REDFIN_STA_H_

#include <stdbool.h>
#include <stdint.h>

#define REDFIN_STA_ELEMENTS_MOST       1024

/* One access point, as a scan heard it. */
struct redfin_sta_bss {
	uint8_t bssid[6];
	uint8_t ssid[32], ssid_length;
	uint16_t frequency;                     /* MHz */
	int16_t rssi;                           /* dBm */
	uint16_t beacon_interval;               /* in units of 1024 microseconds */
	uint16_t capability;                    /* the beacon's capability field */
	uint32_t age_ms;                        /* how long ago it was last heard */
	uint16_t elements_length;               /* the beacon's information elements as received: who asks */
	uint8_t elements[REDFIN_STA_ELEMENTS_MOST];    /* reads the network's protection out of them itself */
};

/* What to scan for. All zero: every channel, the radio's own way. */
struct redfin_sta_scan {
	uint8_t ssid[32], ssid_length;          /* ask for this network by name (a hidden one answers only then) */
	uint16_t frequencies[64], frequency_count;      /* only these channels */
	bool passive;                           /* only listen */
	uint16_t dwell_ms;                      /* on each channel; 0: the radio's own */
};

enum { REDFIN_STA_OPEN, REDFIN_STA_WPA2_PSK };

struct redfin_sta_join {
	uint8_t ssid[32], ssid_length;
	uint8_t bssid[6];                       /* all zero: the access point of that name heard best */
	int security;
	uint8_t pmk[32];                        /* WPA2 with a passphrase: the key made of the passphrase and the name ... */
	uint8_t passphrase[64], passphrase_length;      /* ... or, if this is not empty, the passphrase itself */
};

enum redfin_sta_phase { REDFIN_STA_OFF, REDFIN_STA_IDLE, REDFIN_STA_SCANNING, REDFIN_STA_JOINING, REDFIN_STA_JOINED };

struct redfin_sta_state {
	enum redfin_sta_phase phase;
	struct redfin_sta_bss bss;             /* the network joined or being joined */
	int last_error;                         /* why the last join failed or the network was lost (an errno); 0: it was not */
};

#define REDFIN_STA_CHANNEL_PASSIVE     1u      /* the radio may only listen there */
#define REDFIN_STA_CHANNEL_RADAR       2u      /* ... and has to look out for radar */

struct redfin_sta_channel {
	uint16_t frequency;                     /* MHz */
	uint16_t flags;
};

/*
 * What the station side supplies. All but state() are called on one thread, one at a time, and
 * may take as long as the thing takes: scan() returns when the scan is over, join() when frames
 * can pass or it is known why not. Each gives 0 or an errno.
 */
struct redfin_sta_ops {
	int (*power)(bool on);                  /* off: leave the network, stop the radio; on: start it */
	int (*scan)(const struct redfin_sta_scan *what);
	void (*heard)(void (*each)(const struct redfin_sta_bss *bss, void *context), void *context);   /* by the last scan */
	int (*join)(const struct redfin_sta_join *what);
	int (*leave)(void);
	void (*state)(struct redfin_sta_state *state);         /* on any thread; does not sleep */
	unsigned (*channels)(struct redfin_sta_channel *channels, unsigned most);      /* what the radio may tune to */
	uint8_t address[6];
};

/* What happens, said to whoever listens (the Apple80211 side). */
enum redfin_sta_event {
	REDFIN_STA_POWER,                      /* status: 1 on, 0 off */
	REDFIN_STA_SCAN_DONE,                  /* status: 0, or the scan's errno */
	REDFIN_STA_JOIN_DONE,                  /* status: 0, or the join's errno */
	REDFIN_STA_LINK,                       /* status: 1 a network is joined, 0 it has been left when asked,
	                                         * an errno: it was lost (the access point showed us the door) */
};

#ifdef KERNEL
/* ---- the station side ---- */
void     redfin_sta_attach(const struct redfin_sta_ops *ops);         /* NULL: it is going away (waits for a call under way) */
void     redfin_sta_lost(int error);                                   /* the network joined is gone by itself */

/* ---- who wants a network: each asks and returns; the outcome is an event. 0, or an errno ---- */
bool     redfin_sta_present(void);
int      redfin_sta_ask_power(bool on);
int      redfin_sta_ask_scan(const struct redfin_sta_scan *what);
int      redfin_sta_ask_join(const struct redfin_sta_join *what);
/* ... and joined again whenever the radio is turned on, until some other network is asked for */
int      redfin_sta_ask_join_standing(const struct redfin_sta_join *what);
int      redfin_sta_ask_leave(void);
bool     redfin_sta_busy(void);                                        /* something asked for is not over yet */
bool     redfin_sta_powered(void);
/* the `index`th access point the last scan heard: true, or false when there are not that many */
bool     redfin_sta_heard(unsigned index, struct redfin_sta_bss *bss);
void     redfin_sta_state(struct redfin_sta_state *state);
unsigned redfin_sta_channels(struct redfin_sta_channel *channels, unsigned most);
bool     redfin_sta_address(uint8_t *address);

/* ---- the listener: bsd/dev/redfin_apple80211.c ---- */
void     redfin_apple80211_event(enum redfin_sta_event event, int status);
void     redfin_apple80211_summary(void);                              /* what was asked in this run, to the log */
#endif

#endif
