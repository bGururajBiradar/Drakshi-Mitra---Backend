from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from django.db.models import Sum, Count, Q, F, Value, DecimalField
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone
from .models import *

ZERO=Decimal("0")
def money(x): return float((Decimal(x or 0)).quantize(Decimal("0.01"),rounding=ROUND_HALF_UP))

def growth_stage(cycle):
    planting=cycle.planting_date or cycle.farm.planting_date
    if not planting: return {"name":"Not available","order":None,"days_since_planting":None}
    days=(date.today()-planting).days
    rules=list(GrowthStageRule.objects.filter(is_active=True).order_by("order"))
    overrides={x.stage_id:x for x in cycle.stage_overrides.all()}
    for rule in rules:
        r=overrides.get(rule.id); start=r.start_day if r else rule.start_day; end=r.end_day if r else rule.end_day
        if start<=days<=end: return {"name":rule.name,"order":rule.order,"days_since_planting":days}
    if rules and days<rules[0].start_day: return {"name":"Pre-stage","order":0,"days_since_planting":days}
    return {"name":"Dormancy","order":rules[-1].order if rules else None,"days_since_planting":days}

def calculate_loan(loan, as_of=None):
    as_of=as_of or date.today()
    principal=Decimal(loan.principal_amount); current=principal; accrued_interest=ZERO; interest_paid=ZERO; principal_paid=ZERO; total_accrued=ZERO
    cursor=loan.start_date
    for repayment in loan.repayments.filter(payment_date__lte=as_of).order_by("payment_date","created_at"):
        end=max(cursor,repayment.payment_date)
        days=max(0,(end-cursor).days)
        interest=(current*Decimal(loan.annual_interest_rate)/Decimal(100)*Decimal(days)/Decimal(365))
        accrued_interest += interest; total_accrued += interest
        amount=Decimal(repayment.amount)
        if repayment.payment_type==LoanRepayment.PaymentType.PRINCIPAL_ONLY:
            p=min(current,amount); current-=p; principal_paid+=p
        elif repayment.payment_type==LoanRepayment.PaymentType.FULL_SETTLEMENT:
            i=min(accrued_interest,amount); accrued_interest-=i; interest_paid+=i; amount-=i
            p=min(current,amount); current-=p; principal_paid+=p
        elif repayment.payment_type==LoanRepayment.PaymentType.INTEREST_ONLY:
            i=min(accrued_interest,amount); accrued_interest-=i; interest_paid+=i
        else:
            i=min(accrued_interest,amount); accrued_interest-=i; interest_paid+=i; amount-=i
            p=min(current,amount); current-=p; principal_paid+=p
        cursor=end
    days=max(0,(as_of-cursor).days)
    interest=(current*Decimal(loan.annual_interest_rate)/Decimal(100)*Decimal(days)/Decimal(365))
    accrued_interest+=interest; total_accrued+=interest
    total_paid=principal_paid+interest_paid
    return {"originalPrincipal":money(principal),"currentPrincipal":money(current),"accruedInterest":money(accrued_interest),
            "totalInterestAccruedAllTime":money(total_accrued),"totalPrincipalPaid":money(principal_paid),
            "totalInterestPaid":money(interest_paid),"totalPaid":money(total_paid),
            "totalOutstanding":money(current+accrued_interest),"elapsedDays":max(0,(as_of-loan.start_date).days),
            "dailyInterestRate":money(current*Decimal(loan.annual_interest_rate)/Decimal(100)/Decimal(365)),
            "isCompleted": current<=Decimal("0.01") and accrued_interest<=Decimal("0.01")}

def dashboard(user,farm=None,cycle=None):
    if user.role==User.Role.ADMIN: farms=Farm.objects.all()
    elif user.role==User.Role.SUPERVISOR: farms=Farm.objects.filter(supervisor_assignments__supervisor=user,supervisor_assignments__is_active=True)
    else: farms=Farm.objects.filter(owner=user)
    farm=farm or farms.filter(is_active=True).first()
    if not farm: return {"farm":None,"crop_cycle":None,"growth_stage":None,"stats":{},"todayActivities":[],"attention":[]}
    cycle=cycle or farm.cycles.filter(is_active=True).order_by("-start_date").first()
    if not cycle: return {"farm":FarmSerializerForService(farm),"crop_cycle":None,"growth_stage":None,"stats":{},"todayActivities":[],"attention":[]}
    today=date.today()
    sprays=SprayRecord.objects.filter(farm=farm,cycle=cycle)
    times=TimesheetEntry.objects.filter(farm=farm,cycle=cycle)
    purchases=FarmInputPurchase.objects.filter(farm=farm,cycle=cycle,is_deleted=False)
    stats={
      "spraysScheduled":sprays.filter(spray_date=today).count(),
      "spraysCompleted":sprays.filter(status=SprayRecord.Status.COMPLETED).count(),
      "spraysPending":sprays.filter(status=SprayRecord.Status.SCHEDULED).count(),
      "labourers":times.values("labour_id").distinct().count(),
      "labourCostToday":money(times.filter(date=today).aggregate(v=Sum("daily_wage"))["v"] or 0),
      "labourPaidToday":money(times.filter(date=today).aggregate(v=Sum("paid_amount"))["v"] or 0),
      "labourPendingToday":money(times.filter(date=today).aggregate(v=Sum(F("daily_wage")-F("paid_amount")))["v"] or 0),
      "inputExpense":money(sum((p.total_amount for p in purchases),ZERO)),
      "loanOutstanding":money(sum((Decimal(str(calculate_loan(l)["totalOutstanding"])) for l in Loan.objects.filter(owner=user,is_archived=False)),ZERO)),
    }
    activities=[]
    for s in sprays.filter(spray_date=today).order_by("scheduled_time")[:10]:
        activities.append({"title":f"Spray: {s.product}","subtitle":s.purpose or s.type or "Farm spray","status":s.status})
    for t in times.filter(date=today).select_related("labour")[:10]:
        activities.append({"title":f"Labour: {t.labour.name}","subtitle":f"{t.hours} hours • ₹{t.daily_wage}","status":"Recorded"})
    attention=[]
    if sprays.filter(spray_date=today,status=SprayRecord.Status.SCHEDULED).exists(): attention.append({"title":"Spray scheduled today","subtitle":"Review and complete today's planned spray.","kind":"SPRAY"})
    if times.filter(date__gte=today-timedelta(days=7)).aggregate(v=Sum(F("daily_wage")-F("paid_amount")))["v"] or 0:
        attention.append({"title":"Labour payment pending","subtitle":"Review outstanding labour payments.","kind":"LABOUR"})
    return {"farm":FarmSerializerForService(farm),"crop_cycle":{"id":str(cycle.id),"name":cycle.name,"start_date":str(cycle.start_date),"end_date":str(cycle.end_date)},
            "growth_stage":growth_stage(cycle),"stats":stats,"todayActivities":activities,"attention":attention}

