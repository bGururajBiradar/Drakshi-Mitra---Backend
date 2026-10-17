from django.contrib.auth import authenticate
from django.db import transaction
from rest_framework import serializers
from .models import *

def user_dict(u):
    return {"id":str(u.id),"name":u.name,"phone":u.phone,"email":u.email,"role":u.role.title() if u.role else "Farmer"}

class UserSerializer(serializers.ModelSerializer):
    role=serializers.CharField(source="get_role_display",read_only=True)
    class Meta:
        model=User; fields=["id","name","phone","email","role","is_active","created_at"]

class SignupSerializer(serializers.Serializer):
    name=serializers.CharField(max_length=150)
    phone=serializers.CharField(max_length=20)
    email=serializers.EmailField(required=False,allow_blank=True)
    role=serializers.ChoiceField(choices=User.Role.choices,default=User.Role.FARMER)
    passcode=serializers.RegexField(r"^.{8}$",write_only=True)
    def validate_phone(self,v):
        v=v.strip()
        if User.objects.filter(phone=v).exists(): raise serializers.ValidationError("PHONE_ALREADY_REGISTERED")
        return v
    def create(self,validated):
        role=validated.pop("role",User.Role.FARMER)
        validated["role"]=role
        password=validated.pop("passcode")
        return User.objects.create_user(password=password,**validated)

class LoginSerializer(serializers.Serializer):
    phone=serializers.CharField(); passcode=serializers.CharField(write_only=True)
    def validate(self,attrs):
        user=authenticate(phone=attrs["phone"].strip(),password=attrs["passcode"])
        if not user or not user.is_active: raise serializers.ValidationError("Incorrect phone number or passcode.")
        attrs["user"]=user; return attrs

class GrapeVarietySerializer(serializers.ModelSerializer):
    class Meta: model=GrapeVariety; fields="__all__"

class GrowthStageRuleSerializer(serializers.ModelSerializer):
    class Meta: model=GrowthStageRule; fields="__all__"

class FarmSerializer(serializers.ModelSerializer):
    owner=serializers.PrimaryKeyRelatedField(read_only=True)
    variety_name=serializers.CharField(source="variety.name",read_only=True)
    class Meta:
        model=Farm
        fields=["id","owner","name","location","area_acres","area_gunta","crop","variety","variety_name","plants_count","blocks_count","planting_date","expected_harvest","is_active","created_at","updated_at"]
    def validate(self,data):
        if data.get("area_gunta",0) > 40: raise serializers.ValidationError({"area_gunta":"Gunta must be between 0 and 40."})
        return data

class CropCycleSerializer(serializers.ModelSerializer):
    farm_name=serializers.CharField(source="farm.name",read_only=True)
    class Meta:
        model=CropCycle; fields=["id","farm","farm_name","name","start_date","end_date","planting_date","expected_harvest","is_active","created_at"]
    def validate(self,data):
        start=data.get("start_date",getattr(self.instance,"start_date",None)); end=data.get("end_date",getattr(self.instance,"end_date",None))
        if start and end and end<=start: raise serializers.ValidationError({"end_date":"End date must be after start date."})
        farm=data.get("farm",getattr(self.instance,"farm",None))
        if farm and self.context["request"].user.role==User.Role.FARMER and farm.owner_id!=self.context["request"].user.id:
            raise serializers.ValidationError({"farm":"You do not own this farm."})
        return data

class LabourerSerializer(serializers.ModelSerializer):
    pending_amount=serializers.SerializerMethodField()
    class Meta:
        model=Labourer; fields=["id","owner","name","phone","status","default_daily_wage","notes","pending_amount","created_at"]; read_only_fields=["owner","pending_amount"]
    def get_pending_amount(self,obj):
        from django.db.models import F, Sum
        return obj.timesheets.aggregate(v=Sum(F("daily_wage")-F("paid_amount")))["v"] or 0

class TimesheetSerializer(serializers.ModelSerializer):
    labour_name=serializers.CharField(source="labour.name",read_only=True)
    farm_name=serializers.CharField(source="farm.name",read_only=True)
    pending_amount=serializers.ReadOnlyField()
    class Meta:
        model=TimesheetEntry; fields="__all__"; read_only_fields=["owner"]
    def validate(self,data):
        request=self.context["request"]; farm=data.get("farm",getattr(self.instance,"farm",None)); cycle=data.get("cycle",getattr(self.instance,"cycle",None)); labour=data.get("labour",getattr(self.instance,"labour",None))
        if request.user.role==User.Role.FARMER and farm and farm.owner_id!=request.user.id: raise serializers.ValidationError({"farm":"Invalid farm."})
        if cycle and farm and cycle.farm_id!=farm.id: raise serializers.ValidationError({"cycle":"Cycle does not belong to selected farm."})
        if labour and request.user.role==User.Role.FARMER and labour.owner_id!=request.user.id: raise serializers.ValidationError({"labour":"Invalid labourer."})
        if data.get("paid_amount",getattr(self.instance,"paid_amount",0)) > data.get("daily_wage",getattr(self.instance,"daily_wage",0)): raise serializers.ValidationError({"paid_amount":"Paid amount cannot exceed wage."})
        return data

