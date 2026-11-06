import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./vendormind.db')
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql+psycopg://', 1)
elif DATABASE_URL.startswith('postgresql://'):
    DATABASE_URL = DATABASE_URL.replace('postgresql://', 'postgresql+psycopg://', 1)
engine = create_engine(DATABASE_URL, connect_args={'check_same_thread': False} if DATABASE_URL.startswith('sqlite') else {})
Session = sessionmaker(bind=engine, expire_on_commit=False)

class Base(DeclarativeBase): pass
class Supplier(Base):
    __tablename__ = 'suppliers'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    price: Mapped[float] = mapped_column(Float)
    lead_days: Mapped[int] = mapped_column(Integer)
    stock: Mapped[int] = mapped_column(Integer)
    area: Mapped[str] = mapped_column(String)
    approved: Mapped[bool] = mapped_column(Boolean, default=True)
class Event(Base):
    __tablename__ = 'events'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey('suppliers.id'))
    po: Mapped[str] = mapped_column(String)
    occurred_at: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
    on_time: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    quality_ok: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    invoice_ok: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    note: Mapped[str] = mapped_column(String)
    memory_status: Mapped[str] = mapped_column(String, default='not_synced')
class Decision(Base):
    __tablename__ = 'decisions'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[str] = mapped_column(String)
    request: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    review: Mapped[Optional[str]] = mapped_column(String, nullable=True)

app = FastAPI(title='VendorMind API')
Base.metadata.create_all(engine)

def seed():
    with Session.begin() as db:
        if db.scalar(select(Supplier.id).limit(1)): return
        rows = [('V-001','CleanPro',95,1,1500,'Bengaluru',True),('V-002','ValueChem',88,2,1200,'Bengaluru',True),('V-003','SwiftSupply',92,1,800,'Bengaluru',True),('V-004','NewVendor',90,2,1000,'Bengaluru',True),('V-005','Metro Hygiene',97,3,300,'Bengaluru',True),('V-006','Northstar Supplies',86,2,1500,'Hyderabad',False)]
        for id,name,price,lead,stock,area,approved in rows:
            db.add(Supplier(id=id,name=name,price=price,lead_days=lead,stock=stock,area=area,approved=approved))
        for s in range(1,4):
            for i in range(8):
                on_time = s == 1 or (s == 2 and i >= 4) or (s == 3 and i != 2)
                quality = not (s == 3 and i in (1,5))
                invoice = not (s == 2 and i in (1,3))
                note = ('Delivered on time' if on_time else 'Delivered two days late') + ('; quality issue recorded' if not quality else '; quality accepted') + ('; invoice mismatch recorded' if not invoice else '')
                db.add(Event(id=f'EV-{s}{i+1:02}',supplier_id=f'V-{s:03}',po=f'PO-{s}{i+1:02}',occurred_at=(date(2026,7,1)+timedelta(days=i*12)).isoformat(),source=f'DR-{s}{i+1:02}',on_time=on_time,quality_ok=quality,invoice_ok=invoice,note=note))
seed()

def secret():
    value = os.getenv('SESSION_SECRET')
    password = os.getenv('DEMO_PASSWORD')
    if not value or not password or value.startswith('change-me') or password.startswith('change-me'):
        raise HTTPException(503, 'Demo access is not configured. Set DEMO_PASSWORD and SESSION_SECRET on the server.')
    return value
def signature(expires: str): return hmac.new(secret().encode(), expires.encode(), hashlib.sha256).hexdigest()
def require_session(vm_session: Optional[str] = Cookie(default=None)):
    if not vm_session: raise HTTPException(401, 'Please enter the demo password.')
    try:
        expires, token = vm_session.split('.', 1)
        if int(expires) <= int(time.time()) or not hmac.compare_digest(token, signature(expires)): raise ValueError()
    except (ValueError, TypeError): raise HTTPException(401, 'Session expired. Please sign in again.')

class Login(BaseModel): password: str
class Request(BaseModel):
    item: str = Field(default='Commercial floor cleaner', min_length=1, max_length=100)
    quantity: int = Field(default=500, ge=1, le=100000)
    location: str = Field(default='Bengaluru', min_length=1, max_length=80)
    deadline_days: int = Field(default=2, ge=1, le=365)
    budget: float = Field(default=50000, gt=0, le=100000000)
class Outcome(BaseModel):
    decision_id: str
    supplier_id: str
    occurred_at: date
    on_time: bool
    quality_ok: bool
    invoice_ok: bool
    note: str = Field(min_length=3, max_length=500)
