"""Organization-scoped procurement pilot. Existing /api demo remains synthetic."""
import hashlib
import io
import csv
import os
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column
from backend.app import Base, Session, DATABASE_URL

router = APIRouter(prefix='/api/pilot', tags=['pilot'])

def uid(prefix): return prefix + '_' + secrets.token_hex(8)
def now(): return datetime.now(timezone.utc)
def money(value):
    try:
        number=Decimal(str(value))
        if not number.is_finite() or number < 0 or number > Decimal('1000000000'): raise ValueError()
        return number.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError): raise HTTPException(422,'Enter a valid non-negative amount.')
def qty(value):
    try:
        number=Decimal(str(value))
        if not number.is_finite() or number <= 0 or number > Decimal('1000000000'): raise ValueError()
        result=number.quantize(Decimal('.001'), rounding=ROUND_HALF_UP)
        if result<=0: raise ValueError()
        return result
    except (InvalidOperation, ValueError): raise HTTPException(422,'Enter a valid positive quantity.')
def nonnegative_qty(value):
    try:
        number=Decimal(str(value))
        if not number.is_finite() or number < 0 or number > Decimal('1000000000'): raise ValueError()
        return number.quantize(Decimal('.001'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError): raise HTTPException(422,'Enter a valid non-negative quantity.')

class Organization(Base):
    __tablename__='pilot_organizations'
    id: Mapped[str]=mapped_column(String, primary_key=True)
    name: Mapped[str]=mapped_column(String)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))
class Member(Base):
    __tablename__='pilot_members'
    __table_args__=(UniqueConstraint('org_id','user_id'),)
    id: Mapped[str]=mapped_column(String, primary_key=True)
    org_id: Mapped[str]=mapped_column(ForeignKey('pilot_organizations.id'), index=True)
    user_id: Mapped[str]=mapped_column(String, index=True)
    role: Mapped[str]=mapped_column(String, default='owner')
class Vendor(Base):
    __tablename__='pilot_vendors'
    id: Mapped[str]=mapped_column(String, primary_key=True)
    org_id: Mapped[str]=mapped_column(ForeignKey('pilot_organizations.id'), index=True)
    name: Mapped[str]=mapped_column(String)
    email: Mapped[str]=mapped_column(String, default='')
    phone: Mapped[str]=mapped_column(String, default='')
    location: Mapped[str]=mapped_column(String, default='')
    category: Mapped[str]=mapped_column(String, default='')
    place_id: Mapped[str]=mapped_column(String, default='')
    approved: Mapped[bool]=mapped_column(Boolean, default=False)
class PurchaseRequest(Base):
    __tablename__='pilot_requests'
    id: Mapped[str]=mapped_column(String, primary_key=True)
    org_id: Mapped[str]=mapped_column(ForeignKey('pilot_organizations.id'), index=True)
    title: Mapped[str]=mapped_column(String)
    location: Mapped[str]=mapped_column(String)
    deadline: Mapped[str]=mapped_column(String)
    budget: Mapped[str]=mapped_column(String)
    currency: Mapped[str]=mapped_column(String)
    lines: Mapped[list]=mapped_column(JSON)
    status: Mapped[str]=mapped_column(String, default='open')
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))
class Invitation(Base):
    __tablename__='pilot_invitations'
    id: Mapped[str]=mapped_column(String, primary_key=True)
    org_id: Mapped[str]=mapped_column(ForeignKey('pilot_organizations.id'), index=True)
    request_id: Mapped[str]=mapped_column(ForeignKey('pilot_requests.id'))
    vendor_id: Mapped[str]=mapped_column(ForeignKey('pilot_vendors.id'))
    token_hash: Mapped[str]=mapped_column(String, unique=True)
    expires_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool]=mapped_column(Boolean, default=False)
class Quote(Base):
    __tablename__='pilot_quotes'
    __table_args__=(UniqueConstraint('request_id','vendor_id'),)
    id: Mapped[str]=mapped_column(String, primary_key=True)
    org_id: Mapped[str]=mapped_column(ForeignKey('pilot_organizations.id'), index=True)
    request_id: Mapped[str]=mapped_column(ForeignKey('pilot_requests.id'))
    vendor_id: Mapped[str]=mapped_column(ForeignKey('pilot_vendors.id'))
    prices: Mapped[list]=mapped_column(JSON)
    tax: Mapped[str]=mapped_column(String)
    freight: Mapped[str]=mapped_column(String)
    total: Mapped[str]=mapped_column(String)
    lead_days: Mapped[int]=mapped_column()
    submitted_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))