class SpraySerializer(serializers.ModelSerializer):
    farm_name=serializers.CharField(source="farm.name",read_only=True); cycle_name=serializers.CharField(source="cycle.name",read_only=True)
    supervisor_name=serializers.CharField(source="supervisor.name",read_only=True)
    class Meta:
        model=SprayRecord; fields="__all__"; read_only_fields=["owner","supervisor","completed_date"]
    def validate(self,data):
        request=self.context["request"]; farm=data.get("farm",getattr(self.instance,"farm",None)); cycle=data.get("cycle",getattr(self.instance,"cycle",None))
        if cycle and farm and cycle.farm_id!=farm.id: raise serializers.ValidationError({"cycle":"Cycle does not belong to selected farm."})
        if request.user.role==User.Role.FARMER and farm and farm.owner_id!=request.user.id: raise serializers.ValidationError({"farm":"Invalid farm."})
        if data.get("status")==SprayRecord.Status.COMPLETED and not getattr(self.instance,"completed_date",None): data["completed_date"]=__import__("datetime").date.today()
        return data

class InputProviderSerializer(serializers.ModelSerializer):
    class Meta:
        model=InputProvider; fields="__all__"; read_only_fields=["owner"]

class FarmInputPurchaseSerializer(serializers.ModelSerializer):
    total_amount=serializers.ReadOnlyField(); product_name=serializers.CharField(source="product",read_only=True)
    class Meta:
        model=FarmInputPurchase; fields="__all__"; read_only_fields=["owner","total_amount"]
    def validate(self,data):
        request=self.context["request"]; farm=data.get("farm",getattr(self.instance,"farm",None)); cycle=data.get("cycle",getattr(self.instance,"cycle",None)); provider=data.get("provider",getattr(self.instance,"provider",None))
        if farm and request.user.role==User.Role.FARMER and farm.owner_id!=request.user.id: raise serializers.ValidationError({"farm":"Invalid farm."})
        if cycle and farm and cycle.farm_id!=farm.id: raise serializers.ValidationError({"cycle":"Cycle does not belong to farm."})
        if provider and request.user.role==User.Role.FARMER and provider.owner_id!=request.user.id: raise serializers.ValidationError({"provider":"Invalid provider."})
        return data

class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model=ExpenseCategory; fields="__all__"; read_only_fields=["owner"]

class ExpenseSerializer(serializers.ModelSerializer):
    category_name=serializers.CharField(source="category.name",read_only=True)
    class Meta:
        model=Expense; fields="__all__"; read_only_fields=["owner"]
    def validate(self,data):
        request=self.context["request"]; category=data.get("category",getattr(self.instance,"category",None)); farm=data.get("farm",getattr(self.instance,"farm",None)); cycle=data.get("cycle",getattr(self.instance,"cycle",None))
        if category and request.user.role==User.Role.FARMER and category.owner_id!=request.user.id: raise serializers.ValidationError({"category":"Invalid category."})
        if farm and request.user.role==User.Role.FARMER and farm.owner_id!=request.user.id: raise serializers.ValidationError({"farm":"Invalid farm."})
        if cycle and farm and cycle.farm_id!=farm.id: raise serializers.ValidationError({"cycle":"Cycle does not belong to farm."})
        if data.get("source_type")==Expense.Source.LINKED and not data.get("source_purchase"): raise serializers.ValidationError({"source_purchase":"Linked expenses require a source purchase."})
        return data

class LoanProviderSerializer(serializers.ModelSerializer):
    class Meta:
        model=LoanProvider; fields="__all__"; read_only_fields=["owner"]

class LoanSerializer(serializers.ModelSerializer):
    provider_name=serializers.CharField(source="provider.name",read_only=True)
    calculation=serializers.SerializerMethodField()
    class Meta:
        model=Loan; fields="__all__"; read_only_fields=["owner","calculation"]
    def get_calculation(self,obj):
        from .services import calculate_loan
        return calculate_loan(obj)

class LoanRepaymentSerializer(serializers.ModelSerializer):
    class Meta: model=LoanRepayment; fields="__all__"
    def validate(self,data):
        loan=data.get("loan",getattr(self.instance,"loan",None))
        if self.context["request"].user.role!=User.Role.ADMIN and loan and loan.owner_id!=self.context["request"].user.id:
            raise serializers.ValidationError({"loan":"Invalid loan."})
        if loan and data.get("amount") is not None:
            from .services import calculate_loan
            as_of=data.get("payment_date") or getattr(self.instance,"payment_date",None)
            outstanding=Decimal(str(calculate_loan(loan,as_of)["totalOutstanding"])) if as_of else Decimal(str(calculate_loan(loan)["totalOutstanding"]))
            if Decimal(str(data["amount"])) > outstanding + Decimal("0.01"):
                raise serializers.ValidationError({"amount":f"Payment exceeds outstanding amount ({outstanding:.2f})."})
        return data

class NotificationSerializer(serializers.ModelSerializer):
    class Meta: model=Notification; fields="__all__"; read_only_fields=["owner"]


class UserAdminSerializer(serializers.ModelSerializer):
    passcode = serializers.RegexField(r"^.{8}$", write_only=True, required=False)
    class Meta:
        model = User
        fields = ["id", "name", "phone", "email", "role", "is_active", "passcode"]
    def create(self, validated_data):
        password = validated_data.pop("passcode", "12345678")
        return User.objects.create_user(password=password, **validated_data)
    def update(self, instance, validated_data):
        password = validated_data.pop("passcode", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance

class SupervisorAssignmentSerializer(serializers.ModelSerializer):
    supervisor_name=serializers.CharField(source="supervisor.name",read_only=True)
    farm_name=serializers.CharField(source="farm.name",read_only=True)
    class Meta:
        model=SupervisorFarmAssignment
        fields="__all__"
