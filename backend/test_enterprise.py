import os
import tempfile
from pathlib import Path
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(Path(tempfile.mkdtemp()) / 'enterprise-test.db').as_posix()}")
os.environ["PILOT_ENABLE_UNSAFE_LOCAL"]="1"

import pytest
from fastapi.testclient import TestClient
from backend.app import app
from backend.pilot import bearer_user
client=TestClient(app)
current_user=''

@pytest.fixture(autouse=True)
def enterprise_auth():
    old=app.dependency_overrides.get(bearer_user)
    app.dependency_overrides[bearer_user]=lambda:current_user
    yield
    if old is None: app.dependency_overrides.pop(bearer_user,None)
    else: app.dependency_overrides[bearer_user]=old

def test_branch_intake_to_sourcing_and_isolation():
    global current_user
    current_user='branch-owner'
    org=client.post('/api/pilot/organizations',json={'name':'Multi branch'}).json()['id']
    other=client.post('/api/pilot/organizations',json={'name':'Other'}).json()['id']
    branch=client.post(f'/api/enterprise/{org}/branches',json={'name':'North','city':'Pune','code':'PN-01'}).json()
    assert client.post(f'/api/enterprise/{org}/branches',json={'name':'Same','city':'Pune','code':'pn-01'}).status_code==409
    assert client.post(f'/api/enterprise/{other}/intakes',json={'branch_id':branch['id'],'title':'Crates','category':'Packaging','amount':'100.12','quantity':'12','unit':'box','deadline':'2099-01-01'}).status_code==404
    assert client.post(f'/api/enterprise/{org}/rules',json={'branch_id':branch['id'],'category':'Packaging','threshold':'100','approver':'Central team'}).status_code==200
    intake=client.post(f'/api/enterprise/{org}/intakes',json={'branch_id':branch['id'],'title':'Crates','category':'Packaging','amount':'100.12','quantity':'12','unit':'box','deadline':'2099-01-01'}).json()
    assert intake['approver']=='Central team'
    approved=client.post(f"/api/enterprise/{org}/intakes/{intake['id']}/approve")
    assert approved.status_code==200
    assert client.post(f"/api/enterprise/{org}/intakes/{intake['id']}/approve").status_code==409
    requests=client.get(f'/api/pilot/{org}/requests').json()
    assert requests[0]['lines']==[{'description':'Crates','quantity':'12.000','unit':'box'}]
    current_user='another-user'
    assert client.get(f'/api/enterprise/{org}/overview').status_code==404

def test_demo_branches_and_reset():
    from backend.pilot import DEMO_USER, DEMO_ORG
    global current_user
    current_user=DEMO_USER
    client.post('/api/pilot/demo/bootstrap')
    data=client.get(f'/api/enterprise/{DEMO_ORG}/overview').json()
    assert len(data['branches'])==10 and len(data['intakes'])==5
    assert client.post('/api/pilot/demo/reset').status_code==200
    assert len(client.get(f'/api/enterprise/{DEMO_ORG}/overview').json()['branches'])==10

def test_purchase_order_pdf_is_scoped_and_contains_order():
    from io import BytesIO
    from pypdf import PdfReader
    from backend.pilot import DEMO_USER, DEMO_ORG
    global current_user
    current_user=DEMO_USER
    client.post('/api/pilot/demo/bootstrap')
    response=client.get(f'/api/pilot/{DEMO_ORG}/orders/po_demo_sample/pdf')
    assert response.status_code==200 and response.headers['content-type']=='application/pdf'
    text=' '.join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)
    assert 'CleanPro' in text and '45000.00' in text and 'FICTIONAL TRAINING DATA' in text
    current_user='unrelated-user'
    assert client.get(f'/api/pilot/{DEMO_ORG}/orders/po_demo_sample/pdf').status_code==404

def test_searchable_invoice_text_requires_authorization():
    from backend.app import Session
    from backend.pilot import DEMO_USER, DEMO_ORG, DEMO_ATTACHMENTS, Invoice
    global current_user
    current_user=DEMO_USER
    client.post('/api/pilot/demo/bootstrap')
    pdf=client.get(f'/api/pilot/{DEMO_ORG}/orders/po_demo_sample/pdf').content
    DEMO_ATTACHMENTS['invoice_demo_sample']=(pdf,'application/pdf')
    with Session.begin() as db:
        db.get(Invoice,'invoice_demo_sample').attachment_path='demo-in-memory'
    result=client.get(f'/api/pilot/{DEMO_ORG}/invoices/invoice_demo_sample/pdf-text')
    assert result.status_code==200 and result.json()['status']=='text_extracted'
    assert 'CleanPro' in result.json()['pages'][0]['text']
    current_user='unrelated-user'
    assert client.get(f'/api/pilot/{DEMO_ORG}/invoices/invoice_demo_sample/pdf-text').status_code==404
    current_user=DEMO_USER
    assert client.post('/api/pilot/demo/reset').status_code==200