class Order(Base):
    __tablename__='pilot_orders'
    __table_args__=(UniqueConstraint('request_id'),)
    id: Mapped[str]=mapped_column(String, primary_key=True)
    org_id: Mapped[str]=mapped_column(ForeignKey('pilot_organizations.id'), index=True)
    request_id: Mapped[str]=mapped_column(ForeignKey('pilot_requests.id'))
    vendor_id: Mapped[str]=mapped_column(ForeignKey('pilot_vendors.id'))
    quote_id: Mapped[str]=mapped_column(ForeignKey('pilot_quotes.id'))
    lines: Mapped[list]=mapped_column(JSON)
    currency: Mapped[str]=mapped_column(String)
    tax: Mapped[str]=mapped_column(String)
    freight: Mapped[str]=mapped_column(String)
    total: Mapped[str]=mapped_column(String)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))
class Receipt(Base):
    __tablename__='pilot_receipts'
    __table_args__=(UniqueConstraint('org_id','order_id','idempotency_key'),)
    id: Mapped[str]=mapped_column(String, primary_key=True)
    org_id: Mapped[str]=mapped_column(ForeignKey('pilot_organizations.id'), index=True)
    order_id: Mapped[str]=mapped_column(ForeignKey('pilot_orders.id'))
    idempotency_key: Mapped[str]=mapped_column(String)
    quantities: Mapped[list]=mapped_column(JSON)
    note: Mapped[str]=mapped_column(String, default='')
    received_on: Mapped[str]=mapped_column(String)
    quality_ok: Mapped[bool]=mapped_column(Boolean, default=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))
class Invoice(Base):
    __tablename__='pilot_invoices'
    __table_args__=(UniqueConstraint('org_id','vendor_id','number'),)
    id: Mapped[str]=mapped_column(String, primary_key=True)
    org_id: Mapped[str]=mapped_column(ForeignKey('pilot_organizations.id'), index=True)
    order_id: Mapped[str]=mapped_column(ForeignKey('pilot_orders.id'))
    vendor_id: Mapped[str]=mapped_column(ForeignKey('pilot_vendors.id'))
    number: Mapped[str]=mapped_column(String)
    lines: Mapped[list]=mapped_column(JSON)
    tax: Mapped[str]=mapped_column(String)
    freight: Mapped[str]=mapped_column(String)
    total: Mapped[str]=mapped_column(String)
    attachment_path: Mapped[Optional[str]]=mapped_column(String, nullable=True)
    status: Mapped[str]=mapped_column(String, default='submitted')
    resolution: Mapped[Optional[str]]=mapped_column(String, nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))
class Audit(Base):
    __tablename__='pilot_audit'
    id: Mapped[str]=mapped_column(String, primary_key=True)
    org_id: Mapped[str]=mapped_column(ForeignKey('pilot_organizations.id'), index=True)
    subject_id: Mapped[str]=mapped_column(String)
    action: Mapped[str]=mapped_column(String)
    actor: Mapped[str]=mapped_column(String)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))
class MemoryEvent(Base):
    __tablename__='pilot_memory_events'
    id: Mapped[str]=mapped_column(String, primary_key=True)
    org_id: Mapped[str]=mapped_column(ForeignKey('pilot_organizations.id'), index=True)
    vendor_id: Mapped[str]=mapped_column(ForeignKey('pilot_vendors.id'))
    source_id: Mapped[str]=mapped_column(String)
    event_type: Mapped[str]=mapped_column(String)
    status: Mapped[str]=mapped_column(String, default='pending')

class OrgIn(BaseModel): name:str=Field(min_length=1,max_length=120)
class VendorIn(BaseModel):
    name:str=Field(min_length=1,max_length=160); email:str=Field(default='',max_length=255); phone:str=Field(default='',max_length=60); location:str=Field(default='',max_length=160); category:str=Field(default='',max_length=160); place_id:str=Field(default='',max_length=255); approved:bool=False
class LineIn(BaseModel): description:str=Field(min_length=1,max_length=200); quantity:str; unit:str=Field(default='unit',min_length=1,max_length=30)
class RequestIn(BaseModel):
    title:str=Field(min_length=1,max_length=160); location:str=Field(min_length=1,max_length=160); deadline:str=Field(min_length=1,max_length=30); budget:str; currency:str=Field(default='INR',pattern='^[A-Z]{3}$'); lines:list[LineIn]=Field(min_length=1,max_length=30)
class InviteIn(BaseModel): vendor_id:str
class QuoteIn(BaseModel): prices:list[str]=Field(min_length=1,max_length=30); tax:str='0'; freight:str='0'; lead_days:int=Field(ge=0,le=3650)
class ReceiptIn(BaseModel): quantities:list[str]=Field(min_length=1,max_length=30); note:str=Field(default='',max_length=500); received_on:Optional[str]=Field(default=None,max_length=10); quality_ok:bool=True; idempotency_key:Optional[str]=Field(default=None,min_length=16,max_length=100)
class InvoiceLine(BaseModel): quantity:str; unit_price:str
class InvoiceIn(BaseModel): number:str=Field(min_length=1,max_length=120); lines:list[InvoiceLine]=Field(min_length=1,max_length=30); tax:str='0'; freight:str='0'
class ResolutionIn(BaseModel): note:str=Field(min_length=3,max_length=500)

