import os
import tempfile
from pathlib import Path

os.environ.setdefault('DATABASE_URL',f"sqlite:///{(Path(tempfile.mkdtemp()) / 'pilot.db').as_posix()}")
os.environ['PILOT_ENABLE_UNSAFE_LOCAL']='1'
os.environ.pop('HINDSIGHT_API_KEY',None)

from fastapi.testclient import TestClient
from backend.app import app
from backend.pilot import bearer_user

current_user='buyer-a'
app.dependency_overrides[bearer_user]=lambda:current_user
client=TestClient(app)

def test_full_supplier_to_invoice_workflow(monkeypatch):
    global current_user
    current_user='buyer-a'
    org=client.post('/api/pilot/organizations',json={'name':'Acme'}).json()['id']
    other_org=client.post('/api/pilot/organizations',json={'name':'Other'}).json()['id']
    supplier=client.post(f'/api/pilot/{org}/suppliers',json={'name':'Supplier One','approved':False}).json()
    request=client.post(f'/api/pilot/{org}/requests',json={'title':'Paper and cleaner','location':'Bengaluru','deadline':'2099-01-01','budget':'1000','currency':'INR','lines':[{'description':'Cleaner','quantity':'2','unit':'litre'},{'description':'Paper','quantity':'3','unit':'box'}]}).json()
    invite_path=f"/api/pilot/{org}/requests/{request['id']}/invites"
    assert client.post(invite_path,json={'vendor_id':supplier['id']}).status_code==400
    assert client.post(f"/api/pilot/{org}/suppliers/{supplier['id']}/approve").status_code==200
    link=client.post(invite_path,json={'vendor_id':supplier['id']}).json()
    token=link['url'].split('#',1)[1];header={'X-Supplier-Token':token}
    portal=client.get('/api/pilot/portal',headers=header).json()
    assert 'budget' not in portal['request']
    quote=client.post('/api/pilot/portal/quote',headers=header,json={'prices':['10.10','20.20'],'tax':'3.00','freight':'2.00','lead_days':1})
    assert quote.status_code==200 and quote.json()['total']=='85.80'
    assert client.post('/api/pilot/portal/quote',headers=header,json={'prices':['10.10','20.20'],'lead_days':1}).status_code==409
    quotes=client.get(f"/api/pilot/{org}/requests/{request['id']}/quotes").json()
    assert quotes[0]['eligible'] and quotes[0]['total']=='85.80'
    po=client.post(f"/api/pilot/{org}/quotes/{quote.json()['id']}/approve").json()
    assert client.post(f"/api/pilot/{org}/quotes/{quote.json()['id']}/approve").status_code==409
    assert client.get('/api/pilot/portal',headers=header).json()['order']['id']==po['id']
    invoice_data={'number':'abc-01','lines':[{'quantity':'2','unit_price':'10.10'},{'quantity':'3','unit_price':'20.20'}],'tax':'3','freight':'2'}
    invoice=client.post('/api/pilot/portal/invoice',headers=header,json=invoice_data)
    assert invoice.status_code==200
    monkeypatch.setenv('SUPABASE_URL','https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY','fake-server-key')
    class StorageResponse:
        def raise_for_status(self): pass
        def json(self): return {'signedURL':'/object/sign/test'}
    monkeypatch.setattr('backend.pilot.httpx.post',lambda *args,**kwargs:StorageResponse())
    upload=client.post(f"/api/pilot/portal/invoices/{invoice.json()['id']}/attachment",headers=header,files={'file':('invoice.pdf',b'%PDF-1.4 synthetic','application/pdf')})
    assert upload.status_code==200 and upload.json()['uploaded'] is True
    attachment=client.get(f"/api/pilot/{org}/invoices/{invoice.json()['id']}/attachment")
    assert attachment.status_code==200 and attachment.json()['url'].endswith('/storage/v1/object/sign/test')
    assert client.post('/api/pilot/portal/invoice',headers=header,json=invoice_data).status_code==409
    matches=client.get(f"/api/pilot/{org}/orders/{po['id']}/invoices").json()
    assert not matches[0]['match']['matched'] and 'No goods receipt' in matches[0]['match']['exceptions'][0]
    receipt_data={'quantities':['2','1'],'note':'Partial delivery','idempotency_key':'receipt-test-key-123456'}
    receipt=client.post(f"/api/pilot/{org}/orders/{po['id']}/receipts",json=receipt_data)
    assert receipt.status_code==200 and receipt.json()['memory_status']=='not_configured'
    retry=client.post(f"/api/pilot/{org}/orders/{po['id']}/receipts",json=receipt_data)
    assert retry.status_code==200 and retry.json()['id']==receipt.json()['id']
    matches=client.get(f"/api/pilot/{org}/orders/{po['id']}/invoices").json()
    assert not matches[0]['match']['matched']
    client.post(f"/api/pilot/{org}/orders/{po['id']}/receipts",json={'quantities':['0','2'],'note':'Remainder'})
    matches=client.get(f"/api/pilot/{org}/orders/{po['id']}/invoices").json()
    assert matches[0]['match']['matched']
    second=client.post('/api/pilot/portal/invoice',headers=header,json={'number':'def-02','lines':[{'quantity':'1','unit_price':'11'},{'quantity':'0','unit_price':'20.20'}],'tax':'3','freight':'2'})
    assert second.status_code==200
    matches=client.get(f"/api/pilot/{org}/orders/{po['id']}/invoices").json()
    assert all(not m['match']['matched'] for m in matches)
    assert any('Unit price differs' in x for m in matches for x in m['match']['exceptions'])
    assert any('Total invoiced quantity' in x for m in matches for x in m['match']['exceptions'])
    assert client.get(f"/api/pilot/{other_org}/orders/{po['id']}/invoices").status_code==404
    current_user='buyer-b'
    assert client.get(f'/api/pilot/{org}/suppliers').status_code==404
    current_user='buyer-a'
    assert client.post(f"/api/pilot/{org}/invites/{link['id']}/revoke").status_code==200
    assert client.get('/api/pilot/portal',headers=header).status_code==404

