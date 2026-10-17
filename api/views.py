import io, json, zipfile, hashlib
from datetime import date, timedelta
from decimal import Decimal
import requests
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.fernet import Fernet
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets, permissions
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.tokens import RefreshToken
from .models import *
from .serializers import *
from .services import dashboard, report, create_linked_expense, calculate_loan
from .permissions import IsAdmin, IsFarmerOrAdmin, IsSupervisorOrAdmin, IsAdminOrSelf
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated



def scoped_qs(model,user):
    if model in [Farm,Labourer,InputProvider,ExpenseCategory,LoanProvider,Loan,TimesheetEntry,SprayRecord,FarmInputPurchase,Expense]:
        if user.role==User.Role.ADMIN: return model.objects.all()
        if model==Farm: return model.objects.filter(owner=user)
        if model==Labourer: return model.objects.filter(owner=user)
        if model==InputProvider: return model.objects.filter(owner=user)
        if model==ExpenseCategory: return model.objects.filter(owner=user)
        if model==LoanProvider: return model.objects.filter(owner=user)
        if model==Loan: return model.objects.filter(owner=user)
        return model.objects.filter(owner=user)
    if model==CropCycle:
        if user.role==User.Role.ADMIN: return model.objects.all()
        if user.role==User.Role.SUPERVISOR: return model.objects.filter(farm__supervisor_assignments__supervisor=user,farm__supervisor_assignments__is_active=True)
        return model.objects.filter(farm__owner=user)
    if model==LoanRepayment:
        if user.role==User.Role.ADMIN:return model.objects.all()
        return model.objects.filter(loan__owner=user)
    if model==Notification:
        return model.objects.all() if user.role==User.Role.ADMIN else model.objects.filter(owner=user)
    return model.objects.all()

class BaseScopedViewSet(viewsets.ModelViewSet):
    permission_classes=[permissions.IsAuthenticated]
    search_fields=[]; filterset_fields=[]; ordering_fields=["created_at"]
    model=None; serializer_class=None
    def get_queryset(self): return scoped_qs(self.model,self.request.user)
    def perform_create(self,serializer):
        if self.request.user.role==User.Role.SUPERVISOR:
            raise PermissionDenied("Supervisors cannot create financial or farm records.")
        serializer.save(owner=self.request.user)

class FarmViewSet(BaseScopedViewSet):
    model=Farm; serializer_class=FarmSerializer; filterset_fields=["is_active","variety"]; search_fields=["name","location","crop"]
    def get_queryset(self):
        u=self.request.user
        if u.role==User.Role.ADMIN:return Farm.objects.all()
        if u.role==User.Role.SUPERVISOR:return Farm.objects.filter(supervisor_assignments__supervisor=u,supervisor_assignments__is_active=True)
        return Farm.objects.filter(owner=u)
    def perform_update(self,serializer):
        if self.request.user.role==User.Role.SUPERVISOR: raise PermissionDenied("Supervisors cannot modify farms.")
        serializer.save()
    def perform_destroy(self,instance):
        if self.request.user.role==User.Role.SUPERVISOR: raise PermissionDenied("Supervisors cannot delete farms.")
        instance.delete()

class CropCycleViewSet(BaseScopedViewSet):
    model=CropCycle; serializer_class=CropCycleSerializer; filterset_fields=["farm","is_active"]; search_fields=["name"]
    def perform_create(self,serializer):
        if self.request.user.role!=User.Role.ADMIN and self.request.user.role!=User.Role.FARMER: raise PermissionDenied("Only farmers can create crop cycles.")
        serializer.save()
    def perform_update(self,serializer):
        if self.request.user.role==User.Role.SUPERVISOR: raise PermissionDenied("Supervisors cannot modify crop cycles.")
        serializer.save()
    def perform_destroy(self,instance):
        if self.request.user.role==User.Role.SUPERVISOR: raise PermissionDenied("Supervisors cannot delete crop cycles.")
        instance.delete()

class LabourViewSet(BaseScopedViewSet):
    model=Labourer; serializer_class=LabourerSerializer; filterset_fields=["status"]; search_fields=["name","phone"]

