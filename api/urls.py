from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from .views import *

router=DefaultRouter()
router.register("farms",FarmViewSet,basename="farm")
router.register("crop-cycles",CropCycleViewSet,basename="crop-cycle")
router.register("labour",LabourViewSet,basename="labour")
router.register("timesheet",TimesheetViewSet,basename="timesheet")
router.register("sprays",SprayViewSet,basename="spray")
router.register("input-providers",InputProviderViewSet,basename="input-provider")
router.register("fertilizers",PurchaseViewSet,basename="fertilizer")
router.register("purchases",PurchaseViewSet,basename="purchase")
router.register("expense-categories",ExpenseCategoryViewSet,basename="expense-category")
router.register("expenses",ExpenseViewSet,basename="expense")
router.register("loan-providers",LoanProviderViewSet,basename="loan-provider")
router.register("loans",LoanViewSet,basename="loan")
router.register("loan-repayments",LoanRepaymentViewSet,basename="loan-repayment")
router.register("notifications",NotificationViewSet,basename="notification")
router.register("users",UserAdminViewSet,basename="user")
router.register("supervisor-assignments",SupervisorAssignmentViewSet,basename="supervisor-assignment")
router.register("varieties",VarietyViewSet,basename="variety")
router.register("growth-stages",GrowthStageViewSet,basename="growth-stage")
urlpatterns=[
 path("",include(router.urls)),
 path("auth/login/",login),
 path("auth/signup/",signup),
 path("auth/logout/",logout),
 path("auth/me/",me),
 path("auth/refresh/",TokenRefreshView.as_view()),
 path("profile/", ProfileView.as_view(), name="profile"),
 path("dashboard/",dashboard_api),path("reports/",reports_api),path("weather/",weather_api),path("export/",export_data),path("backup/export/",export_data),path("backup/restore/",restore_data),
]