class Review(BaseModel): action: str = Field(pattern='^(approved|rejected)$')

def memory_client():
    key = os.getenv('HINDSIGHT_API_KEY')
    if not key: return None
    from hindsight_client import Hindsight
    return Hindsight(base_url=os.getenv('HINDSIGHT_API_URL','https://api.hindsight.vectorize.io'), api_key=key, timeout=4, max_attempts=1)
def bank(): return os.getenv('HINDSIGHT_BANK_ID','vendormind-demo')
def retain(event):
    try:
        client = memory_client()
        if not client: return 'not_configured'
        client.retain(bank_id=bank(), document_id=event.id, content=f"Synthetic demonstration: supplier {event.supplier_id}, {event.po}, source {event.source}, date {event.occurred_at}. {event.note}. On time: {event.on_time}; quality accepted: {event.quality_ok}; invoice correct: {event.invoice_ok}.")
        return 'submitted'
    except Exception: return 'failed'

def event_dict(e):
    return dict(id=e.id,supplier_id=e.supplier_id,po=e.po,occurred_at=e.occurred_at,source=e.source,on_time=e.on_time,quality_ok=e.quality_ok,invoice_ok=e.invoice_ok,note=e.note,memory_status=e.memory_status)
def rate(events, field):
    values=[getattr(e,field) for e in events if getattr(e,field) is not None]
    return {'value': round(sum(values)/len(values)*100) if values else None, 'sample':len(values)}
def memory_evidence(supplier, known_events):
    try:
        client=memory_client()
        if not client: return {'status':'not_configured','evidence':[],'reflection':None}
        result=client.recall(bank_id=bank(),query=f'Find source IDs and procurement outcomes for supplier {supplier.id} {supplier.name}.')
        texts=[str(getattr(x,'text','')) for x in getattr(result,'results',[])]
        # Only show memory text that cites an existing source for this supplier.
        supported=[{'text':t,'source':e.source} for t in texts for e in known_events if e.source in t and supplier.id in t]
        try:
            client.reflect(bank_id=bank(), query=f'For supplier {supplier.id}, summarise supported procurement risks and cite source IDs.')
        except Exception:
            pass
        # Reflections are exposed only if every cited source can be checked; use verified recalled text instead.
        return {'status':'available','evidence':supported[:4], 'reflection': None if not supported else 'Review the recalled source-linked events below.'}
    except Exception: return {'status':'unavailable','evidence':[],'reflection':None}

def recommend(db, request):
    suppliers=db.scalars(select(Supplier)).all()
    all_events=db.scalars(select(Event).order_by(Event.occurred_at.desc())).all()
    eligible=[]; excluded=[]
    for s in suppliers:
        reasons=[]
        if request.item.strip().lower() != 'commercial floor cleaner': reasons.append('No current quote for this item')
        if not s.approved: reasons.append('Supplier not approved')
        if s.area.casefold()!=request.location.strip().casefold(): reasons.append('Outside service area')
        if s.stock<request.quantity: reasons.append('Insufficient stock')
        if s.lead_days>request.deadline_days: reasons.append('Lead time exceeds deadline')
        if s.price*request.quantity>request.budget: reasons.append('Quote exceeds budget')
        if reasons: excluded.append({'id':s.id,'name':s.name,'reasons':reasons}); continue
        events=[e for e in all_events if e.supplier_id==s.id][:20]
        eligible.append({'id':s.id,'name':s.name,'unit_price':s.price,'total':s.price*request.quantity,'lead_days':s.lead_days,'stock':s.stock,'metrics':{'delivery':rate(events,'on_time'),'quality':rate(events,'quality_ok'),'invoice':rate(events,'invoice_ok')},'events':[event_dict(e) for e in events], 'memory':memory_evidence(s,events)})
    if eligible:
        lo=min(x['unit_price'] for x in eligible)
        for x in eligible:
            price=round(100*lo/x['unit_price'])
            factors={'price':price, **{k:v['value'] for k,v in x['metrics'].items()}}
            weights={'price':.35,'delivery':.30,'quality':.20,'invoice':.15}
            known=sum(weights[k] for k,v in factors.items() if v is not None)
            x['score']=round(sum(weights[k]*v for k,v in factors.items() if v is not None)/known,1)
            x['factors']=factors
            x['confidence']='Limited history' if x['metrics']['delivery']['sample']<3 else 'Historical evidence available'
        # Insufficient-history suppliers remain eligible but require manual review.
        eligible.sort(key=lambda x:(x['confidence']=='Limited history',-x['score'],x['total'],x['id']))
    return {'ranked':eligible,'excluded':excluded,'weights':{'price':35,'delivery':30,'quality':20,'invoice':15},'memory_note':'Narrative memory is supporting evidence and does not alter calculated scores.', 'synthetic':True}

