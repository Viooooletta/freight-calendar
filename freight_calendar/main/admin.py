from django.contrib import admin
from .models import Order, Vehicle, DeliveryPlan, PlanItem, CustomUser
from django.contrib.auth.admin import UserAdmin

# Тут добавляю свои таблицы БД в панель admin

# Кастомизирую стандартную БД пользователей под себя
class CustomUserAdmin(UserAdmin):
    model = CustomUser
    # Добавляем роль в список отображения
    list_display = ['username', 'email', 'role', 'is_active', 'is_staff']
    # Позволяем редактировать роль и статус активности прямо в админке
    fieldsets = UserAdmin.fieldsets + (
        (None, {'fields': ('role',)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (None, {'fields': ('role',)}),
    )

admin.site.register(Order)
admin.site.register(Vehicle)
admin.site.register(DeliveryPlan)
admin.site.register(PlanItem)
admin.site.register(CustomUser, CustomUserAdmin)