class TimesheetViewSet(BaseScopedViewSet):
    model=TimesheetEntry; serializer_class=TimesheetSerializer; filterset_fields=["farm","cycle","labour","date","attendance_type"]; search_fields=["labour__name","notes"]
    def perform_create(self,serializer): serializer.save(owner=self.request.user)
    @action(detail=False,methods=["post"],url_path="bulk")
    def bulk(self,request):
        ids=request.data.get("labourers",[]); farm_id=request.data.get("farm"); cycle_id=request.data.get("cycle")
        if not ids or not farm_id or not cycle_id: return Response({"detail":"farm, cycle and labourers are required."},status=400)
        farm=Farm.objects.filter(id=farm_id,owner=request.user).first()
        cycle=CropCycle.objects.filter(id=cycle_id,farm=farm).first()
        if not farm or not cycle:return Response({"detail":"Invalid farm/cycle."},status=400)
        labourers=Labourer.objects.filter(id__in=ids,owner=request.user)
        dt=request.data.get("date"); attendance=request.data.get("attendance_type","FULL_DAY"); wage=Decimal(str(request.data.get("daily_wage",0))); hours=Decimal(str(request.data.get("hours",8)))
        if wage<0 or hours<0 or hours>24:return Response({"detail":"Invalid wage/hours."},status=400)
        if attendance=="HALF_DAY": wage=wage/2
        elif attendance=="HOURLY": wage=wage*hours
        created=[]
        with transaction.atomic():
            for labour in labourers:
                obj,_=TimesheetEntry.objects.update_or_create(labour=labour,farm=farm,cycle=cycle,date=dt,defaults={"owner":request.user,"attendance_type":attendance,"hours":hours,"daily_wage":wage,"notes":request.data.get("notes","")})
                created.append(TimesheetSerializer(obj,context={"request":request}).data)
        return Response(created,status=status.HTTP_201_CREATED)

class SprayViewSet(BaseScopedViewSet):
    model=SprayRecord; serializer_class=SpraySerializer; filterset_fields=["farm","cycle","status","spray_date"]; search_fields=["product","purpose","notes"]
    def get_queryset(self):
        u=self.request.user
        if u.role==User.Role.ADMIN:return SprayRecord.objects.all()
        if u.role==User.Role.SUPERVISOR:return SprayRecord.objects.filter(farm__supervisor_assignments__supervisor=u,farm__supervisor_assignments__is_active=True)
        return SprayRecord.objects.filter(owner=u)
    def perform_create(self,serializer):
        farm=serializer.validated_data["farm"]
        if self.request.user.role==User.Role.SUPERVISOR:
            if not SupervisorFarmAssignment.objects.filter(supervisor=self.request.user,farm=farm,is_active=True).exists(): raise PermissionDenied("Farm is not assigned to this supervisor.")
            serializer.save(owner=farm.owner,supervisor=self.request.user)
        else: serializer.save(owner=self.request.user,supervisor=self.request.user if self.request.user.role==User.Role.SUPERVISOR else None)
    def perform_update(self,serializer):
        if self.request.user.role==User.Role.FARMER:
            allowed={"status","notes"}
            if set(serializer.validated_data)-allowed: raise PermissionDenied("Farmers can only update spray completion/status and notes.")
        serializer.save()
    @action(detail=True,methods=["post"])
    def complete(self,request,pk=None):
        obj=self.get_object(); obj.status=SprayRecord.Status.COMPLETED; obj.completed_date=date.today(); obj.save(update_fields=["status","completed_date","updated_at"])
        return Response(SpraySerializer(obj,context={"request":request}).data)

class InputProviderViewSet(BaseScopedViewSet):
    model=InputProvider; serializer_class=InputProviderSerializer; filterset_fields=["is_active"]; search_fields=["name","phone_number"]

class PurchaseViewSet(BaseScopedViewSet):
    model=FarmInputPurchase; serializer_class=FarmInputPurchaseSerializer; filterset_fields=["farm","cycle","input_type","purchase_date","provider"]; search_fields=["product"]
    def perform_create(self,serializer):
        obj=serializer.save(owner=self.request.user); create_linked_expense(obj)
    def perform_update(self,serializer):
        obj=serializer.save(); create_linked_expense(obj)
    def destroy(self,request,*args,**kwargs):
        obj=self.get_object(); obj.is_deleted=True; obj.save(update_fields=["is_deleted","updated_at"]); return Response(status=204)

class ExpenseCategoryViewSet(BaseScopedViewSet):
    model=ExpenseCategory; serializer_class=ExpenseCategorySerializer; filterset_fields=["is_active"]; search_fields=["name"]

