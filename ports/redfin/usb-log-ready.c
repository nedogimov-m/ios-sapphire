/* Pure unhooked state/codec for usb-log-ready.h. No hardware-start adapter. */
#include "usb-log-ready.h"
#include <sys/errno.h>
#include <string.h>

static const uint8_t rf_ulr_magic[8] = {'R','F','L','G','v','0','0','1'};

static uint32_t rf_ulr_get32(const uint8_t *p)
{
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
}
static uint64_t rf_ulr_get64(const uint8_t *p)
{
    return (uint64_t)rf_ulr_get32(p) << 32 | rf_ulr_get32(p + 4);
}
static void rf_ulr_put32(uint8_t *p, uint32_t n)
{
    p[0] = (uint8_t)(n >> 24); p[1] = (uint8_t)(n >> 16);
    p[2] = (uint8_t)(n >> 8); p[3] = (uint8_t)n;
}
static void rf_ulr_put64(uint8_t *p, uint64_t n)
{
    rf_ulr_put32(p, (uint32_t)(n >> 32)); rf_ulr_put32(p + 4, (uint32_t)n);
}
static bool rf_ulr_canonical(const struct rf_ulr_message *m)
{
    if (!m || !m->boot_nonce || !m->cookie || m->kind < RF_ULR_HELLO ||
        m->kind > RF_ULR_MARKER_ACK) return false;
    if (m->kind <= RF_ULR_HELLO_ACK)
        return m->sequence == 1 && !m->address && !m->operation && !m->value;
    return m->sequence >= 2 && m->sequence <= RF_ULR_MAX_MARKERS + 1 &&
        m->address && m->address < (UINT64_C(1) << 36) && !(m->address & 3) &&
        ((m->operation == RF_ULR_READ32 && !m->value) || m->operation == RF_ULR_WRITE32);
}
int rf_ulr_encode(const struct rf_ulr_message *m, uint8_t *out, size_t bytes)
{
    if (!out || bytes < RF_ULR_BYTES || !rf_ulr_canonical(m)) return EINVAL;
    memcpy(out, rf_ulr_magic, sizeof(rf_ulr_magic));
    rf_ulr_put32(out + 8, m->kind); rf_ulr_put32(out + 12, m->sequence);
    rf_ulr_put64(out + 16, m->boot_nonce); rf_ulr_put64(out + 24, m->cookie);
    rf_ulr_put64(out + 32, m->address); rf_ulr_put32(out + 40, m->operation);
    rf_ulr_put32(out + 44, m->value);
    return 0;
}
int rf_ulr_decode(const uint8_t *p, size_t bytes, struct rf_ulr_message *out)
{
    if (!p || !out || bytes != RF_ULR_BYTES || memcmp(p, rf_ulr_magic, sizeof(rf_ulr_magic)))
        return EBADMSG;
    struct rf_ulr_message m = {
        rf_ulr_get32(p + 8), rf_ulr_get32(p + 12), rf_ulr_get64(p + 16),
        rf_ulr_get64(p + 24), rf_ulr_get64(p + 32), rf_ulr_get32(p + 40), rf_ulr_get32(p + 44)
    };
    if (!rf_ulr_canonical(&m)) return EBADMSG;
    *out = m;
    return 0;
}
void rf_ulr_abort(struct rf_ulr_session *s, int error)
{
    if (!s || s->phase == RF_ULR_FAILED) return;
    s->error = error > 0 ? (uint32_t)error : ECANCELED;
    s->phase = RF_ULR_FAILED;
}
int rf_ulr_poll(struct rf_ulr_session *s, uint64_t now)
{
    if (!s || s->phase == RF_ULR_EMPTY) return EINVAL;
    if (s->phase == RF_ULR_FAILED) return (int)s->error;
    if (now < s->last_time) { rf_ulr_abort(s, EINVAL); return EINVAL; }
    s->last_time = now;
    if (now >= s->lease_end || now >= s->request_end) {
        rf_ulr_abort(s, ETIMEDOUT); return ETIMEDOUT;
    }
    return 0;
}
static uint64_t rf_ulr_deadline(uint64_t now, uint64_t end, uint64_t interval)
{
    return end - now < interval ? end : now + interval;
}
int rf_ulr_begin(struct rf_ulr_session *s, uint64_t nonce, uint64_t cookie,
    uint32_t interface_index, uint64_t now, uint64_t lease_end, uint8_t out[RF_ULR_BYTES])
{
    if (!s) return EINVAL;
    if (s->phase != RF_ULR_EMPTY || s->boot_nonce || s->cookie) return EBUSY;
    if (!nonce || !cookie || !interface_index || !out || lease_end <= now ||
        lease_end - now > RF_ULR_MAX_LEASE_NS) {
        rf_ulr_abort(s, EINVAL); return EINVAL;
    }
    s->boot_nonce = nonce; s->cookie = cookie; s->interface_index = interface_index;
    s->lease_end = lease_end; s->last_time = now;
    s->request_end = rf_ulr_deadline(now, lease_end, RF_ULR_HOST_TIMEOUT_NS);
    s->pending = (struct rf_ulr_message){RF_ULR_HELLO, 1, nonce, cookie, 0, 0, 0};
    s->phase = RF_ULR_HELLO_TX;
    return rf_ulr_encode(&s->pending, out, RF_ULR_BYTES);
}
int rf_ulr_marker(struct rf_ulr_session *s, uint64_t address, uint32_t operation,
    uint32_t value, uint64_t now, uint8_t out[RF_ULR_BYTES])
{
    int error = rf_ulr_poll(s, now);
    if (error) return error;
    if (s->phase != RF_ULR_READY) return EBUSY;
    if (s->markers == RF_ULR_MAX_MARKERS) { rf_ulr_abort(s, E2BIG); return E2BIG; }
    struct rf_ulr_message m = {RF_ULR_MARKER, s->markers + 2,
        s->boot_nonce, s->cookie, address, operation, value};
    if (!out || !rf_ulr_canonical(&m)) return EINVAL;
    s->pending = m; s->markers++;
    s->request_end = rf_ulr_deadline(now, s->lease_end, RF_ULR_MARKER_TIMEOUT_NS);
    s->phase = RF_ULR_MARKER_TX;
    return rf_ulr_encode(&s->pending, out, RF_ULR_BYTES);
}
static bool rf_ulr_same(const struct rf_ulr_message *a, const struct rf_ulr_message *b, uint32_t kind)
{
    return a->kind == kind && a->sequence == b->sequence &&
        a->boot_nonce == b->boot_nonce && a->cookie == b->cookie &&
        a->address == b->address && a->operation == b->operation && a->value == b->value;
}
int rf_ulr_tx_completed(struct rf_ulr_session *s, const uint8_t *p, size_t bytes,
    uint32_t frame_bytes, int completion_error, uint64_t now)
{
    int error = rf_ulr_poll(s, now);
    if (error) return error;
    if (s->phase != RF_ULR_HELLO_TX && s->phase != RF_ULR_MARKER_TX) return EALREADY;
    struct rf_ulr_message message;
    if (completion_error || frame_bytes != RF_ULR_FRAME_BYTES) {
        rf_ulr_abort(s, EIO); return EIO;
    }
    if (rf_ulr_decode(p, bytes, &message) || !rf_ulr_same(&message, &s->pending, s->pending.kind)) {
        rf_ulr_abort(s, EPROTO); return EPROTO;
    }
    s->phase = s->phase == RF_ULR_HELLO_TX ? RF_ULR_HELLO_WAIT : RF_ULR_MARKER_WAIT;
    return 0;
}
static int rf_ulr_reject(struct rf_ulr_session *s)
{
    if (++s->rejected >= RF_ULR_MAX_REJECTED) rf_ulr_abort(s, EBADMSG);
    return EBADMSG;
}
int rf_ulr_ack(struct rf_ulr_session *s, uint32_t interface_index, uint32_t source_ipv4,
    uint16_t source_port, uint16_t destination_port, const uint8_t *p, size_t bytes, uint64_t now)
{
    /* Do not consume normal traffic or advance any deadline/state for it. */
    if (destination_port != RF_ULR_PORT) return ENOMSG;
    int error = rf_ulr_poll(s, now);
    if (error) return error;
    struct rf_ulr_message message;
    if (interface_index != s->interface_index || source_ipv4 != RF_ULR_HOST_IPV4 ||
        source_port != RF_ULR_PORT || rf_ulr_decode(p, bytes, &message) ||
        !rf_ulr_same(&message, &s->pending, s->pending.kind + 1)) return rf_ulr_reject(s);
    if (s->phase == RF_ULR_HELLO_TX || s->phase == RF_ULR_MARKER_TX) return EAGAIN;
    if (s->phase == RF_ULR_READY || s->phase == RF_ULR_MARKER_ACKED) return EALREADY;
    if (s->phase == RF_ULR_HELLO_WAIT) {
        s->phase = RF_ULR_READY; s->request_end = s->lease_end;
    } else if (s->phase == RF_ULR_MARKER_WAIT) {
        s->phase = RF_ULR_MARKER_ACKED;
    } else return EPROTO;
    return 0;
}
bool rf_ulr_listener_ready(struct rf_ulr_session *s, uint64_t now)
{
    return !rf_ulr_poll(s, now) && s->phase >= RF_ULR_READY && s->phase <= RF_ULR_MARKER_ACKED;
}
int rf_ulr_take_marker(struct rf_ulr_session *s, uint64_t address,
    uint32_t operation, uint32_t value, uint64_t now)
{
    int error = rf_ulr_poll(s, now);
    if (error) return error;
    if (s->phase != RF_ULR_MARKER_ACKED) return EAGAIN;
    if (s->pending.address != address || s->pending.operation != operation || s->pending.value != value)
        return EINVAL;
    s->phase = RF_ULR_READY; s->request_end = s->lease_end;
    return 0;
}
