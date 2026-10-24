/* A window-server restart replaces the HID consumer, not the SEC controller.
 * Keep the existing hardware session and deadline; discard old queue data
 * after the next real consumer registers. No sensing restart or rail write.
 */
static int
redfin_events_reconnect(struct redfin_events_state *state,const struct redfin_events_ops *ops,uint64_t deadline)
{
    redfin_events_release_all(state,redfin_events_emit_hid,NULL);
    state->synchronized=false;state->startup_reset=false;
    printf("REDFIN TOUCH EVENTS: HID consumer detached; retaining SPI session\n");
    while(mach_absolute_time()<deadline) {
        if(!redfin_events_owned())return EBUSY;
        if(!sweet_hid_redfin_touch_ready()){redfin_events_wait(20);continue;}
        redfin_events_delivery_failed=false;
        int error=0;
        for(unsigned batch=0;batch<4 && !state->synchronized;batch++) {
            if(mach_absolute_time()>=deadline)return ETIMEDOUT;
            error=redfin_events_batch(state,ops,false);
            if(error==EILSEQ || error==EOVERFLOW)error=redfin_events_resynchronize(state,ops);
            if(error)break;
        }
        if(error==EPIPE){redfin_events_wait(20);continue;}
        if(error)return error;
        if(!state->synchronized)return EBUSY;
        if(!sweet_hid_redfin_touch_ready()){state->synchronized=false;continue;}
        printf("REDFIN TOUCH EVENTS: HID consumer reconnected; stale contacts discarded\n");
        return 0;
    }
    return ETIMEDOUT;
}