class ExpenseViewSet(BaseScopedViewSet):
    model = Expense
    serializer_class = ExpenseSerializer
    filterset_fields = ["farm", "cycle", "category", "date", "source_type"]
    search_fields = ["description", "notes"]

    def get_queryset(self):
        # Exclude soft-deleted records from list and detail views
        return super().get_queryset().filter(is_deleted=False)

    def perform_create(self, serializer): 
        serializer.save(owner=self.request.user)

    def perform_destroy(self, instance): 
        instance.is_deleted = True
        instance.save(update_fields=["is_deleted", "updated_at"])
        
# class ExpenseViewSet(BaseScopedViewSet):
#     model=Expense; serializer_class=ExpenseSerializer; filterset_fields=["farm","cycle","category","date","source_type"]; search_fields=["description","notes"]
#     def perform_create(self,serializer): serializer.save(owner=self.request.user)
#     def perform_destroy(self,instance): instance.is_deleted=True; instance.save(update_fields=["is_deleted","updated_at"])

class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        return Response({
            "id": str(user.id),
            "name": user.name,
            "phone": user.phone,
            "email": user.email,
            "role": user.role,
        })

    def patch(self, request):
        user = request.user

        if "name" in request.data:
            name = str(request.data["name"]).strip()

            if not name:
                return Response(
                    {"detail": "Name cannot be empty."},
                    status=400
                )

            user.name = name

        if "email" in request.data:
            user.email = str(request.data["email"]).strip()

        user.save()

        return Response({
            "message": "Profile updated successfully.",
            "id": str(user.id),
            "name": user.name,
            "phone": user.phone,
            "email": user.email,
            "role": user.role,
        })

class LoanProviderViewSet(BaseScopedViewSet):
    model=LoanProvider; serializer_class=LoanProviderSerializer; filterset_fields=["is_active"]; search_fields=["name","phone_number"]

class LoanViewSet(BaseScopedViewSet):
    model=Loan; serializer_class=LoanSerializer; filterset_fields=["provider","farm","is_archived"]; search_fields=["reference_number","purpose"]
    def perform_create(self,serializer):
        if "reference_number" not in serializer.validated_data: serializer.validated_data["reference_number"]=f"LN-{date.today().year}-{Loan.objects.count()+1:04d}"
        serializer.save(owner=self.request.user)

class LoanRepaymentViewSet(viewsets.ModelViewSet):
    serializer_class=LoanRepaymentSerializer; permission_classes=[permissions.IsAuthenticated]; filterset_fields=["loan","payment_date","payment_type"]
    def get_queryset(self): return scoped_qs(LoanRepayment,self.request.user)

class NotificationViewSet(BaseScopedViewSet):
    model=Notification; serializer_class=NotificationSerializer; http_method_names=["get","patch","head","options"]
    @action(detail=True,methods=["post"])
    def read(self,request,pk=None):
        obj=self.get_object(); obj.is_read=True; obj.save(update_fields=["is_read"]); return Response(NotificationSerializer(obj).data)

class SupervisorAssignmentViewSet(viewsets.ModelViewSet):
    queryset=SupervisorFarmAssignment.objects.all(); serializer_class=SupervisorAssignmentSerializer; permission_classes=[IsAdmin]
    filterset_fields=["supervisor","farm","is_active"]

