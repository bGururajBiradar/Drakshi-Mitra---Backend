from rest_framework.permissions import BasePermission
from .models import User
class IsAdmin(BasePermission):
    def has_permission(self,request,view): return bool(request.user and request.user.is_authenticated and request.user.role==User.Role.ADMIN)
class IsFarmerOrAdmin(BasePermission):
    def has_permission(self,request,view): return request.user.is_authenticated and request.user.role in [User.Role.FARMER,User.Role.ADMIN]
class IsSupervisorOrAdmin(BasePermission):
    def has_permission(self,request,view): return request.user.is_authenticated and request.user.role in [User.Role.SUPERVISOR,User.Role.ADMIN]

class IsAdminOrSelf(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated
    def has_object_permission(self, request, view, obj):
        if request.user.is_staff or getattr(request.user, 'role', None) == 'admin':
            return True
        return obj == request.user
