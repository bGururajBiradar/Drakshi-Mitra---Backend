from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import *
@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model=User; ordering=("phone",); list_display=("phone","name","role","is_active","is_staff")
    fieldsets=((None,{"fields":("phone","password")}),("Profile",{"fields":("name","email","role")}),("Permissions",{"fields":("is_active","is_staff","is_superuser","groups","user_permissions")}))
    add_fieldsets=((None,{"classes":("wide",),"fields":("phone","name","password1","password2","role")}),)
    search_fields=("phone","name")
for m in [GrapeVariety,GrowthStageRule,Farm,CropCycle,SupervisorFarmAssignment,Labourer,TimesheetEntry,SprayRecord,InputProvider,FarmInputPurchase,ExpenseCategory,Expense,LoanProvider,Loan,LoanRepayment,GrowthStageOverride,SystemSetting,WeatherCache,Notification,AuditLog]:
    admin.site.register(m)