@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def weather_api(request):
    lat=request.query_params.get("latitude"); lon=request.query_params.get("longitude")
    if not lat or not lon:
        return Response({"detail":"latitude and longitude are required."},status=400)
    try:
        lat=float(lat); lon=float(lon)
        if not (-90<=lat<=90 and -180<=lon<=180): raise ValueError
    except ValueError: return Response({"detail":"Invalid coordinates."},status=400)
    try:
        r=requests.get("https://api.open-meteo.com/v1/forecast",params={
            "latitude":lat,"longitude":lon,
            "current":"temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m",
            "hourly":"temperature_2m,precipitation_probability,weather_code,wind_speed_10m",
            "daily":"weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "forecast_days":7,"past_days":7,"timezone":"auto"},timeout=12)
        r.raise_for_status(); return Response(r.json())
    except requests.RequestException as e:
        return Response({"detail":f"Weather service unavailable: {e}"},status=503)

class UserAdminViewSet(viewsets.ModelViewSet):
    # queryset=User.objects.all(); 
    serializer_class=UserAdminSerializer; 
    permission_classes=[IsAdminOrSelf]; 
    search_fields=["name","phone","email"]; 
    filterset_fields=["role","is_active"]
    def get_queryset(self):
        user = self.request.user
        if user.is_authenticated and (user.is_staff or getattr(user, 'role', None) == 'admin'):
            return User.objects.all()
        return User.objects.filter(pk=user.pk)

class VarietyViewSet(viewsets.ModelViewSet):
    queryset=GrapeVariety.objects.all(); 
    serializer_class=GrapeVarietySerializer; 
    permission_classes=[permissions.IsAuthenticated]

class GrowthStageViewSet(viewsets.ModelViewSet):
    queryset=GrowthStageRule.objects.all(); 
    serializer_class=GrowthStageRuleSerializer; 
    permission_classes=[IsAdmin]

@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def login(request):
    s=LoginSerializer(data=request.data); s.is_valid(raise_exception=True); user=s.validated_data["user"]
    refresh=RefreshToken.for_user(user)
    return Response({"tokens":{"refresh":str(refresh),"access":str(refresh.access_token)},"user":user_dict(user)})

@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def signup(request):
    data=dict(request.data)
    if not request.user.is_authenticated: data["role"]=User.Role.FARMER
    elif request.user.role!=User.Role.ADMIN: data["role"]=User.Role.FARMER
    s=SignupSerializer(data=data); s.is_valid(raise_exception=True); user=s.save()
    refresh=RefreshToken.for_user(user)
    return Response({"tokens":{"refresh":str(refresh),"access":str(refresh.access_token)},"user":user_dict(user)},status=201)

@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def logout(request):
    try: RefreshToken(request.data["refresh"]).blacklist()
    except Exception: pass
    return Response(status=204)

@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def me(request): return Response(user_dict(request.user))

@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def dashboard_api(request):
    farm=Farm.objects.filter(id=request.query_params.get("farm_id")).first() if request.query_params.get("farm_id") else None
    cycle=CropCycle.objects.filter(id=request.query_params.get("crop_cycle_id")).first() if request.query_params.get("crop_cycle_id") else None
    if farm and request.user.role!=User.Role.ADMIN and farm.owner_id!=request.user.id and not SupervisorFarmAssignment.objects.filter(supervisor=request.user,farm=farm,is_active=True).exists(): return Response({"detail":"Forbidden."},status=403)
    return Response(dashboard(request.user,farm,cycle))

@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def reports_api(request):
    today=date.today(); period=request.query_params.get("period","30 Days")
    if request.query_params.get("start_date"): start=date.fromisoformat(request.query_params["start_date"]); end=date.fromisoformat(request.query_params.get("end_date",str(today)))
    elif period=="7 Days": start=today-timedelta(days=6); end=today
    elif period=="6 Months": start=(today.replace(day=1)-timedelta(days=1)).replace(day=1); start=(start.replace(day=1)-timedelta(days=150)); end=today
    elif period=="1 Year" or period=="Current crop year": start=today-timedelta(days=364); end=today
    else: start=today-timedelta(days=29); end=today
    farm=Farm.objects.filter(id=request.query_params.get("farm_id")).first() if request.query_params.get("farm_id") else None
    cycle=CropCycle.objects.filter(id=request.query_params.get("crop_cycle_id")).first() if request.query_params.get("crop_cycle_id") else None
    if farm and request.user.role!=User.Role.ADMIN and farm.owner_id!=request.user.id:return Response({"detail":"Forbidden."},status=403)
    data=report(request.user,start,end,farm,cycle)
    # Existing Flutter view expects summary/points/categories.
    data["summary"]={"Total expenses":data["total_expenses"],"Labour cost":data["labour_cost"],"Fertilizer cost":data["fertilizer_cost"],
                     "Spray/pesticide cost":data["spray_cost"],"Other expenses":data["other_cost"],"Loan outstanding":data["loan_outstanding"],"Total purchases":data["total_purchases"]}
    data["points"]=data.pop("monthly_trend"); data["categories"]=data.pop("category_breakdown")
    return Response(data)


def _fernet(password,salt):
    import base64
    kdf=PBKDF2HMAC(algorithm=hashes.SHA256(),length=32,salt=salt,iterations=390000)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(password.encode())))

