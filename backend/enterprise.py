"""Additive multi-branch workspace. Pilot records remain the purchasing source of truth."""
from datetime import timedelta
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import String, ForeignKey, JSON, select
from sqlalchemy.orm import Mapped, mapped_column
from backend.app import Base, Session
from backend.pilot import (DEMO_ORG, Member, PurchaseRequest, Vendor, audit, get_owned,
                           money, qty, now, require_org, uid)

router = APIRouter(prefix='/api/enterprise', tags=['enterprise'])

class Branch(Base):
    __tablename__='orrfin_branches'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    org_id:Mapped[str]=mapped_column(ForeignKey('pilot_organizations.id'),index=True)
    name:Mapped[str]=mapped_column(String)
    city:Mapped[str]=mapped_column(String)
    code:Mapped[str]=mapped_column(String)

class ApprovalRule(Base):
    __tablename__='orrfin_approval_rules'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    org_id:Mapped[str]=mapped_column(ForeignKey('pilot_organizations.id'),index=True)
    branch_id:Mapped[str]=mapped_column(String,default='*')
    category:Mapped[str]=mapped_column(String,default='*')
    threshold:Mapped[str]=mapped_column(String)
    approver:Mapped[str]=mapped_column(String)

class Intake(Base):
    __tablename__='orrfin_intakes'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    org_id:Mapped[str]=mapped_column(ForeignKey('pilot_organizations.id'),index=True)
    branch_id:Mapped[str]=mapped_column(ForeignKey('orrfin_branches.id'))
    title:Mapped[str]=mapped_column(String)
    category:Mapped[str]=mapped_column(String)
    amount:Mapped[str]=mapped_column(String)
    quantity:Mapped[str]=mapped_column(String)
    unit:Mapped[str]=mapped_column(String)
    deadline:Mapped[str]=mapped_column(String)
    owner:Mapped[str]=mapped_column(String)
    approver:Mapped[str]=mapped_column(String)
    status:Mapped[str]=mapped_column(String)
    request_id:Mapped[str|None]=mapped_column(String,nullable=True)
    created_at:Mapped[str]=mapped_column(String)

class SupplierReview(Base):
    __tablename__='orrfin_supplier_reviews'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    org_id:Mapped[str]=mapped_column(ForeignKey('pilot_organizations.id'),index=True)
    vendor_id:Mapped[str]=mapped_column(ForeignKey('pilot_vendors.id'))
    tier:Mapped[str]=mapped_column(String)
    evidence:Mapped[str]=mapped_column(String)
    review_date:Mapped[str]=mapped_column(String)
    created_at:Mapped[str]=mapped_column(String)

class BranchIn(BaseModel):
    name:str=Field(min_length=1,max_length=120)
    city:str=Field(min_length=1,max_length=120)
    code:str=Field(min_length=1,max_length=30,pattern=r'^[A-Za-z0-9_-]+$')
class RuleIn(BaseModel):
    branch_id:str='*'
    category:str=Field(default='*',min_length=1,max_length=100)
    threshold:str
    approver:str=Field(min_length=1,max_length=120)
class IntakeIn(BaseModel):
    branch_id:str
    title:str=Field(min_length=1,max_length=160)
    category:str=Field(min_length=1,max_length=100)
    amount:str
    quantity:str
    unit:str=Field(min_length=1,max_length=30)
    deadline:str=Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
class ReviewIn(BaseModel):
    vendor_id:str
    tier:str=Field(pattern='^(low|medium|high)$')
    evidence:str=Field(min_length=3,max_length=1000)
    review_date:str=Field(pattern=r'^\d{4}-\d{2}-\d{2}$')

# The old pilot endpoints grant access to entire organizations. Until branch-level
# permissions are implemented end-to-end, do not pretend branch users are isolated.
def require_owner(org_id:str, user:str=Depends(require_org)):
    with Session() as db:
        role=db.scalar(select(Member.role).where(Member.org_id==org_id,Member.user_id==user))
        if role!='owner': raise HTTPException(403,'Only workspace owners can use this preview.')
    return user

