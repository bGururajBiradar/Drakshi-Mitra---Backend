import uuid
from decimal import Decimal
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator
from django.db import models

class UserManager(BaseUserManager):
    def create_user(self, phone, password=None, **extra):
        if not phone: raise ValueError("Phone number is required.")
        user=self.model(phone=phone.strip(), **extra); user.set_password(password or ""); user.save(using=self._db); return user
    def create_superuser(self, phone, password=None, **extra):
        extra.update(is_staff=True,is_superuser=True,role=User.Role.ADMIN,is_active=True); return self.create_user(phone,password,**extra)

class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        FARMER="FARMER","Farmer"
        SUPERVISOR="SUPERVISOR","Supervisor"
        ADMIN="ADMIN","Admin"
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    phone=models.CharField(max_length=20,unique=True,validators=[RegexValidator(r"^\+?[0-9]{10,15}$")])
    name=models.CharField(max_length=150); email=models.EmailField(blank=True)
    role=models.CharField(max_length=20,choices=Role.choices,default=Role.FARMER)
    is_active=models.BooleanField(default=True); is_staff=models.BooleanField(default=False)
    created_at=models.DateTimeField(auto_now_add=True); updated_at=models.DateTimeField(auto_now=True)
    USERNAME_FIELD="phone"; REQUIRED_FIELDS=["name"]; objects=UserManager()
    def __str__(self): return f"{self.name} ({self.phone})"

class GrapeVariety(models.Model):
    name=models.CharField(max_length=100,unique=True); is_active=models.BooleanField(default=True)
    def __str__(self): return self.name

class GrowthStageRule(models.Model):
    name=models.CharField(max_length=100,unique=True); order=models.PositiveIntegerField(unique=True)
    start_day=models.PositiveIntegerField(); end_day=models.PositiveIntegerField(); is_active=models.BooleanField(default=True)
    class Meta: ordering=["order"]
    def __str__(self): return self.name