def ensure_pilot_ready():
    if os.getenv('PILOT_ENABLE_UNSAFE_LOCAL')=='1': return
    if DATABASE_URL.startswith('sqlite') or os.getenv('PILOT_RLS_READY')!='1':
        raise HTTPException(503,'Pilot access is disabled until the dedicated database and organization isolation are configured.')
def bearer_user(authorization:Optional[str]=Header(default=None)):
    ensure_pilot_ready()
    url=os.getenv('SUPABASE_URL','').rstrip('/'); key=os.getenv('SUPABASE_ANON_KEY','')
    if not url or not key: raise HTTPException(503,'Buyer sign-in is not configured. Set up Supabase first.')
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'Sign in to continue.')
    try:
        r=httpx.get(url+'/auth/v1/user',headers={'apikey':key,'Authorization':authorization},timeout=5)
        if r.status_code!=200: raise HTTPException(401,'Your session is invalid or expired.')
        user=r.json(); return user['id']
    except HTTPException: raise
    except Exception: raise HTTPException(503,'Sign-in service is unavailable.')
def require_org(org_id:str, user:str=Depends(bearer_user)):
    with Session() as db:
        if not db.scalar(select(Member.id).where(Member.org_id==org_id,Member.user_id==user)): raise HTTPException(404,'Workspace not found.')
    return user
def audit(db,org,subject,action,actor): db.add(Audit(id=uid('aud'),org_id=org,subject_id=subject,action=action,actor=actor,created_at=now()))
def get_owned(db,model,id,org):
    obj=db.get(model,id)
    if not obj or obj.org_id!=org: raise HTTPException(404,'Record not found.')
    return obj
def dt_utc(d): return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d
def invitation_for(db, token):
    ensure_pilot_ready()
    token_hash=hashlib.sha256(token.encode()).hexdigest()
    invitation=db.scalar(select(Invitation).where(Invitation.token_hash==token_hash))
    if not invitation or invitation.revoked or dt_utc(invitation.expires_at)<=now(): raise HTTPException(404,'This supplier link is invalid, expired or revoked.')
    return invitation
def vendor_json(v): return {'id':v.id,'name':v.name,'email':v.email,'phone':v.phone,'location':v.location,'category':v.category,'place_id':v.place_id,'approved':v.approved}
def req_json(r): return {'id':r.id,'title':r.title,'location':r.location,'deadline':r.deadline,'budget':r.budget,'currency':r.currency,'lines':r.lines,'status':r.status,'created_at':r.created_at.isoformat()}
def order_json(o): return {'id':o.id,'request_id':o.request_id,'vendor_id':o.vendor_id,'quote_id':o.quote_id,'lines':o.lines,'currency':o.currency,'tax':o.tax,'freight':o.freight,'total':o.total,'created_at':o.created_at.isoformat()}
def memory_status(): return 'configured' if os.getenv('HINDSIGHT_API_KEY') else 'not_configured'
def send_memory(event_id):
    with Session() as db:
        event=db.get(MemoryEvent,event_id)
        if not event: return 'not_found'
        org_id,vendor_id,source_id,event_type=event.org_id,event.vendor_id,event.source_id,event.event_type
    status='not_configured'
    if os.getenv('HINDSIGHT_API_KEY'):
        try:
            from hindsight_client import Hindsight
            client=Hindsight(base_url=os.getenv('HINDSIGHT_API_URL','https://api.hindsight.vectorize.io'),api_key=os.environ['HINDSIGHT_API_KEY'],timeout=5,max_attempts=1)
            client.retain(bank_id='vendormind-'+org_id,document_id=event_id,content=f'Supplier {vendor_id}: verified event {event_type}; source {source_id}.')
            status='submitted'
        except Exception: status='failed'
    with Session.begin() as db: db.get(MemoryEvent,event_id).status=status
    return status
def retrieve_memory(org_id,vendor_id,known):
    if not os.getenv('HINDSIGHT_API_KEY'): return {'status':'not_configured','evidence':[]}
    try:
        from hindsight_client import Hindsight
        client=Hindsight(base_url=os.getenv('HINDSIGHT_API_URL','https://api.hindsight.vectorize.io'),api_key=os.environ['HINDSIGHT_API_KEY'],timeout=4,max_attempts=1)
        result=client.recall(bank_id='vendormind-'+org_id,query=f'Find verified procurement outcomes for supplier {vendor_id}, including source IDs.')
        evidence=[]
        for item in getattr(result,'results',[]):
            text=str(getattr(item,'text',''))
            for source,event_type in known.items():
                if source in text and vendor_id in text: evidence.append({'source':source,'text':event_type.replace('_',' ')})
        return {'status':'available','evidence':evidence[:3]}
    except Exception: return {'status':'unavailable','evidence':[]}

@router.get('/config')
def config(): return {'supabase_url':os.getenv('SUPABASE_URL',''),'supabase_anon_key':os.getenv('SUPABASE_ANON_KEY',''),'google_places':bool(os.getenv('GOOGLE_PLACES_API_KEY'))}
@router.get('/organizations')
def organizations(user:str=Depends(bearer_user)):
    with Session() as db:
        return [{'id':o.id,'name':o.name} for o in db.scalars(select(Organization).join(Member,Member.org_id==Organization.id).where(Member.user_id==user)).all()]