def test_contract_versions_and_cited_search_are_organization_scoped():
    global current_user
    current_user='contract-owner'
    org=client.post('/api/pilot/organizations',json={'name':'Contract org'}).json()['id']
    other=client.post('/api/pilot/organizations',json={'name':'Other org'}).json()['id']
    vendor=client.post(f'/api/pilot/{org}/suppliers',json={'name':'North Packaging'}).json()
    body={'title':'Packaging agreement','vendor_id':vendor['id'],'text':'Renewal on 2027-02-01. Termination requires thirty days notice.'}
    contract=client.post(f'/api/enterprise/{org}/contracts',json=body)
    assert contract.status_code==200
    cid=contract.json()['id']
    assert client.get(f'/api/enterprise/{other}/contracts/{cid}/versions').status_code==404
    version=client.get(f'/api/enterprise/{org}/contracts/{cid}/versions').json()[0]
    assert version['review']['clauses'][0]['status']=='found'
    assert version['review']['dates'][0]['text']=='2027-02-01'
    assert client.post(f'/api/enterprise/{org}/contracts/{cid}/versions',json={'text':'Liability is limited. Payment due after 30 days.'}).status_code==200
    assert len(client.get(f'/api/enterprise/{org}/contracts/{cid}/versions').json())==2
    result=client.post(f'/api/enterprise/{org}/search',json={'query':'Packaging'}).json()
    assert any(x['id']==cid and x['kind']=='contract' for x in result['results'])
    assert client.post(f'/api/enterprise/{other}/search',json={'query':'Packaging'}).json()['results']==[]

def test_erp_preview_requires_mapping_and_never_sends():
    from backend.pilot import DEMO_USER, DEMO_ORG
    global current_user
    current_user=DEMO_USER
    client.post('/api/pilot/demo/bootstrap')
    base=f'/api/enterprise/{DEMO_ORG}/erp-previews'
    assert client.post(base+'/zoho',json={'order_id':'po_demo_sample','vendor_id':'vendor1','item_ids':['','extra']}).status_code==422
    response=client.post(base+'/zoho',json={'order_id':'po_demo_sample','vendor_id':'vendor1','item_ids':['item1']})
    assert response.status_code==200 and response.json()['payload']['reference_number']=='po_demo_sample'
    pid=response.json()['id']
    assert client.post(base+'/'+pid+'/approve').json()['status']=='approved_locally'
    assert client.post(base+'/'+pid+'/approve').status_code==409
    current_user='unauthorized-user'
    assert client.get(base).status_code==404
    current_user=DEMO_USER
    assert client.post('/api/pilot/demo/reset').status_code==200

def test_branch_csv_import_is_atomic():
    global current_user
    current_user='csv-owner'
    org=client.post('/api/pilot/organizations',json={'name':'CSV org'}).json()['id']
    base=f'/api/enterprise/{org}'
    csv=b'name,city,code\nEast,Delhi,DEL-E\nWest,Mumbai,MUM-W\n'
    assert client.post(base+'/branches/import',files={'file':('branches.csv',csv,'text/csv')}).json()['imported']==2
    duplicate=b'name,city,code\nSouth,Delhi,DEL-S\nEast again,Delhi,DEL-E\n'
    assert client.post(base+'/branches/import',files={'file':('branches.csv',duplicate,'text/csv')}).status_code==409
    assert len(client.get(base+'/overview').json()['branches'])==2

def test_scoped_onboarding_questionnaire_and_revoke():
    global current_user
    current_user='onboarding-owner'
    org=client.post('/api/pilot/organizations',json={'name':'Onboarding org'}).json()['id']
    supplier=client.post(f'/api/pilot/{org}/suppliers',json={'name':'Fresh supplier'}).json()
    link=client.post(f"/api/enterprise/{org}/onboarding/{supplier['id']}/link").json()
    headers={'X-Supplier-Token':link['url'].split('#')[1]}
    assert client.get('/api/enterprise/onboarding-portal',headers=headers).json()['supplier']=='Fresh supplier'
    data={'legal_name':'Fresh Supplier Ltd','contact_email':'supplier@example.com','operating_locations':'Pune','certification_expiry':'2099-01-01'}
    assert client.post('/api/enterprise/onboarding-portal',headers=headers,json=data).status_code==200
    assert client.post('/api/enterprise/onboarding-portal',headers=headers,json=data).status_code==404
    cases=client.get(f'/api/enterprise/{org}/onboarding').json()
    assert cases[0]['response']['legal_name']=='Fresh Supplier Ltd'
    assert client.post(f"/api/enterprise/{org}/onboarding/{link['id']}/approve").json()['status']=='approved'
    link2=client.post(f"/api/enterprise/{org}/onboarding/{supplier['id']}/link").json()
    assert client.post(f"/api/enterprise/{org}/onboarding/{link2['id']}/revoke").status_code==200
    assert client.get('/api/enterprise/onboarding-portal',headers={'X-Supplier-Token':link2['url'].split('#')[1]}).status_code==404