def test_csv_validation_and_discovery_unavailable():
    org=client.post('/api/pilot/organizations',json={'name':'Import Test'}).json()['id']
    csv=b'name,email,location,category\nExample,supplier@example.com,Bengaluru,Paper\n'
    result=client.post(f'/api/pilot/{org}/suppliers/import',files={'file':('suppliers.csv',csv,'text/csv')})
    assert result.status_code==200 and result.json()['imported']==1
    assert client.get(f'/api/pilot/{org}/suppliers').json()[0]['approved'] is False
    os.environ.pop('GOOGLE_PLACES_API_KEY',None)
    assert client.get(f'/api/pilot/{org}/discover?query=paper&location=Bengaluru').status_code==503

def test_quality_issue_blocks_a_match():
    from types import SimpleNamespace
    from backend.pilot import match_invoice
    order=SimpleNamespace(lines=[{'description':'Cleaner','quantity':'2','unit_price':'10.00'}],tax='0',freight='0',currency='INR')
    invoice=SimpleNamespace(lines=[{'quantity':'2','unit_price':'10.00'}],tax='0',freight='0')
    receipt=SimpleNamespace(id='grn-test',quantities=['2'],quality_ok=False)
    result=match_invoice(order,invoice,[receipt])
    assert not result['matched'] and 'Quality issue' in result['exceptions'][0]

def test_memory_uses_an_organization_bank_and_validated_sources(monkeypatch):
    import sys
    from types import SimpleNamespace
    from backend.app import Session
    from backend.pilot import MemoryEvent, send_memory, retrieve_memory
    org_id=client.post('/api/pilot/organizations',json={'name':'Memory Test'}).json()['id']
    vendor_id=client.post(f'/api/pilot/{org_id}/suppliers',json={'name':'Memory Supplier'}).json()['id']
    event_id,source_id,event_type='memory-test-id','grn-test-source','late_quality_issue'
    with Session.begin() as db:
        db.add(MemoryEvent(id=event_id,org_id=org_id,vendor_id=vendor_id,source_id=source_id,event_type=event_type,status='pending'))
    calls=[]
    class Memory:
        def __init__(self,**kwargs): pass
        def retain(self,**kwargs): calls.append(kwargs)
        def recall(self,**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(results=[SimpleNamespace(text=f'Supplier {vendor_id} source {source_id}: invented unsupported claim')])
    monkeypatch.setitem(sys.modules,'hindsight_client',SimpleNamespace(Hindsight=Memory))
    monkeypatch.setenv('HINDSIGHT_API_KEY','not-a-real-key')
    assert send_memory(event_id)=='submitted'
    assert calls[0]['bank_id']=='vendormind-'+org_id and calls[0]['document_id']==event_id
    result=retrieve_memory(org_id,vendor_id,{source_id:event_type})
    assert result['evidence']==[{'source':source_id,'text':event_type.replace('_',' ')}]
