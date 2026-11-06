import os
import tempfile
from pathlib import Path

test_db = Path(tempfile.mkdtemp()) / 'test.db'
os.environ['DATABASE_URL'] = f'sqlite:///{test_db.as_posix()}'
os.environ['DEMO_PASSWORD'] = 'test-password'
os.environ['SESSION_SECRET'] = 'a-long-test-only-secret'
os.environ.pop('HINDSIGHT_API_KEY', None)

from fastapi.testclient import TestClient
import backend.app as module
from backend.app import app

client = TestClient(app)

def test_protected_and_login():
    assert client.get('/api/session').status_code == 401
    assert client.post('/api/login', json={'password':'wrong'}).status_code == 401
    assert client.post('/api/login', json={'password':'test-password'}).status_code == 200
    assert client.get('/api/session').status_code == 200

def test_recommendation_eligibility_and_unknowns():
    result = client.post('/api/recommendations', json={}).json()
    assert result['ranked'][0]['name'] == 'CleanPro'
    assert result['ranked'][0]['memory']['status'] == 'not_configured'
    new = next(v for v in result['ranked'] if v['name'] == 'NewVendor')
    assert new['metrics']['delivery'] == {'value':None,'sample':0}
    assert 'Limited' in new['confidence']
    assert any(v['name'] == 'Metro Hygiene' and 'Lead time exceeds deadline' in v['reasons'] for v in result['excluded'])
    assert any(v['name'] == 'Northstar Supplies' and 'Supplier not approved' in v['reasons'] for v in result['excluded'])
    empty = client.post('/api/recommendations',json={'budget':1}).json()
    assert empty['ranked'] == []

def test_outcome_and_replay():
    decision=client.post('/api/recommendations',json={}).json()
    before=decision['ranked'][0]
    out=client.post('/api/outcomes',json={'decision_id':decision['id'],'supplier_id':before['id'],'occurred_at':'2026-11-06','on_time':False,'quality_ok':True,'invoice_ok':True,'note':'Arrived one day late.'})
    assert out.status_code==200 and out.json()['memory_status']=='not_configured'
    replay=client.post('/api/replay/'+decision['id']).json()
    b=next(v for v in replay['before']['ranked'] if v['id']==before['id'])
    a=next(v for v in replay['after']['ranked'] if v['id']==before['id'])
    assert len(a['events'])==len(b['events'])+1
    assert a['metrics']['delivery']['sample']==b['metrics']['delivery']['sample']+1
    assert a['metrics']['delivery']['value']<b['metrics']['delivery']['value']
    assert out.json()['source'] in [e['source'] for e in a['events']]
    assert client.post('/api/decisions/'+decision['id']+'/review',json={'action':'approved'}).json()['status']=='approved'

def test_unsupported_product_and_invalid_outcome():
    r=client.post('/api/recommendations',json={'item':'Unsupported product'}).json()
    assert not r['ranked']
    assert all('No current quote for this item' in x['reasons'] for x in r['excluded'])
    assert client.post('/api/outcomes',json={'decision_id':r['id'],'supplier_id':'V-001','occurred_at':'2026-11-06','on_time':True,'quality_ok':True,'invoice_ok':True,'note':'Test'}).status_code==400

def test_memory_integration_and_outage(monkeypatch):
    calls=[]
    class Memory:
        def retain(self, **kwargs): calls.append(('retain',kwargs))
        def recall(self, **kwargs):
            calls.append(('recall',kwargs))
            from types import SimpleNamespace
            return SimpleNamespace(results=[SimpleNamespace(text='V-001 delivered late; source SRC-TEST')])
        def reflect(self, **kwargs): calls.append(('reflect',kwargs))
    monkeypatch.setattr(module,'memory_client',lambda:Memory())
    with module.Session.begin() as db:
        db.add(module.Event(id='EV-MEMTEST',supplier_id='V-001',po='PO-TEST',occurred_at='2026-11-06',source='SRC-TEST',on_time=False,quality_ok=True,invoice_ok=True,note='Delivered late'))
    result=client.post('/api/recommendations',json={}).json()
    vendor=next(v for v in result['ranked'] if v['id']=='V-001')
    assert vendor['memory']['status']=='available'
    assert vendor['memory']['evidence'][0]['source']=='SRC-TEST'
    assert {'recall','reflect'} <= {name for name,_ in calls}
    out=client.post('/api/outcomes',json={'decision_id':result['id'],'supplier_id':'V-001','occurred_at':'2026-11-06','on_time':True,'quality_ok':True,'invoice_ok':True,'note':'Arrived on time.'}).json()
    assert out['memory_status']=='submitted'
    retain=next(data for name,data in calls if name=='retain')
    assert retain['document_id']==out['id'] and out['source'] in retain['content']
    class Offline:
        def recall(self, **kwargs): raise ConnectionError('unavailable')
    monkeypatch.setattr(module,'memory_client',lambda:Offline())
    offline=client.post('/api/recommendations',json={}).json()
    assert offline['ranked'] and all(v['memory']['status']=='unavailable' for v in offline['ranked'])