@router.post('/organizations')
def create_organization(data:OrgIn,user:str=Depends(bearer_user)):
    with Session.begin() as db:
        o=Organization(id=uid('org'),name=data.name.strip(),created_at=now()); db.add(o); db.flush()
        db.add(Member(id=uid('mem'),org_id=o.id,user_id=user,role='owner')); audit(db,o.id,o.id,'workspace_created',user)
        return {'id':o.id,'name':o.name}
@router.get('/{org_id}/suppliers')
def suppliers(org_id:str,user:str=Depends(require_org)):
    with Session() as db: return [vendor_json(v) for v in db.scalars(select(Vendor).where(Vendor.org_id==org_id).order_by(Vendor.name)).all()]
@router.post('/{org_id}/suppliers')
def add_supplier(org_id:str,data:VendorIn,user:str=Depends(require_org)):
    with Session.begin() as db:
        values=data.model_dump();values['approved']=False
        v=Vendor(id=uid('sup'),org_id=org_id,**values);db.add(v);audit(db,org_id,v.id,'supplier_added',user);return vendor_json(v)
@router.post('/{org_id}/suppliers/{vendor_id}/approve')
def approve_supplier(org_id:str,vendor_id:str,user:str=Depends(require_org)):
    with Session.begin() as db:
        v=get_owned(db,Vendor,vendor_id,org_id);v.approved=True;audit(db,org_id,v.id,'supplier_approved',user);return vendor_json(v)
@router.post('/{org_id}/suppliers/import')
async def import_suppliers(org_id:str,file:UploadFile=File(...),user:str=Depends(require_org)):
    raw=await file.read(1024*1024+1)
    if len(raw)>1024*1024: raise HTTPException(413,'CSV must be under 1 MB.')
    try: rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
    except (UnicodeError,csv.Error): raise HTTPException(422,'Upload a UTF-8 CSV file.')
    if len(rows)>500 or not rows: raise HTTPException(422,'CSV must contain 1–500 rows.')
    prepared=[]
    for n,row in enumerate(rows,2):
        name=(row.get('name') or '').strip()
        if not name or len(name)>160: raise HTTPException(422,f'Row {n} needs a name under 160 characters.')
        prepared.append(VendorIn(name=name,email=(row.get('email') or '')[:255],phone=(row.get('phone') or '')[:60],location=(row.get('location') or '')[:160],category=(row.get('category') or '')[:160],approved=False))
    with Session.begin() as db:
        for v in prepared: db.add(Vendor(id=uid('sup'),org_id=org_id,**v.model_dump()))
        audit(db,org_id,org_id,'suppliers_imported',user)
    return {'imported':len(prepared),'message':'Imported suppliers are unapproved until reviewed.'}
@router.get('/{org_id}/discover')
def discover(org_id:str,query:str,location:str,user:str=Depends(require_org)):
    key=os.getenv('GOOGLE_PLACES_API_KEY')
    if not key: raise HTTPException(503,'Google Places is not configured. Add a Google Places API key to enable live discovery.')
    if not query.strip() or not location.strip() or len(query)>120 or len(location)>120: raise HTTPException(422,'Enter a category and location.')
    try:
        r=httpx.post('https://places.googleapis.com/v1/places:searchText',headers={'X-Goog-Api-Key':key,'X-Goog-FieldMask':'places.id,places.displayName,places.formattedAddress,places.googleMapsUri'},json={'textQuery':f'{query} suppliers in {location}','pageSize':10},timeout=8)
        r.raise_for_status();return {'places':r.json().get('places',[]),'notice':'Google Maps results are unverified leads. Confirm suitability and contact details.'}
    except Exception: raise HTTPException(503,'Supplier discovery is temporarily unavailable.')
@router.get('/{org_id}/requests')
def requests(org_id:str,user:str=Depends(require_org)):
    with Session() as db: return [req_json(r) for r in db.scalars(select(PurchaseRequest).where(PurchaseRequest.org_id==org_id).order_by(PurchaseRequest.created_at.desc())).all()]
@router.post('/{org_id}/requests')
def create_request(org_id:str,data:RequestIn,user:str=Depends(require_org)):
    try: datetime.strptime(data.deadline,'%Y-%m-%d')
    except ValueError: raise HTTPException(422,'Enter a valid deadline (YYYY-MM-DD).')
    if money(data.budget)<=0: raise HTTPException(422,'Budget must be greater than zero.')
    lines=[{'description':l.description,'quantity':str(qty(l.quantity)),'unit':l.unit} for l in data.lines]
    with Session.begin() as db:
        r=PurchaseRequest(id=uid('req'),org_id=org_id,title=data.title,location=data.location,deadline=data.deadline,budget=str(money(data.budget)),currency=data.currency,lines=lines,status='open',created_at=now());db.add(r);audit(db,org_id,r.id,'request_created',user);return req_json(r)