@app.get('/api/health')
def health(): return {'status':'ok','memory':'configured' if os.getenv('HINDSIGHT_API_KEY') else 'not_configured'}
@app.post('/api/login')
def login(data: Login, response: Response):
    expected=os.getenv('DEMO_PASSWORD','')
    if not secrets.compare_digest(data.password, expected) or not expected: raise HTTPException(401,'Incorrect password.')
    expires=str(int(time.time())+8*60*60)
    response.set_cookie('vm_session', expires+'.'+signature(expires), httponly=True, secure=os.getenv('COOKIE_SECURE')=='1', samesite='strict', max_age=8*60*60, path='/')
    return {'ok':True}
@app.post('/api/logout')
def logout(response: Response): response.delete_cookie('vm_session',path='/'); return {'ok':True}
@app.get('/api/session', dependencies=[Depends(require_session)])
def session(): return {'ok':True}
@app.post('/api/recommendations', dependencies=[Depends(require_session)])
def create_recommendation(data: Request):
    with Session.begin() as db:
        result=recommend(db,data); id='DEC-'+secrets.token_hex(4).upper()
        db.add(Decision(id=id,created_at=datetime.now(timezone.utc).isoformat(),request=data.model_dump(),result=result))
        return {'id':id,'request':data.model_dump(),**result}
@app.get('/api/suppliers/{supplier_id}/timeline', dependencies=[Depends(require_session)])
def timeline(supplier_id: str):
    with Session() as db:
        if not db.get(Supplier,supplier_id): raise HTTPException(404,'Supplier not found')
        return [event_dict(e) for e in db.scalars(select(Event).where(Event.supplier_id==supplier_id).order_by(Event.occurred_at.desc())).all()]
@app.post('/api/decisions/{decision_id}/review', dependencies=[Depends(require_session)])
def review(decision_id: str, data: Review):
    with Session.begin() as db:
        d=db.get(Decision,decision_id)
        if not d: raise HTTPException(404,'Decision not found')
        d.review=data.action
        return {'status':d.review,'note':'Review recorded. No order or supplier communication was sent.'}
@app.post('/api/outcomes', dependencies=[Depends(require_session)])
def outcome(data: Outcome):
    with Session.begin() as db:
        decision=db.get(Decision,data.decision_id)
        if not decision or data.supplier_id not in [v['id'] for v in decision.result['ranked']]: raise HTTPException(400,'Choose an eligible supplier from this decision.')
        id='EV-'+secrets.token_hex(4).upper()
        event=Event(id=id,supplier_id=data.supplier_id,po='PO-DEMO-'+id[-4:],occurred_at=data.occurred_at.isoformat(),source='SRC-'+id[-4:],on_time=data.on_time,quality_ok=data.quality_ok,invoice_ok=data.invoice_ok,note=data.note)
        db.add(event); db.flush()
    status=retain(event)
    with Session.begin() as db:
        saved=db.get(Event,id)
        saved.memory_status=status
        return event_dict(saved)
@app.post('/api/memory/sync', dependencies=[Depends(require_session)])
def sync_memory():
    if not os.getenv('HINDSIGHT_API_KEY'): raise HTTPException(503, 'Configure HINDSIGHT_API_KEY before syncing memory.')
    with Session() as db:
        events=db.scalars(select(Event).where(Event.memory_status.in_(['not_synced','not_configured','failed'])).order_by(Event.occurred_at.desc()).limit(6)).all()
    statuses=[(event.id,retain(event)) for event in events]
    with Session.begin() as db:
        for id,status in statuses: db.get(Event,id).memory_status=status
    return {'submitted':sum(status=='submitted' for _,status in statuses),'failed':sum(status!='submitted' for _,status in statuses),'remaining_batch_limit':6}
@app.post('/api/replay/{decision_id}', dependencies=[Depends(require_session)])
def replay(decision_id: str):
    with Session.begin() as db:
        d=db.get(Decision,decision_id)
        if not d: raise HTTPException(404,'Decision not found')
        after=recommend(db,Request(**d.request))
        return {'id':d.id,'request':d.request,'before':d.result,'after':after,'explanation':'The request and quotes are unchanged. Recorded outcomes and available memory evidence may have changed.'}