def seed_branches(db,org):
    if org!=DEMO_ORG or db.scalar(select(Branch.id).where(Branch.org_id==org).limit(1)): return
    names=[('BLR-01','Bengaluru Central','Bengaluru'),('BLR-02','Bengaluru North','Bengaluru'),('HYD-01','Hyderabad Central','Hyderabad'),('HYD-02','Hyderabad West','Hyderabad'),('MUM-01','Mumbai Central','Mumbai'),('MUM-02','Mumbai West','Mumbai'),('DEL-01','Delhi Central','Delhi'),('DEL-02','Delhi South','Delhi'),('PUN-01','Pune Central','Pune'),('CHN-01','Chennai Central','Chennai')]
    for code,name,city in names: db.add(Branch(id='branch_demo_'+code,org_id=org,name=name,city=city,code=code))
    db.add(ApprovalRule(id='rule_demo_default',org_id=org,branch_id='*',category='*',threshold='0.00',approver='Central procurement'))
    db.flush()
    for i,(code,name,city) in enumerate(names[:5]):
        db.add(Intake(id='intake_demo_'+str(i),org_id=org,branch_id='branch_demo_'+code,title=['Cold-chain packaging','Store cleaning supplies','Delivery crates','Safety equipment','Warehouse shelving'][i],category=['Packaging','Facilities','Operations','Safety','Facilities'][i],amount=['125000.00','42000.00','87000.00','36000.00','210000.00'][i],quantity='100.000',unit='unit',deadline=(now().date()+timedelta(days=14)).isoformat(),owner='Branch operations',approver='Central procurement',status='pending',request_id=None,created_at=now().isoformat()))

def branch_json(x):return {'id':x.id,'name':x.name,'city':x.city,'code':x.code}
def intake_json(x):return {'id':x.id,'branch_id':x.branch_id,'title':x.title,'category':x.category,'amount':x.amount,'quantity':x.quantity,'unit':x.unit,'deadline':x.deadline,'owner':x.owner,'approver':x.approver,'status':x.status,'request_id':x.request_id,'created_at':x.created_at}

@router.get('/{org_id}/overview')
def overview(org_id:str,user:str=Depends(require_owner)):
    with Session.begin() as db:
        seed_branches(db,org_id)
        branches=db.scalars(select(Branch).where(Branch.org_id==org_id).order_by(Branch.code)).all()
        intakes=db.scalars(select(Intake).where(Intake.org_id==org_id).order_by(Intake.created_at.desc())).all()
        rules=db.scalars(select(ApprovalRule).where(ApprovalRule.org_id==org_id)).all()
        reviews=db.scalars(select(SupplierReview).where(SupplierReview.org_id==org_id)).all()
        return {'branches':[branch_json(x) for x in branches], 'intakes':[intake_json(x) for x in intakes], 'rules':[{'id':x.id,'branch_id':x.branch_id,'category':x.category,'threshold':x.threshold,'approver':x.approver} for x in rules], 'reviews':[{'id':x.id,'vendor_id':x.vendor_id,'tier':x.tier,'evidence':x.evidence,'review_date':x.review_date} for x in reviews], 'capabilities':{'erp':'not_configured','tinyfish':'not_configured','ai':'not_configured','ocr':'not_configured'}}

@router.post('/{org_id}/branches')
def create_branch(org_id:str,data:BranchIn,user:str=Depends(require_owner)):
    with Session.begin() as db:
        if db.scalar(select(Branch.id).where(Branch.org_id==org_id,Branch.code==data.code.upper())): raise HTTPException(409,'Branch code already exists.')
        b=Branch(id=uid('branch'),org_id=org_id,name=data.name.strip(),city=data.city.strip(),code=data.code.upper());db.add(b);audit(db,org_id,b.id,'branch_created',user)
        return branch_json(b)

@router.post('/{org_id}/rules')
def create_rule(org_id:str,data:RuleIn,user:str=Depends(require_owner)):
    threshold=str(money(data.threshold))
    with Session.begin() as db:
        if data.branch_id!='*':get_owned(db,Branch,data.branch_id,org_id)
        r=ApprovalRule(id=uid('rule'),org_id=org_id,branch_id=data.branch_id,category=data.category.strip(),threshold=threshold,approver=data.approver.strip());db.add(r);audit(db,org_id,r.id,'approval_rule_created',user)
        return {'id':r.id}