def export_queryset(user):
    specs=[
        ("GrapeVariety",GrapeVariety.objects.all()),
        ("GrowthStageRule",GrowthStageRule.objects.all()),
        ("Farm",Farm.objects.filter(owner=user)),
        ("CropCycle",CropCycle.objects.filter(farm__owner=user)),
        ("Labourer",Labourer.objects.filter(owner=user)),
        ("TimesheetEntry",TimesheetEntry.objects.filter(owner=user)),
        ("SprayRecord",SprayRecord.objects.filter(owner=user)),
        ("InputProvider",InputProvider.objects.filter(owner=user)),
        ("FarmInputPurchase",FarmInputPurchase.objects.filter(owner=user)),
        ("ExpenseCategory",ExpenseCategory.objects.filter(owner=user)),
        ("Expense",Expense.objects.filter(owner=user)),
        ("LoanProvider",LoanProvider.objects.filter(owner=user)),
        ("Loan",Loan.objects.filter(owner=user)),
        ("LoanRepayment",LoanRepayment.objects.filter(loan__owner=user)),
        ("Notification",Notification.objects.filter(owner=user)),
    ]
    out={}
    for name,qs in specs:
        rows=[]
        for obj in qs:
            data={}
            for f in obj._meta.fields:
                v=getattr(obj,f.name)
                if f.is_relation: v=str(v.pk) if v else None
                elif hasattr(v,"isoformat"): v=v.isoformat()
                elif isinstance(v,Decimal): v=str(v)
                data[f.name]=v
            rows.append(data)
        out[name]=rows
    return out

@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def export_data(request):
    password=request.query_params.get("password") or request.headers.get("X-Backup-Password")
    if not password or len(password)<8:return Response({"detail":"Provide an 8+ character backup password."},status=400)
    payload=json.dumps(export_queryset(request.user),default=str).encode()
    salt=hashlib.sha256((str(request.user.id)+password).encode()).digest()[:16]
    token=_fernet(password,salt).encrypt(payload)
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("metadata.json",json.dumps({"version":1,"created_at":timezone.now().isoformat(),"application":"Drakshi Mitra"}))
        z.writestr("payload.bin",token); z.writestr("salt.bin",salt)
    resp=HttpResponse(buf.getvalue(),content_type="application/zip")
    resp["Content-Disposition"]=f'attachment; filename="DrakshiMitra_Backup_{date.today()}.zip"'
    return resp

