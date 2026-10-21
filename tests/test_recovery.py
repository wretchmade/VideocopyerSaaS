"""Preserve D's accepted-request and immutable-clock boundaries without paid requests."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from app.workbench_d.commercial.engine import Engine
from app.workbench_d.commercial.ledger import Ledger

def test_remote_dispatch_claim_is_once_and_survives_new_store(tmp_path):
    e=Engine(tmp_path);p=e.create({'commandId':'project','document':{}});l=Ledger(e.store)
    b=l.authorize({'commandId':'budget','projectId':p['projectId'],'revision':0,'account':'test','currency':'CNY','limitMicros':1000000,'concurrency':1})
    build={'id':'build','project':p['projectId'],'revision':0};task={'id':'generation','budget':b['budgetId'],'max_cost_micros':500000}
    r=l.reserve(build,task,'test',{'prompt':'x'},'CNY');assert l.claim_dispatch(r['id']);assert not l.claim_dispatch(r['id'])
    recovered=Ledger(Engine(tmp_path).store)
    assert recovered.lookup(build,task,{'prompt':'x'})['state']=='submitting'
    assert not recovered.claim_dispatch(r['id'])
    recovered.update(r['id'],'accepted',remote='provider-confirmed-id')
    assert recovered.lookup(build,task,{'prompt':'x'})['remote']=='provider-confirmed-id'
