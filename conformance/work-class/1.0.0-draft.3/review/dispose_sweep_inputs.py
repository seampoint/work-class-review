"""Original November 7 DISPOSE matrix construction, retained for successor diagnostics.

Source copied from the hash-verified original sweep; runtime orchestration is separate.
`run` is injected by the verifier for paired prior-state checks. This is differential
coverage, not an independent expected-result oracle. The original P3/P4 omitted-attempt
limit slice is deliberately retained and labelled; corrected cases are added separately.
"""
from pathlib import Path
import sys,os,json,copy,itertools,hashlib
HERE=Path(__file__).resolve().parent
W=str(HERE.parents[3]);D3=str(HERE.parent)
import recovery_fixture as rec
from reservation_fixture import host_and_event,request,native
from corpus_common import digest
facts=rec.facts_for("2"); H=facts['history']

def agree(req):
    p,t=run([req],'py')[0],run([req],'ts')[0]
    if p!=t: raise SystemExit('prior disagreement at '+req['event']['id'])
    return p['state']

def with_policy(state):
    return rec.policy_issue(facts,state)[1]['state']

def head(state):
    rows=state['core']['recovery']['dispositions']; ids={r['supersedes'] for r in rows}
    live=[r for r in rows if r['id'] not in ids]; return live[0]['id'] if live else None

def priors():
    p={}
    p['P0-unknown']=with_policy(rec.disputed(facts))
    p['P1-effect-retained']=with_policy(rec.disputed(facts,result_kind='EFFECT'))
    _,res=rec.reserve(facts,rec.registered(facts)); before=res['state']
    n=native(facts,'UNKNOWN','native-x',completion_mismatch=True,mismatch_reason='NATIVE_REQUEST_MISMATCH')
    for f in n['request']['fields']:
        if f['name']=='amount': f['value']['value']='3'
    ev,ho=host_and_event(facts,'SETTLE','x-settle',before['core']['revision'],{'native':n,'histories':[H]},administration=False)
    p['P2-changed-request']=with_policy(agree(request(before,ev,ho)))
    s=p['P0-unknown']; pd=s['core']['recovery']['policies'][0]['policy_digest']
    p['P3-after-accept']=agree(rec.dispose_request(facts,s,'ACCEPT_UNRESOLVED',event_id='prior-accept',policy_digest=pd,evidence=rec.evidence_for(facts,s,attempts=2)))
    p['P4-after-leave']=agree(rec.dispose_request(facts,s,'LEAVE_UNRESOLVED',event_id='prior-leave',evidence=rec.evidence_for(facts,s,attempts=2)))
    return p

SETTLE=facts['budget']['reservation_policy']['settlement']; NOEFF=facts['budget']['reservation_policy']['no_effect']

def attempts(state, shape, effect):
    req=rec.native_request(state)
    spec={'a1':[('1',False)],'a2':[('1',False),('1',False)],'a3':[('3',False)],'a4':[('1',False),('1',True)],'a5':[('1',True),('1',True)]}[shape] if not shape.startswith('max') else [(shape[3:],False)]
    rows=[]
    for i,(m,ne) in enumerate(spec):
        rows.append({"id":"attempt-"+str(i+1),"attempt_digest":digest("recovery-attempt-evidence",{"request":req,"attempt":str(i+1)}),
            "executor":facts["authority_a"]["proposal"]["executor"]["actor"],"connector":"payment-connector",
            "request_digest":digest("reservation-native-request",req),"maximum_executions":m,
            "effect_ids":["effect-1"] if effect and i==0 and not ne else [],"no_effect":ne})
    return rows

def evidence(state, R, C, RO, CI, A, N, S):
    target=rec.target_for(state); req=rec.native_request(state)
    noeff = R=='ESTABLISH_NO_EFFECT' or (R=='LEAVE_UNRESOLVED' and C=='NO_EFFECT_ESTABLISHED')
    sel=NOEFF if noeff else SETTLE
    outs=[]
    if N in ('effect','effect-noattempt'):
        o=native(facts,'EFFECT','native-recovery-established',reservation_id=target['reservation'],request_record=req); o.update(provider=sel['provider'],source=sel['source']); outs=[o]
    elif N=='noeffect':
        o=native(facts,'NO_EFFECT','native-recovery-established',reservation_id=target['reservation'],request_record=req); o.update(provider=sel['provider'],source=sel['source']); outs=[o]
    elif N=='unknown':
        o=native(facts,'UNKNOWN','native-recovery-unknown',reservation_id=target['reservation'],request_record=req); o.update(provider=sel['provider'],source=sel['source']); outs=[o]
    retained=[x["native"] for x in state["core"]["effects"] if x["reservation"]==target["reservation"]]
    retained+=[x for d in state["core"]["recovery"]["dispositions"] if d["target"]==target for x in d["evidence"]["native_outcomes"]]
    rf={digest("recovery-fact",rec.normalize_native(x)) for x in retained}
    cov=sorted(rf|{digest("recovery-fact",rec.normalize_native(x)) for x in outs})
    return {"id":"provider-adjudication-1",**copy.deepcopy(sel),"record_type":"RECOVERY_ADJUDICATION",
        "record_digest":digest("provider-recovery-record",{"target":target,"k":[R,C,RO,CI,A,N,S]}),
        "evidence_ref":"authenticated-provider-complete-attempt-inventory","provider_revision":"2","target":target,"request":req,
        "covered_evidence_digests":cov,"superseded_evidence_digests":sorted(rf) if S=='all' else [],
        "attempts":attempts(state,A,N=='effect'),"conclusion":C,"native_outcomes":outs,
        "rules_out_past_and_future_effects":RO,"complete_attempt_inventory":CI}