def test_public_research_requires_consent_and_filters_unsafe_links(monkeypatch):
    global current_user
    current_user='research-owner'
    org=client.post('/api/pilot/organizations',json={'name':'Research org'}).json()['id']
    vendor=client.post(f'/api/pilot/{org}/suppliers',json={'name':'Example Ltd','location':'Pune'}).json()
    monkeypatch.setenv('TINYFISH_API_KEY','test-only-secret')
    import httpx
    def fake_get(url,**kwargs):
        assert url=='https://api.search.tinyfish.ai' and kwargs['params']['query']=='Example Ltd Pune business supplier'
        return httpx.Response(200,request=httpx.Request('GET',url),json={'results':[{'url':'https://example.com/about','title':'Example','snippet':'Source text'},{'url':'javascript:alert(1)','title':'unsafe'}]})
    monkeypatch.setattr('httpx.get',fake_get)
    path=f'/api/enterprise/{org}/supplier-research'
    assert client.post(path,json={'vendor_id':vendor['id'],'confirm_public_search':False}).status_code==422
    result=client.post(path,json={'vendor_id':vendor['id'],'confirm_public_search':True}).json()
    assert result['status']=='unverified' and len(result['results'])==1

def test_ai_consent_and_citation_validation(monkeypatch):
    import httpx,json
    global current_user
    current_user='ai-owner'
    org=client.post('/api/pilot/organizations',json={'name':'AI org'}).json()['id']
    vendor=client.post(f'/api/pilot/{org}/suppliers',json={'name':'Acme Packaging'}).json()
    monkeypatch.setenv('GROQ_API_KEY','test-only-secret')
    path=f'/api/enterprise/{org}'
    assert client.post(path+'/ask',json={'question':'Acme'}).status_code==403
    assert client.post(path+'/ai-consent',json={'enabled':True}).status_code==200
    def result(ids):
        def call(url,**kwargs):
            return httpx.Response(200,request=httpx.Request('POST',url),json={'choices':[{'message':{'content':json.dumps({'answer':'Supplier exists.','source_ids':ids})}}]})
        return call
    monkeypatch.setattr('httpx.post',result([vendor['id']]))
    answer=client.post(path+'/ask',json={'question':'Acme'}).json()
    assert answer['status']=='unverified_ai' and answer['citations'][0]['id']==vendor['id']
    monkeypatch.setattr('httpx.post',result(['other-org-record']))
    assert client.post(path+'/ask',json={'question':'Acme'}).status_code==503

def test_scanned_pdf_uses_ocr_without_changing_matching(monkeypatch):
    from io import BytesIO
    from reportlab.pdfgen import canvas
    from backend.app import Session
    from backend.pilot import DEMO_USER, DEMO_ORG, DEMO_ATTACHMENTS, Invoice
    global current_user
    current_user=DEMO_USER
    client.post('/api/pilot/demo/bootstrap')
    buf=BytesIO();doc=canvas.Canvas(buf);doc.rect(100,100,200,200,fill=1);doc.showPage();doc.save()
    DEMO_ATTACHMENTS['invoice_demo_sample']=(buf.getvalue(),'application/pdf')
    with Session.begin() as db:db.get(Invoice,'invoice_demo_sample').attachment_path='demo-in-memory'
    monkeypatch.setattr('backend.ocr.ocr_pdf_pages',lambda raw,pages:({0:'Invoice total 46000.00'},'available'))
    result=client.get(f'/api/pilot/{DEMO_ORG}/invoices/invoice_demo_sample/pdf-text').json()
    assert result['pages'][0]['source']=='ocr' and result['pages'][0]['text']=='Invoice total 46000.00'
    assert 'unverified' in result['notice']
    assert not client.get(f'/api/pilot/{DEMO_ORG}/orders/po_demo_sample/invoices').json()[0]['match']['matched']
    assert client.post('/api/pilot/demo/reset').status_code==200