class Farm(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    owner=models.ForeignKey(User,on_delete=models.CASCADE,related_name="farms")
    name=models.CharField(max_length=150); location=models.CharField(max_length=255)
    area_acres=models.IntegerField(validators=[MinValueValidator(0)])
    area_gunta=models.IntegerField(validators=[MinValueValidator(0),MaxValueValidator(40)])
    crop=models.CharField(max_length=80,default="Grape"); variety=models.ForeignKey(GrapeVariety,null=True,blank=True,on_delete=models.SET_NULL,related_name="farms")
    plants_count=models.PositiveIntegerField(default=0); blocks_count=models.PositiveIntegerField(default=1)
    planting_date=models.DateField(null=True,blank=True); expected_harvest=models.DateField(null=True,blank=True)
    is_active=models.BooleanField(default=True); created_at=models.DateTimeField(auto_now_add=True); updated_at=models.DateTimeField(auto_now=True)
    class Meta: ordering=["name"]
    def __str__(self): return self.name

class CropCycle(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    farm=models.ForeignKey(Farm,on_delete=models.CASCADE,related_name="cycles")
    name=models.CharField(max_length=30,blank=True); start_date=models.DateField(); end_date=models.DateField()
    planting_date=models.DateField(null=True,blank=True); expected_harvest=models.DateField(null=True,blank=True); is_active=models.BooleanField(default=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta: ordering=["-start_date"]; constraints=[models.UniqueConstraint(fields=["farm","start_date","end_date"],name="unique_farm_cycle")]
    def save(self,*args,**kwargs):
        if not self.name: self.name=f"{self.start_date.year}–{self.end_date.year}"
        super().save(*args,**kwargs)

class SupervisorFarmAssignment(models.Model):
    supervisor=models.ForeignKey(User,on_delete=models.CASCADE,related_name="supervisor_assignments")
    farm=models.ForeignKey(Farm,on_delete=models.CASCADE,related_name="supervisor_assignments")
    assigned_at=models.DateTimeField(auto_now_add=True); is_active=models.BooleanField(default=True)
    class Meta: constraints=[models.UniqueConstraint(fields=["supervisor","farm"],name="unique_supervisor_farm")]

class Labourer(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    owner=models.ForeignKey(User,on_delete=models.CASCADE,related_name="labourers")
    name=models.CharField(max_length=150); phone=models.CharField(max_length=20,blank=True)
    status=models.CharField(max_length=20,default="ACTIVE",choices=[("ACTIVE","Active"),("INACTIVE","Inactive")])
    default_daily_wage=models.DecimalField(max_digits=12,decimal_places=2,default=0,validators=[MinValueValidator(Decimal("0"))])
    notes=models.TextField(blank=True); created_at=models.DateTimeField(auto_now_add=True)
    class Meta: ordering=["name"]

class TimesheetEntry(models.Model):
    class Attendance(models.TextChoices):
        FULL="FULL_DAY","Full Day"
        HALF="HALF_DAY","Half Day"
        HOURLY="HOURLY","Custom/Hourly"
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    owner=models.ForeignKey(User,on_delete=models.CASCADE,related_name="timesheets"); farm=models.ForeignKey(Farm,on_delete=models.CASCADE,related_name="timesheets")
    cycle=models.ForeignKey(CropCycle,on_delete=models.CASCADE,related_name="timesheets"); labour=models.ForeignKey(Labourer,on_delete=models.PROTECT,related_name="timesheets")
    date=models.DateField(); attendance_type=models.CharField(max_length=20,choices=Attendance.choices,default=Attendance.FULL)
    hours=models.DecimalField(max_digits=6,decimal_places=2,default=8,validators=[MinValueValidator(Decimal("0")),MaxValueValidator(Decimal("24"))])
    daily_wage=models.DecimalField(max_digits=12,decimal_places=2,validators=[MinValueValidator(Decimal("0"))])
    paid_amount=models.DecimalField(max_digits=12,decimal_places=2,default=0,validators=[MinValueValidator(Decimal("0"))])
    payment_date=models.DateField(null=True,blank=True); notes=models.TextField(blank=True)
    created_at=models.DateTimeField(auto_now_add=True); updated_at=models.DateTimeField(auto_now=True)
    class Meta: ordering=["-date"]; constraints=[models.UniqueConstraint(fields=["labour","farm","cycle","date"],name="unique_labour_farm_cycle_date")]
    @property
    def pending_amount(self): return max(Decimal("0"),self.daily_wage-self.paid_amount)

class SprayRecord(models.Model):
    class Status(models.TextChoices):
        SCHEDULED="SCHEDULED","Scheduled"
        COMPLETED="COMPLETED","Completed"
        SKIPPED="SKIPPED","Skipped"
        CANCELLED="CANCELLED","Cancelled"
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    owner=models.ForeignKey(User,on_delete=models.CASCADE,related_name="sprays"); farm=models.ForeignKey(Farm,on_delete=models.CASCADE,related_name="sprays")
    cycle=models.ForeignKey(CropCycle,on_delete=models.CASCADE,related_name="sprays"); supervisor=models.ForeignKey(User,null=True,blank=True,on_delete=models.SET_NULL,related_name="created_sprays")
    spray_date=models.DateField(); scheduled_time=models.TimeField(null=True,blank=True); product=models.CharField(max_length=150); type=models.CharField(max_length=80,blank=True)
    purpose=models.CharField(max_length=255,blank=True); area_acres=models.DecimalField(max_digits=10,decimal_places=4,default=0); block=models.CharField(max_length=100,blank=True)
    instructions=models.TextField(blank=True); status=models.CharField(max_length=20,choices=Status.choices,default=Status.SCHEDULED); completed_date=models.DateField(null=True,blank=True); notes=models.TextField(blank=True)
    created_at=models.DateTimeField(auto_now_add=True); updated_at=models.DateTimeField(auto_now=True)
    class Meta: ordering=["spray_date","scheduled_time"]

class InputProvider(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    owner=models.ForeignKey(User,on_delete=models.CASCADE,related_name="input_providers")
    name=models.CharField(max_length=150); phone_number=models.CharField(max_length=20,blank=True); address=models.TextField(blank=True); notes=models.TextField(blank=True)
    is_active=models.BooleanField(default=True); created_at=models.DateTimeField(auto_now_add=True)
    class Meta: ordering=["name"]

class FarmInputPurchase(models.Model):
    class InputType(models.TextChoices):
        FERTILIZER="FERTILIZER","Fertilizer"
        FUNGICIDE="FUNGICIDE","Fungicide"
        PESTICIDE="PESTICIDE","Pesticide"
        OTHER="OTHER","Other"
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    owner=models.ForeignKey(User,on_delete=models.CASCADE,related_name="purchases")
    farm=models.ForeignKey(Farm,on_delete=models.CASCADE,related_name="purchases")
    cycle=models.ForeignKey(CropCycle,on_delete=models.CASCADE,related_name="purchases")
    provider=models.ForeignKey(InputProvider,null=True,blank=True,on_delete=models.SET_NULL,related_name="purchases")
    product=models.CharField(max_length=180)
    input_type=models.CharField(max_length=20,choices=InputType.choices)
    quantity=models.IntegerField(validators=[MinValueValidator(0)])
    unit=models.CharField(max_length=30)
    price=models.IntegerField(validators=[MinValueValidator(0)])
    purchase_date=models.DateField(); notes=models.TextField(blank=True)
    is_deleted=models.BooleanField(default=False)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    @property
    def total_amount(self): return self.quantity*self.price

class ExpenseCategory(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    owner=models.ForeignKey(User,on_delete=models.CASCADE,related_name="expense_categories"); name=models.CharField(max_length=100); is_active=models.BooleanField(default=True)
    class Meta: constraints=[models.UniqueConstraint(fields=["owner","name"],name="unique_owner_expense_category")]

class Expense(models.Model):
    class Source(models.TextChoices):
        DIRECT="DIRECT","Direct"
        LINKED="LINKED","Linked"
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False); owner=models.ForeignKey(User,on_delete=models.CASCADE,related_name="expenses")
    farm=models.ForeignKey(Farm,null=True,blank=True,on_delete=models.CASCADE,related_name="expenses"); cycle=models.ForeignKey(CropCycle,null=True,blank=True,on_delete=models.CASCADE,related_name="expenses")
    category=models.ForeignKey(ExpenseCategory,on_delete=models.PROTECT,related_name="expenses"); description=models.CharField(max_length=255)
    amount=models.DecimalField(max_digits=14,decimal_places=2,validators=[MinValueValidator(Decimal("0"))]); date=models.DateField()
    source_type=models.CharField(max_length=10,choices=Source.choices,default=Source.DIRECT); source_purchase=models.OneToOneField(FarmInputPurchase,null=True,blank=True,on_delete=models.SET_NULL,related_name="linked_expense")
    notes=models.TextField(blank=True); is_deleted=models.BooleanField(default=False); created_at=models.DateTimeField(auto_now_add=True); updated_at=models.DateTimeField(auto_now=True)

class LoanProvider(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False); owner=models.ForeignKey(User,on_delete=models.CASCADE,related_name="loan_providers")
    name=models.CharField(max_length=150); phone_number=models.CharField(max_length=20,blank=True); type=models.CharField(max_length=80,default="Individual")
    address=models.TextField(blank=True); notes=models.TextField(blank=True); is_active=models.BooleanField(default=True); created_at=models.DateTimeField(auto_now_add=True)

class Loan(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False); 
    owner=models.ForeignKey(User,on_delete=models.CASCADE,related_name="loans")
    provider=models.ForeignKey(LoanProvider,on_delete=models.PROTECT,related_name="loans"); 
    farm=models.ForeignKey(Farm,null=True,blank=True,on_delete=models.SET_NULL,related_name="loans")
    reference_number=models.CharField(max_length=50,blank=True, null=True); 
    principal_amount=models.DecimalField(max_digits=16,decimal_places=2,validators=[MinValueValidator(Decimal("0.01"))])
    annual_interest_rate=models.DecimalField(max_digits=7,decimal_places=3,validators=[MinValueValidator(Decimal("0")),MaxValueValidator(Decimal("1000"))])
    start_date=models.DateField(); purpose=models.CharField(max_length=150,default="Farm"); notes=models.TextField(blank=True); is_archived=models.BooleanField(default=False)
    created_at=models.DateTimeField(auto_now_add=True); updated_at=models.DateTimeField(auto_now=True)

class LoanRepayment(models.Model):
    class PaymentType(models.TextChoices):
        INTEREST_ONLY="INTEREST_ONLY","Interest Only"; PRINCIPAL_ONLY="PRINCIPAL_ONLY","Principal Only"; INTEREST_AND_PRINCIPAL="INTEREST_AND_PRINCIPAL","Interest + Principal"; FULL_SETTLEMENT="FULL_SETTLEMENT","Full Settlement"
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False); loan=models.ForeignKey(Loan,on_delete=models.CASCADE,related_name="repayments")
    payment_date=models.DateField(); amount=models.DecimalField(max_digits=16,decimal_places=2,validators=[MinValueValidator(Decimal("0.01"))]); payment_type=models.CharField(max_length=30,choices=PaymentType.choices,default=PaymentType.INTEREST_AND_PRINCIPAL)
    payment_mode=models.CharField(max_length=40,blank=True); reference_number=models.CharField(max_length=80,blank=True); notes=models.TextField(blank=True); created_at=models.DateTimeField(auto_now_add=True)
    class Meta: ordering=["payment_date","created_at"]

class GrowthStageOverride(models.Model):
    cycle=models.ForeignKey(CropCycle,on_delete=models.CASCADE,related_name="stage_overrides"); stage=models.ForeignKey(GrowthStageRule,on_delete=models.CASCADE,related_name="overrides")
    start_day=models.PositiveIntegerField(); end_day=models.PositiveIntegerField()
    class Meta: constraints=[models.UniqueConstraint(fields=["cycle","stage"],name="unique_cycle_stage_override")]

class SystemSetting(models.Model):
    key=models.CharField(max_length=100,unique=True); value=models.JSONField(default=dict); updated_at=models.DateTimeField(auto_now=True)

class WeatherCache(models.Model):
    key=models.CharField(max_length=255,unique=True); latitude=models.DecimalField(max_digits=9,decimal_places=5); longitude=models.DecimalField(max_digits=9,decimal_places=5)
    location_name=models.CharField(max_length=255,blank=True); payload=models.JSONField(default=dict); fetched_at=models.DateTimeField(auto_now=True)

class Notification(models.Model):
    class Kind(models.TextChoices):
        SPRAY="SPRAY","Spray"
        WEATHER="WEATHER","Weather"
        LABOUR="LABOUR","Labour"
        LOAN="LOAN","Loan"
        CROP="CROP","Crop"
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False); owner=models.ForeignKey(User,on_delete=models.CASCADE,related_name="notifications")
    kind=models.CharField(max_length=20,choices=Kind.choices); title=models.CharField(max_length=200); message=models.TextField(); is_read=models.BooleanField(default=False); created_at=models.DateTimeField(auto_now_add=True)

class AuditLog(models.Model):
    actor=models.ForeignKey(User,null=True,blank=True,on_delete=models.SET_NULL,related_name="audit_logs"); action=models.CharField(max_length=50); model_name=models.CharField(max_length=100)
    object_id=models.CharField(max_length=100,blank=True); metadata=models.JSONField(default=dict); created_at=models.DateTimeField(auto_now_add=True)
