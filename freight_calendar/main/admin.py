from django.contrib import admin
from .models import Order, Vehicle, DeliveryPlan, PlanItem, CustomUser
from django.contrib.auth.admin import UserAdmin

class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ['username', 'email', 'role', 'is_active', 'is_staff']
    list_filter = ['role', 'is_active', 'is_staff']
    search_fields = ['username', 'email']
    fieldsets = UserAdmin.fieldsets + (
        ('Дополнительно', {'fields': ('role',)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Дополнительно', {'fields': ('role',)}),
    )

@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ('name', 'capacity_volume', 'capacity_weight')
    search_fields = ('name',)

@admin.register(DeliveryPlan)
class DeliveryPlanAdmin(admin.ModelAdmin):
    list_display = ('date', 'vehicle', 'status')
    list_filter = ('status', 'date')
    search_fields = ('vehicle__name',)

@admin.register(PlanItem)
class PlanItemAdmin(admin.ModelAdmin):
    list_display = ('plan', 'order')
    list_filter = ('plan__date',)
    search_fields = ('order__address',)

admin.site.register(CustomUser, CustomUserAdmin)

# Настройка заголовков самой панели
admin.site.site_header = "Панель управления Freight Calendar"
admin.site.site_title = "Freight Calendar Admin"
admin.site.index_title = "Добро пожаловать в систему"