@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def restore_data(request):
    upload=request.FILES.get("file"); password=request.data.get("password","")
    if not upload or len(password)<8:return Response({"detail":"Backup file and 8+ character password are required."},status=400)
    try:
        with zipfile.ZipFile(upload) as z:
            token=z.read("payload.bin"); salt=z.read("salt.bin")
        payload=json.loads(_fernet(password,salt).decrypt(token))
    except Exception:return Response({"detail":"Invalid backup or password."},status=400)
    user=request.user; counts={}
    def bump(k): counts[k]=counts.get(k,0)+1
    def pk(v): return v
    with transaction.atomic():
        for row in payload.get("GrapeVariety",[]):
            row=dict(row); obj_id=row.pop("id"); GrapeVariety.objects.update_or_create(id=obj_id,defaults=row)
        for row in payload.get("GrowthStageRule",[]):
            row=dict(row); obj_id=row.pop("id"); GrowthStageRule.objects.update_or_create(id=obj_id,defaults=row)
        for row in payload.get("Farm",[]):
            row=dict(row); row.pop("owner",None); obj_id=row.pop("id"); variety_id=row.pop("variety",None)
            variety=GrapeVariety.objects.filter(id=variety_id).first() if variety_id else None
            defaults={k:v for k,v in row.items() if k not in ["created_at","updated_at"]}
            defaults["owner"]=user; defaults["variety"]=variety
            Farm.objects.update_or_create(id=obj_id,defaults=defaults); bump("farms")
        for row in payload.get("CropCycle",[]):
            row=dict(row); row.pop("owner",None); obj_id=row.pop("id"); farm=Farm.objects.filter(id=row.pop("farm"),owner=user).first()
            if not farm: continue
            defaults={k:v for k,v in row.items() if k!="created_at"}; defaults["farm"]=farm
            CropCycle.objects.update_or_create(id=obj_id,defaults=defaults); bump("cycles")
        for row in payload.get("Labourer",[]):
            row=dict(row); row.pop("owner",None); obj_id=row.pop("id"); row.pop("created_at",None)
            row["owner"]=user; Labourer.objects.update_or_create(id=obj_id,defaults=row); bump("labourers")
        for row in payload.get("InputProvider",[]):
            row=dict(row); row.pop("owner",None); obj_id=row.pop("id"); row.pop("created_at",None); row["owner"]=user
            InputProvider.objects.update_or_create(id=obj_id,defaults=row); bump("input_providers")
        for row in payload.get("ExpenseCategory",[]):
            row=dict(row); row.pop("owner",None); obj_id=row.pop("id"); row["owner"]=user
            ExpenseCategory.objects.update_or_create(id=obj_id,defaults=row); bump("expense_categories")
        for row in payload.get("LoanProvider",[]):
            row=dict(row); row.pop("owner",None); obj_id=row.pop("id"); row.pop("created_at",None); row["owner"]=user
            LoanProvider.objects.update_or_create(id=obj_id,defaults=row); bump("loan_providers")
        for row in payload.get("TimesheetEntry",[]):
            row=dict(row); row.pop("owner",None); obj_id=row.pop("id")
            farm=Farm.objects.filter(id=row.pop("farm"),owner=user).first(); cycle=CropCycle.objects.filter(id=row.pop("cycle"),farm=farm).first() if farm else None; labour=Labourer.objects.filter(id=row.pop("labour"),owner=user).first()
            if not (farm and cycle and labour): continue
            row.pop("created_at",None); row.pop("updated_at",None); row.update(owner=user,farm=farm,cycle=cycle,labour=labour)
            TimesheetEntry.objects.update_or_create(id=obj_id,defaults=row); bump("timesheets")
        for row in payload.get("SprayRecord",[]):
            row=dict(row); row.pop("owner",None); obj_id=row.pop("id")
            farm=Farm.objects.filter(id=row.pop("farm"),owner=user).first(); cycle=CropCycle.objects.filter(id=row.pop("cycle"),farm=farm).first() if farm else None
            if not (farm and cycle): continue
            row.pop("supervisor",None); row.pop("created_at",None); row.pop("updated_at",None); row.update(owner=user,farm=farm,cycle=cycle)
            SprayRecord.objects.update_or_create(id=obj_id,defaults=row); bump("sprays")
        for row in payload.get("FarmInputPurchase",[]):
            row=dict(row); row.pop("owner",None); obj_id=row.pop("id")
            farm=Farm.objects.filter(id=row.pop("farm"),owner=user).first(); cycle=CropCycle.objects.filter(id=row.pop("cycle"),farm=farm).first() if farm else None
            provider=InputProvider.objects.filter(id=row.pop("provider"),owner=user).first() if row.get("provider") else None
            if not (farm and cycle): continue
            row.pop("created_at",None); row.pop("updated_at",None); row.update(owner=user,farm=farm,cycle=cycle,provider=provider)
            FarmInputPurchase.objects.update_or_create(id=obj_id,defaults=row); bump("purchases")
        for row in payload.get("Loan",[]):
            row=dict(row); row.pop("owner",None); obj_id=row.pop("id")
            provider=LoanProvider.objects.filter(id=row.pop("provider"),owner=user).first(); farm=Farm.objects.filter(id=row.pop("farm"),owner=user).first() if row.get("farm") else None
            if not provider: continue
            row.pop("created_at",None); row.pop("updated_at",None); row.update(owner=user,provider=provider,farm=farm)
            Loan.objects.update_or_create(id=obj_id,defaults=row); bump("loans")
        for row in payload.get("LoanRepayment",[]):
            row=dict(row); obj_id=row.pop("id"); loan=Loan.objects.filter(id=row.pop("loan"),owner=user).first()
            if not loan: continue
            row.pop("created_at",None); row["loan"]=loan
            LoanRepayment.objects.update_or_create(id=obj_id,defaults=row); bump("repayments")
        for row in payload.get("Expense",[]):
            row=dict(row); row.pop("owner",None); obj_id=row.pop("id")
            farm_id=row.get("farm"); cycle_id=row.get("cycle"); category_id=row.get("category"); purchase_id=row.get("source_purchase")
            farm=Farm.objects.filter(id=farm_id,owner=user).first() if farm_id else None
            cycle=CropCycle.objects.filter(id=cycle_id,farm=farm).first() if cycle_id and farm else None
            category=ExpenseCategory.objects.filter(id=category_id,owner=user).first() if category_id else None
            purchase=FarmInputPurchase.objects.filter(id=purchase_id,owner=user).first() if purchase_id else None
            row.pop("farm",None); row.pop("cycle",None); row.pop("category",None); row.pop("source_purchase",None)
            if not category: continue
            row.pop("created_at",None); row.pop("updated_at",None); row.update(owner=user,farm=farm,cycle=cycle,category=category,source_purchase=purchase)
            Expense.objects.update_or_create(id=obj_id,defaults=row); bump("expenses")
        for row in payload.get("Notification",[]):
            row=dict(row); row.pop("owner",None); obj_id=row.pop("id"); row.pop("created_at",None); row["owner"]=user
            Notification.objects.update_or_create(id=obj_id,defaults=row); bump("notifications")
    return Response({"detail":"Backup restored successfully.","restored":counts})