def FarmSerializerForService(farm):
    stage=None
    cycle=farm.cycles.filter(is_active=True).order_by("-start_date").first()
    if cycle: stage=growth_stage(cycle).get("name")
    return {"id":str(farm.id),"name":farm.name,"location":farm.location,"area_acres":money(farm.area_acres),"area_gunta":money(farm.area_gunta),
            "crop":farm.crop,"variety":farm.variety.name if farm.variety else None,"plants_count":farm.plants_count,"blocks_count":farm.blocks_count,
            "growth_stage":stage,"planting_date":str(farm.planting_date) if farm.planting_date else None,
            "expected_harvest":str(farm.expected_harvest) if farm.expected_harvest else None}

def report(user,start,end,farm=None,cycle=None):
    filters={}
    if farm: filters["farm"]=farm
    if cycle: filters["cycle"]=cycle
    labour=TimesheetEntry.objects.filter(owner=user,date__range=[start,end],**filters)
    purchases=FarmInputPurchase.objects.filter(owner=user,purchase_date__range=[start,end],is_deleted=False,**filters)
    expenses=Expense.objects.filter(owner=user,date__range=[start,end],is_deleted=False,**filters)
    loans=Loan.objects.filter(owner=user,is_archived=False)
    labour_cost=labour.aggregate(v=Sum("daily_wage"))["v"] or ZERO
    input_cost=sum((p.total_amount for p in purchases),ZERO)
    direct=expenses.filter(source_type=Expense.Source.DIRECT).aggregate(v=Sum("amount"))["v"] or ZERO
    by_cat={}
    for e in expenses.filter(source_type=Expense.Source.DIRECT).select_related("category"):
        by_cat[e.category.name]=by_cat.get(e.category.name,ZERO)+e.amount
    by_cat["Labour"]=by_cat.get("Labour",ZERO)+labour_cost
    for p in purchases:
        label={"FERTILIZER":"Fertilizer","FUNGICIDE":"Sprays","PESTICIDE":"Sprays","OTHER":"Other"}.get(p.input_type,"Other")
        by_cat[label]=by_cat.get(label,ZERO)+p.total_amount
    total=labour_cost+input_cost+direct
    monthly={}
    for t in labour:
        key=t.date.strftime("%Y-%m"); monthly[key]=monthly.get(key,ZERO)+t.daily_wage
    for p in purchases:
        key=p.purchase_date.strftime("%Y-%m"); monthly[key]=monthly.get(key,ZERO)+p.total_amount
    for e in expenses.filter(source_type=Expense.Source.DIRECT):
        key=e.date.strftime("%Y-%m"); monthly[key]=monthly.get(key,ZERO)+e.amount
    return {"start":str(start),"end":str(end),"total_expenses":money(total),"labour_cost":money(labour_cost),
            "fertilizer_cost":money(sum((p.total_amount for p in purchases.filter(input_type=FarmInputPurchase.InputType.FERTILIZER)),ZERO)),
            "spray_cost":money(sum((p.total_amount for p in purchases.filter(input_type__in=[FarmInputPurchase.InputType.FUNGICIDE,FarmInputPurchase.InputType.PESTICIDE])),ZERO)),
            "other_cost":money(direct),"total_purchases":money(input_cost),
            "loan_outstanding":money(sum((Decimal(str(calculate_loan(l)["totalOutstanding"])) for l in loans),ZERO)),
            "monthly_trend":[{"label":k,"value":money(v)} for k,v in sorted(monthly.items())],
            "category_breakdown":[{"label":k,"value":money(v)} for k,v in sorted(by_cat.items())]}

def create_linked_expense(purchase):
    category, _=ExpenseCategory.objects.get_or_create(owner=purchase.owner,name="Fertilizer" if purchase.input_type=="FERTILIZER" else "Sprays")
    Expense.objects.update_or_create(source_purchase=purchase,defaults={"owner":purchase.owner,"farm":purchase.farm,"cycle":purchase.cycle,"category":category,
        "description":f"{purchase.product} purchase","amount":purchase.total_amount,"date":purchase.purchase_date,"source_type":Expense.Source.LINKED})