@router.post('/{org_id}/requests/{request_id}/invites')
def invite(org_id:str,request_id:str,data:InviteIn,user:str=Depends(require_org)):
    with Session.begin() as db:
        r=get_owned(db,PurchaseRequest,request_id,org_id);v=get_owned(db,Vendor,data.vendor_id,org_id)
        if not v.approved: raise HTTPException(400,'Approve the supplier after checking their details first.')
        if r.status!='open': raise HTTPException(400,'This request is closed.')
        token=secrets.token_urlsafe(32); inv=Invitation(id=uid('inv'),org_id=org_id,request_id=r.id,vendor_id=v.id,token_hash=hashlib.sha256(token.encode()).hexdigest(),expires_at=now()+timedelta(days=7),revoked=False)
        db.add(inv);audit(db,org_id,r.id,'supplier_link_created',user)
        return {'id':inv.id,'url':os.getenv('PUBLIC_APP_URL','http://localhost:3000').rstrip('/')+'/supplier#'+token,'expires_at':inv.expires_at.isoformat()}
@router.get('/{org_id}/requests/{request_id}/invites')
def list_invites(org_id:str,request_id:str,user:str=Depends(require_org)):
    with Session() as db:
        get_owned(db,PurchaseRequest,request_id,org_id)
        rows=db.scalars(select(Invitation).where(Invitation.org_id==org_id,Invitation.request_id==request_id)).all()
        return [{'id':i.id,'supplier':db.get(Vendor,i.vendor_id).name,'expires_at':i.expires_at.isoformat(),'revoked':i.revoked or dt_utc(i.expires_at)<=now()} for i in rows]
@router.post('/{org_id}/invites/{invite_id}/revoke')
def revoke(org_id:str,invite_id:str,user:str=Depends(require_org)):
    with Session.begin() as db:
        inv=get_owned(db,Invitation,invite_id,org_id);inv.revoked=True;audit(db,org_id,inv.id,'supplier_link_revoked',user);return {'revoked':True}
@router.get('/portal')
def portal(token:str=Header(alias='X-Supplier-Token')):
    with Session() as db:
        inv=invitation_for(db,token);r=db.get(PurchaseRequest,inv.request_id);v=db.get(Vendor,inv.vendor_id)
        order=db.scalar(select(Order).where(Order.request_id==r.id,Order.vendor_id==v.id))
        public_request=req_json(r);public_request.pop('budget',None)
        return {'supplier':{'name':v.name},'request':public_request,'order':order_json(order) if order else None}
@router.post('/portal/quote')
def submit_quote(data:QuoteIn,token:str=Header(alias='X-Supplier-Token')):
    with Session.begin() as db:
        inv=invitation_for(db,token);r=db.get(PurchaseRequest,inv.request_id)
        if r.status!='open': raise HTTPException(400,'This request is closed.')
        if len(data.prices)!=len(r.lines): raise HTTPException(422,'Provide a unit price for every item.')
        if db.scalar(select(Quote.id).where(Quote.request_id==r.id,Quote.vendor_id==inv.vendor_id)): raise HTTPException(409,'A quote has already been submitted for this supplier.')
        prices=[str(money(p)) for p in data.prices];tax=money(data.tax);freight=money(data.freight)
        total=sum((Decimal(l['quantity'])*Decimal(p) for l,p in zip(r.lines,prices)),Decimal(0))+tax+freight
        q=Quote(id=uid('quote'),org_id=inv.org_id,request_id=r.id,vendor_id=inv.vendor_id,prices=prices,tax=str(tax),freight=str(freight),total=str(total.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)),lead_days=data.lead_days,submitted_at=now());db.add(q);audit(db,inv.org_id,r.id,'quote_submitted','supplier');return {'id':q.id,'total':q.total,'currency':r.currency}