def history(kind, ev):
    if kind=='base': return copy.deepcopy(H)
    if kind=='corr':
        e=[x for x in ev['native_outcomes'] if x['outcome']=='EFFECT']
        return rec.established_history(facts,e[0]) if e else None
    if kind=='missing': return None
    import importlib.util
    if kind in ('unavail','conflict'):
        v={"budget_digest":H["budget_digest"],"provider":H["provider"],"source":H["source"],"status":"UNAVAILABLE","as_of":None,"complete":False,"revision":None,"journal":None,"evidence_ref":"history-unavailable"}
        if kind=='conflict': v['status']='CONFLICT'
        return v
    v=copy.deepcopy(H)
    if kind=='stale': v['as_of']='2026-09-10T04:20:00Z'
    if kind=='incomplete': v['complete']=False
    return v

def build(state, pname, R, C, RO, CI, A, N, S, Hk, PE='none', eid='dispose-sweep'):
    ev=evidence(state,R,C,RO,CI,A,N,S)
    h=history(Hk,ev)
    if h is None and Hk!='missing': return None
    pd=state['core']['recovery']['policies'][0]['policy_digest'] if R=='ACCEPT_UNRESOLVED' else None
    req=rec.dispose_request(facts,state,R,event_id=eid,evidence=ev,policy_digest=pd,supersedes=head(state),histories=[] if Hk=='missing' else [h])
    if PE!='none':
        t=rec.target_for(state)
        rd={'other':digest('recovery-evidence',{'x':'1'}),'packet':digest('recovery-evidence',ev),
            'covered':(ev['covered_evidence_digests'] or [digest('recovery-evidence',{'y':'2'})])[0]}[PE]
        req['host_evidence']['recovery']['pending_evidence']=[{'target':t,'record_digest':rd,'kind':'RECOVERY_EVIDENCE','provider':ev['provider'],'source':ev['source']}]
    return req

def key(k): return '|'.join(map(str,k))

def matrix(P):
    R_=['ESTABLISH_EFFECT','ESTABLISH_NO_EFFECT','ACCEPT_UNRESOLVED','LEAVE_UNRESOLVED']
    C_=['EFFECT_ESTABLISHED','NO_EFFECT_ESTABLISHED','UNRESOLVED']
    for pname,state in P.items():
        S_=['all','none'] if pname in ('P1-effect-retained','P2-changed-request') else ['all']
        for R,C,RO,CI,A,N,S,Hk in itertools.product(R_,C_,[False,True],[True,False],['a1','a2','a3','a4','a5'],['none','effect','noeffect','unknown'],S_,['base','corr','unavail','stale','incomplete','conflict','missing']):
            yield ('main',pname,R,C,RO,CI,A,N,S,Hk,'none'),state
        for R,N,CI,Hk,PE in itertools.product(R_,['none','effect'],[True,False],['base','corr'],['other','packet','covered']):
            C={'ESTABLISH_EFFECT':'EFFECT_ESTABLISHED','ESTABLISH_NO_EFFECT':'NO_EFFECT_ESTABLISHED'}.get(R,'UNRESOLVED')
            yield ('pending',pname,R,C,R=='ESTABLISH_NO_EFFECT',CI,'a2',N,'all',Hk,PE),state
        for R,A,CI,N in itertools.product(R_,['max4096','max4097','max5000','max100000000000000000000'],[True,False],['none','effect']):
            C={'ESTABLISH_EFFECT':'EFFECT_ESTABLISHED','ESTABLISH_NO_EFFECT':'NO_EFFECT_ESTABLISHED'}.get(R,'UNRESOLVED')
            yield ('limits',pname,R,C,R=='ESTABLISH_NO_EFFECT',CI,A,N,'all','corr' if N=='effect' else 'base','none'),state