@router.post('/{org_id}/intakes')
def create_intake(org_id:str,data:IntakeIn,user:str=Depends(require_owner)):
    amount=money(data.amount)
    if amount<=0: raise HTTPException(422,'Enter an amount greater than zero.')
    with Session.begin() as db:
        get_owned(db,Branch,data.branch_id,org_id)
        rules=db.scalars(select(ApprovalRule).where(ApprovalRule.org_id==org_id)).all()
        applicable=[r for r in rules if r.branch_id in ('*',data.branch_id) and r.category.lower() in ('*',data.category.strip().lower()) and money(r.threshold)<=amount]
        applicable.sort(key=lambda r:(money(r.threshold),r.branch_id!='*',r.category!='*',r.id),reverse=True)
        i=Intake(id=uid('intake'),org_id=org_id,branch_id=data.branch_id,title=data.title.strip(),category=data.category.strip(),amount=str(amount),quantity=str(qty(data.quantity)),unit=data.unit.strip(),deadline=data.deadline,owner=user,approver=applicable[0].approver if applicable else 'Unassigned — configure an approval rule',status='pending',request_id=None,created_at=now().isoformat());db.add(i);audit(db,org_id,i.id,'intake_created',user)
        return intake_json(i)

@router.post('/{org_id}/intakes/{intake_id}/approve')
def approve_intake(org_id:str,intake_id:str,user:str=Depends(require_owner)):
    with Session.begin() as db:
        i=db.scalar(select(Intake).where(Intake.id==intake_id,Intake.org_id==org_id).with_for_update())
        if not i: raise HTTPException(404,'Record not found.')
        if i.status!='pending':raise HTTPException(409,'This intake has already been decided.')
        if i.approver.startswith('Unassigned'):raise HTTPException(409,'Configure an approval rule before deciding this intake.')
        branch=get_owned(db,Branch,i.branch_id,org_id)
        request=PurchaseRequest(id=uid('req'),org_id=org_id,title=i.title,location=branch.name+', '+branch.city,deadline=i.deadline,budget=i.amount,currency='INR',lines=[{'description':i.title,'quantity':i.quantity,'unit':i.unit}],status='open',created_at=now())
        db.add(request);i.status='approved';i.request_id=request.id;audit(db,org_id,i.id,'intake_approved_request_created',user)
        return intake_json(i)

@router.post('/{org_id}/supplier-reviews')
def create_review(org_id:str,data:ReviewIn,user:str=Depends(require_owner)):
    with Session.begin() as db:
        get_owned(db,Vendor,data.vendor_id,org_id)
        x=SupplierReview(id=uid('risk'),org_id=org_id,vendor_id=data.vendor_id,tier=data.tier,evidence=data.evidence.strip(),review_date=data.review_date,created_at=now().isoformat());db.add(x);audit(db,org_id,x.id,'supplier_risk_review_recorded',user)
        return {'id':x.id}

@router.post('/{org_id}/branches/import')
async def import_branches(org_id:str,file:UploadFile=File(...),user:str=Depends(require_owner)):
    import csv
    import io
    raw=await file.read(256*1024+1)
    if len(raw)>256*1024:raise HTTPException(413,'Branch CSV must be under 256 KB.')
    try:
        reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
        if not reader.fieldnames or not {'name','city','code'}.issubset(set(reader.fieldnames)): raise ValueError()
        rows=list(reader)
        if not 1<=len(rows)<=500:raise ValueError()
        parsed=[BranchIn(name=(r.get('name') or '').strip(),city=(r.get('city') or '').strip(),code=(r.get('code') or '').strip().upper()) for r in rows]
    except Exception:raise HTTPException(422,'Provide a UTF-8 CSV with name, city, code and 1–500 valid rows.')
    codes=[r.code for r in parsed]
    if len(codes)!=len(set(codes)):raise HTTPException(409,'Branch codes must be unique in the CSV.')
    with Session.begin() as db:
        existing=set(db.scalars(select(Branch.code).where(Branch.org_id==org_id,Branch.code.in_(codes))).all())
        if existing:raise HTTPException(409,'One or more branch codes already exist. No branches were imported.')
        for r in parsed:db.add(Branch(id=uid('branch'),org_id=org_id,name=r.name,city=r.city,code=r.code))
        audit(db,org_id,org_id,'branches_imported',user)
        return {'imported':len(parsed)}