@router.get('/{org_id}/requests/{request_id}/quotes')
def compare_quotes(org_id:str,request_id:str,user:str=Depends(require_org)):
    with Session() as db:
        r=get_owned(db,PurchaseRequest,request_id,org_id);rows=[]
        for q in db.scalars(select(Quote).where(Quote.org_id==org_id,Quote.request_id==r.id)).all():
            v=db.get(Vendor,q.vendor_id);reasons=[]
            if not v.approved: reasons.append('Supplier is not approved')
            if Decimal(q.total)>Decimal(r.budget): reasons.append('Exceeds budget')
            try:
                if now().date()+timedelta(days=q.lead_days)>datetime.fromisoformat(r.deadline).date(): reasons.append('Lead time exceeds deadline')
            except ValueError: reasons.append('Deadline is invalid')
            prev_orders=db.scalars(select(Order.id).where(Order.org_id==org_id,Order.vendor_id==v.id)).all()
            vendor_receipts=db.scalars(select(Receipt).where(Receipt.org_id==org_id,Receipt.order_id.in_(prev_orders)).order_by(Receipt.created_at.desc()).limit(5)).all() if prev_orders else []
            history=[]
            for x in vendor_receipts:
                old_order=db.get(Order,x.order_id);old_request=db.get(PurchaseRequest,old_order.request_id)
                history.append({'source':x.id,'received_on':x.received_on,'on_time':x.received_on<=old_request.deadline,'quality_ok':x.quality_ok,'note':x.note})
            events=db.scalars(select(MemoryEvent).where(MemoryEvent.org_id==org_id,MemoryEvent.vendor_id==v.id,MemoryEvent.status=='submitted')).all()
            known={event.source_id:event.event_type for event in events}
            memory=retrieve_memory(org_id,v.id,known) if known else {'status':memory_status(),'evidence':[]}
            rows.append({'id':q.id,'vendor_id':v.id,'supplier':v.name,'prices':q.prices,'tax':q.tax,'freight':q.freight,'total':q.total,'currency':r.currency,'lead_days':q.lead_days,'eligible':not reasons,'reasons':reasons,'history':history,'memory':memory})
        return sorted(rows,key=lambda x:(not x['eligible'],Decimal(x['total'])))
@router.post('/{org_id}/quotes/{quote_id}/approve')
def approve_quote(org_id:str,quote_id:str,user:str=Depends(require_org)):
    with Session.begin() as db:
        q=get_owned(db,Quote,quote_id,org_id);r=db.scalar(select(PurchaseRequest).where(PurchaseRequest.id==q.request_id,PurchaseRequest.org_id==org_id).with_for_update())
        if not r: raise HTTPException(404,'Record not found.')
        if r.status!='open' or db.scalar(select(Order.id).where(Order.request_id==r.id)): raise HTTPException(409,'An order already exists for this request.')
        v=db.get(Vendor,q.vendor_id)
        if not v.approved or Decimal(q.total)>Decimal(r.budget): raise HTTPException(400,'This quote is not eligible.')
        try: late=now().date()+timedelta(days=q.lead_days)>datetime.fromisoformat(r.deadline).date()
        except ValueError: raise HTTPException(400,'Deadline is invalid.')
        if late: raise HTTPException(400,'This quote does not meet the deadline.')
        lines=[{**l,'unit_price':p} for l,p in zip(r.lines,q.prices)]
        o=Order(id=uid('po'),org_id=org_id,request_id=r.id,vendor_id=q.vendor_id,quote_id=q.id,lines=lines,currency=r.currency,tax=q.tax,freight=q.freight,total=q.total,created_at=now());db.add(o);r.status='ordered';audit(db,org_id,r.id,'purchase_order_created',user);return order_json(o)
@router.get('/{org_id}/orders')
def orders(org_id:str,user:str=Depends(require_org)):
    with Session() as db: return [order_json(o) for o in db.scalars(select(Order).where(Order.org_id==org_id).order_by(Order.created_at.desc())).all()]
@router.post('/{org_id}/orders/{order_id}/supplier-link')
def order_supplier_link(org_id:str,order_id:str,user:str=Depends(require_org)):
    with Session.begin() as db:
        o=get_owned(db,Order,order_id,org_id);token=secrets.token_urlsafe(32)
        inv=Invitation(id=uid('inv'),org_id=org_id,request_id=o.request_id,vendor_id=o.vendor_id,token_hash=hashlib.sha256(token.encode()).hexdigest(),expires_at=now()+timedelta(days=7),revoked=False)
        db.add(inv);audit(db,org_id,o.id,'supplier_order_link_created',user)
        return {'id':inv.id,'url':os.getenv('PUBLIC_APP_URL','http://localhost:3000').rstrip('/')+'/supplier#'+token,'expires_at':inv.expires_at.isoformat()}
@router.post('/{org_id}/orders/{order_id}/receipts')
def receipt(org_id:str,order_id:str,data:ReceiptIn,user:str=Depends(require_org)):
    with Session.begin() as db:
        o=db.scalar(select(Order).where(Order.id==order_id,Order.org_id==org_id).with_for_update())
        if not o: raise HTTPException(404,'Record not found.')
        key=data.idempotency_key or uid('receiptkey')
        previous=db.scalar(select(Receipt).where(Receipt.org_id==org_id,Receipt.order_id==o.id,Receipt.idempotency_key==key))
        if previous: return {'id':previous.id,'quantities':previous.quantities,'memory_status':'already_recorded'}
        if len(data.quantities)!=len(o.lines): raise HTTPException(422,'Enter each received quantity.')
        amounts=[]
        for x in data.quantities:
            try:
                val=Decimal(x)
                if not val.is_finite() or val<0 or val>Decimal('1000000000'): raise ValueError()
                amounts.append(str(val.quantize(Decimal('.001'))))
            except (InvalidOperation,ValueError): raise HTTPException(422,'Enter valid received quantities.')
        if all(Decimal(x)==0 for x in amounts): raise HTTPException(422,'Enter at least one received quantity.')
        received_on=data.received_on or now().date().isoformat()
        try:
            received_date=datetime.fromisoformat(received_on).date()
            deadline=datetime.fromisoformat(db.get(PurchaseRequest,o.request_id).deadline).date()
        except ValueError: raise HTTPException(422,'Enter a valid receipt date.')
        rec=Receipt(id=uid('grn'),org_id=org_id,order_id=o.id,idempotency_key=key,quantities=amounts,note=data.note,received_on=received_on,quality_ok=data.quality_ok,created_at=now());db.add(rec);audit(db,org_id,o.id,'goods_received',user)
        event_type=('on_time' if received_date<=deadline else 'late')+('_quality_ok' if data.quality_ok else '_quality_issue')
        event=MemoryEvent(id=uid('memory'),org_id=org_id,vendor_id=o.vendor_id,source_id=rec.id,event_type=event_type,status='pending');db.add(event)
        event_id=event.id;receipt_id=rec.id
    return {'id':receipt_id,'quantities':amounts,'memory_status':send_memory(event_id)}
