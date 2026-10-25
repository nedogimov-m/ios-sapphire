"""Bind resource readiness to the real asynchronous native command completion."""
from pathlib import Path
from ports.redfin.eagl_userland import replace_once


def adapt(text):
    methods=Path(__file__).with_name('metal-resource-completion.inc').read_text()
    for name in ('RedwoodMetalBuffer','RedwoodMetalTexture'):
        first=text.index('@interface '+name+' :');last=text.index('\n@end',first)
        chunk=text[first:last]
        brace=chunk.index('{')
        chunk=chunk[:brace+1]+'\n    dispatch_group_t _redfinActive;'+chunk[brace+1:]
        chunk+='\n- (BOOL)redfinWillSubmit;\n- (void)redfinDidFinish;\n'
        text=text[:first]+chunk+text[last:]
        first=text.index('@implementation '+name);last=text.index('\n@end',first)
        chunk=text[first:last]
        point=('- (BOOL)isComplete        { return YES; }\n- (void)waitUntilComplete { }' if name=='RedwoodMetalBuffer' else
               '- (BOOL)isComplete               { return YES; }\n- (void)waitUntilComplete        { }')
        chunk=replace_once(chunk,point,methods)
        # Every native superclass-deallocation path releases the group's own
        # reference. A submitted command retains its resources until it leaves.
        chunk=chunk.replace('[super dealloc];','if(_redfinActive)dispatch_release(_redfinActive);\n\t[super dealloc];')
        text=text[:first]+chunk+text[last:]
    point='NSMutableArray *_redfinResources;'
    text=replace_once(text,point,point+'\n    NSMutableArray *_redfinInFlightResources;')
    point='\t[_redfinResources release];'
    text=replace_once(text,point,point+'\n    [_redfinInFlightResources release];')
    point='- (void)redfinRetainResource:(id)resource\n{'
    text=replace_once(text,point,'''- (BOOL)redfinMarkResources
{
    _redfinInFlightResources=[[NSMutableArray alloc] initWithCapacity:_redfinResources.count];
    if(!_redfinInFlightResources)return NO;
    NSSet *unique=[NSSet setWithArray:_redfinResources];
    for(id resource in unique) {
        if(![resource isKindOfClass:[RedwoodMetalBuffer class]]&&![resource isKindOfClass:[RedwoodMetalTexture class]])continue;
        if(![resource redfinWillSubmit])return NO;
        [_redfinInFlightResources addObject:resource];
    }
    return YES;
}
- (void)redfinFinishResources
{
    for(id resource in _redfinInFlightResources)[resource redfinDidFinish];
    [_redfinInFlightResources removeAllObjects];
}

'''+point)
    point='\t\tif (_status>=RW_CB_COMMITTED) return;\n\t\tdispatch_group_enter(_redfinExecution);'
    text=replace_once(text,point,'''\t\tif (_status>=RW_CB_COMMITTED) return;
        if(![self redfinMarkResources]) {
            [self failWith:"native resource completion allocation failed"];
            [self redfinFinishResources];_redfinFinalized=YES;
            [self redwoodReturnSlot];[self redwoodDeliverHandlers];return;
        }
\t\tdispatch_group_enter(_redfinExecution);''')
    # Includes commands_begin refusal as well as the ordinary @finally path.
    # Do not alter the allocation-failure cleanup inserted immediately above.
    first=text.index('- (void)redfinExecute\n{');last=text.index('\n- (BOOL)runDraw:',first)
    chunk=text[first:last]
    if chunk.count('_redfinFinalized=YES;')!=2:raise ValueError('unreviewed command completion exits')
    chunk=chunk.replace('_redfinFinalized=YES;','[self redfinFinishResources];_redfinFinalized=YES;')
    return text[:first]+chunk+text[last:]
