"""Derive complete source-owned retained holdings checkpoint vectors."""
from corpus_common import candidate_pin
from holdings_fixture import lifecycle_base,dispatch_authorization
from lifecycle_factory import permitted_proposal,stateful_refusal,step_input
from equipment_dispatch_fixture import clock_transition


def retained_checkpoints():
    rows=[]
    for source_count in [32,33]:
        base=lifecycle_base(requirement_count=32,source_count=source_count)
        # For33sources this explicitly constructs the attacker-claimed historical
        # PERMITTED event. Direct authority is valid; lifecycle65-member issuance
        # is forbidden. Every ordinary record/hash is nevertheless recomputed.
        permitted=permitted_proposal(base)
        clock,result=clock_transition(permitted,revision='2',instant='2026-09-10T04:30:01Z')
        result['permit']=None
        expected=result if source_count==32 else stateful_refusal(permitted['state'],'STATE_INVALID')
        rows.append({'id':'HOLD-RETAINED-'+str(source_count+32)+'-CLOCK','operation':'step',
            'input':step_input(base,permitted['state'],clock),'expected':expected,
            'derivation':'A complete rehashed retained permit with'+str(source_count+32)+' combined source/holdings requirements '+
                ('admits public checkpoint restart.' if source_count==32 else 'is historically impossible under HOLD-007 and refuses STATE_INVALID before the next event, despite valid direct authority and correct ordinary hashes.')})
        if source_count==33:
            event,_=dispatch_authorization(base,permitted,event_id='forged65-authorize')
            rows.append({'id':'HOLD-RETAINED-65-AUTHORIZE','operation':'step',
                'input':step_input(base,permitted['state'],event),'expected':stateful_refusal(permitted['state'],'STATE_INVALID'),
                'derivation':'The same fully rehashed illegal retained permit cannot enter AUTHORIZE_DISPATCH. Historical permit admission precedes the new event combined-bound check.'})
    return {'candidate_pin':candidate_pin(),'status':'SOURCE_DERIVED_FROZEN_BEFORE_CONSUMER_COMPARISON','rows':rows}