@router.post('/portal/invoice')
def submit_invoice(data:InvoiceIn,token:str=Header(alias='X-Supplier-Token')):
    with Session.begin() as db:
        inv=invitation_for(db,token);o=db.scalar(select(Order).where(Order.request_id==inv.request_id,Order.vendor_id==inv.vendor_id).with_for_update())
        if not o: raise HTTPException(400,'No purchase order has been issued to this supplier.')
        if len(data.lines)!=len(o.lines): raise HTTPException(422,'Provide an invoice quantity and price for every item.')
        number=data.number.strip().upper()
        if not number: raise HTTPException(422,'Enter an invoice number.')
        if db.scalar(select(Invoice.id).where(Invoice.org_id==inv.org_id,Invoice.vendor_id==inv.vendor_id,Invoice.number==number)): raise HTTPException(409,'This supplier invoice number already exists.')
        lines=[{'quantity':str(nonnegative_qty(l.quantity)),'unit_price':str(money(l.unit_price))} for l in data.lines]
        if not any(Decimal(l['quantity'])>0 for l in lines): raise HTTPException(422,'Invoice at least one item.')
        tax=money(data.tax);freight=money(data.freight);total=sum((Decimal(l['quantity'])*Decimal(l['unit_price']) for l in lines),Decimal(0))+tax+freight
        i=Invoice(id=uid('invoice'),org_id=inv.org_id,order_id=o.id,vendor_id=inv.vendor_id,number=number,lines=lines,tax=str(tax),freight=str(freight),total=str(total.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)),status='submitted',created_at=now());db.add(i);audit(db,inv.org_id,o.id,'invoice_submitted','supplier');return {'id':i.id,'total':i.total}

@router.post('/portal/invoices/{invoice_id}/attachment')
async def upload_invoice(invoice_id:str,file:UploadFile=File(...),token:str=Header(alias='X-Supplier-Token')):
    with Session() as db:
        inv=invitation_for(db,token);i=get_owned(db,Invoice,invoice_id,inv.org_id)
        o=db.get(Order,i.order_id)
        if i.vendor_id!=inv.vendor_id or o.request_id!=inv.request_id: raise HTTPException(404,'Invoice not found.')
        if i.attachment_path: raise HTTPException(409,'An invoice file is already attached.')
        org_id=inv.org_id
    raw=await file.read(5*1024*1024+1)
    if len(raw)>5*1024*1024: raise HTTPException(413,'File must be under 5 MB.')
    if raw.startswith(b'%PDF-'): content_type='application/pdf';extension='pdf'
    elif raw.startswith(b'\x89PNG\r\n\x1a\n'): content_type='image/png';extension='png'
    elif raw.startswith(b'\xff\xd8\xff'): content_type='image/jpeg';extension='jpg'
    else: raise HTTPException(422,'Upload a PDF, PNG or JPEG invoice.')
    url=os.getenv('SUPABASE_URL','').rstrip('/');key=os.getenv('SUPABASE_SERVICE_ROLE_KEY','');bucket=os.getenv('SUPABASE_STORAGE_BUCKET','vendormind-invoices')
    if not url or not key: raise HTTPException(503,'Private document storage is not configured.')
    path=f'{org_id}/{invoice_id}/{secrets.token_hex(12)}.{extension}'
    try:
        result=httpx.post(f'{url}/storage/v1/object/{bucket}/{path}',headers={'Authorization':f'Bearer {key}','apikey':key,'Content-Type':content_type,'x-upsert':'false'},content=raw,timeout=15)
        result.raise_for_status()
    except Exception: raise HTTPException(503,'Invoice upload failed; please retry.')
    with Session.begin() as db:
        i=get_owned(db,Invoice,invoice_id,org_id);i.attachment_path=path;audit(db,org_id,i.order_id,'invoice_attachment_added','supplier')
    return {'uploaded':True}

def match_invoice(order, invoice, receipts, others=()):
    exceptions=[]; details=[]
    if not receipts: exceptions.append('No goods receipt has been recorded.')
    for receipt in receipts:
        if not receipt.quality_ok: exceptions.append(f'Quality issue recorded for receipt {receipt.id}; manual review required.')
    for n,(po, line) in enumerate(zip(order.lines,invoice.lines)):
        received=sum((Decimal(r.quantities[n]) for r in receipts),Decimal(0))
        ordered=Decimal(po['quantity']); billed=Decimal(line['quantity'])
        problems=[]
        if Decimal(po['unit_price'])!=Decimal(line['unit_price']): problems.append('Unit price differs from purchase order')
        if billed>ordered: problems.append('Invoiced quantity exceeds purchase order')
        other_billed=sum((Decimal(other.lines[n]['quantity']) for other in others),Decimal(0))
        if billed+other_billed>received: problems.append('Total invoiced quantity exceeds received quantity')
        if billed+other_billed>ordered: problems.append('Total invoiced quantity exceeds purchase order')
        if received>ordered: problems.append('Received quantity exceeds purchase order')
        exceptions.extend([f"{po['description']}: {p}" for p in problems])
        details.append({'description':po['description'],'ordered':str(ordered),'received':str(received),'invoiced':str(billed),'po_unit_price':po['unit_price'],'invoice_unit_price':line['unit_price'],'exceptions':problems})
    if Decimal(order.tax)!=Decimal(invoice.tax): exceptions.append('Tax differs from purchase order.')
    if Decimal(order.freight)!=Decimal(invoice.freight): exceptions.append('Freight differs from purchase order.')
    return {'matched':not exceptions,'exceptions':exceptions,'lines':details,'currency':order.currency}
@router.get('/{org_id}/orders/{order_id}/invoices')
def invoices(org_id:str,order_id:str,user:str=Depends(require_org)):
    with Session() as db:
        o=get_owned(db,Order,order_id,org_id);receipts=db.scalars(select(Receipt).where(Receipt.org_id==org_id,Receipt.order_id==o.id)).all()
        all_invoices=db.scalars(select(Invoice).where(Invoice.org_id==org_id,Invoice.order_id==o.id)).all()
        return [{'id':i.id,'number':i.number,'total':i.total,'status':i.status,'resolution':i.resolution,'attachment':bool(i.attachment_path),'match':match_invoice(o,i,receipts,[other for other in all_invoices if other.id!=i.id])} for i in all_invoices]
@router.get('/{org_id}/invoices/{invoice_id}/attachment')
def invoice_attachment(org_id:str,invoice_id:str,user:str=Depends(require_org)):
    with Session() as db:
        i=get_owned(db,Invoice,invoice_id,org_id)
        if not i.attachment_path: raise HTTPException(404,'No attachment.')
        path=i.attachment_path
    url=os.getenv('SUPABASE_URL','').rstrip('/');key=os.getenv('SUPABASE_SERVICE_ROLE_KEY','');bucket=os.getenv('SUPABASE_STORAGE_BUCKET','vendormind-invoices')
    if not url or not key: raise HTTPException(503,'Private document storage is not configured.')
    try:
        response=httpx.post(f'{url}/storage/v1/object/sign/{bucket}/{path}',headers={'Authorization':f'Bearer {key}','apikey':key},json={'expiresIn':60},timeout=5);response.raise_for_status()
        return {'url':url+'/storage/v1'+response.json()['signedURL']}
    except Exception: raise HTTPException(503,'Unable to open attachment.')
@router.post('/{org_id}/invoices/{invoice_id}/resolve')
def resolve(org_id:str,invoice_id:str,data:ResolutionIn,user:str=Depends(require_org)):
    with Session.begin() as db:
        i=get_owned(db,Invoice,invoice_id,org_id);i.status='reviewed';i.resolution=data.note;audit(db,org_id,i.order_id,'invoice_reviewed',user)
        event=MemoryEvent(id=uid('memory'),org_id=org_id,vendor_id=i.vendor_id,source_id=i.id,event_type='invoice_reviewed',status='pending');db.add(event);event_id=event.id
    return {'status':'reviewed','memory_status':send_memory(event_id),'note':'Review recorded. No payment was initiated.'}
@router.post('/{org_id}/memory/retry')
def retry_memory(org_id:str,user:str=Depends(require_org)):
    with Session() as db:
        ids=db.scalars(select(MemoryEvent.id).where(MemoryEvent.org_id==org_id,MemoryEvent.status.in_(['pending','failed','not_configured'])).limit(10)).all()
    statuses=[send_memory(id) for id in ids]
    return {'submitted':statuses.count('submitted'),'pending':len(statuses)-statuses.count('submitted')}
@router.get('/{org_id}/audit')
def history(org_id:str,user:str=Depends(require_org)):
    with Session() as db: return [{'id':a.id,'subject_id':a.subject_id,'action':a.action,'created_at':a.created_at.isoformat()} for a in db.scalars(select(Audit).where(Audit.org_id==org_id).order_by(Audit.created_at.desc()).limit(100)).all()]
