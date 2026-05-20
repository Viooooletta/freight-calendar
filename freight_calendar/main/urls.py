from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),

    # Админ-панель
    path('admin-panel/users/', views.admin_users_list, name='admin_users'),
    path('admin-panel/users/update/<int:pk>/', views.update_user_ajax, name='update_user_ajax'),
    path('admin-panel/users/password/<int:pk>/', views.change_password_ajax, name='change_password_ajax'),
    path('admin-panel/users/fire/<int:pk>/', views.fire_user_ajax, name='fire_user_ajax'),
    path('admin-panel/logs/', views.event_log_view, name='admin_logs'),
    path('admin-panel/logs/user/<int:user_id>/', views.user_history_api, name='user_history_api'),

    # Логистический отдел
    path('logistics/management/', views.logistics_view, name='logistics_dashboard'),
    path('logistics/management/orders/create/', views.order_create_view, name='order_create'),
    path('logistics/management/orders/<int:pk>/update-inline/', views.order_update_inline, name='order_update_inline'),
    path('logistics/management/orders/<int:pk>/delete/', views.order_delete_view, name='order_delete'),

    # Планирование (ОКП)
    path('logistics/planning/', views.planning_dashboard, name='planning_dashboard'),
    path('logistics/planning/generate-plan/', views.generate_plan_view, name='generate_plan'),
    path('logistics/planning/review-drafts/', views.review_drafts_view, name='review_drafts'),
    path('logistics/planning/approve-all/', views.approve_all_drafts_view, name='approve_all_drafts'),

    # API для логиста
    path('logistics/api/calendar-events/', views.calendar_events_api, name='api_calendar_events'),
    path('api/plan-detail/<str:date_str>/', views.plan_detail_api, name='api_plan_detail'),
    path('api/order/<int:pk>/suggest-date/', views.suggest_optimal_date_api, name='api_suggest_date'),
    path('api/approve-plans-date/<str:date_str>/', views.approve_plans_by_date_api, name='approve_plans_date'),
    # Находим эту строку и проверяем:
    path('api/order/<int:pk>/update/', views.update_order_status_ajax, name='update_order_status'),
    # Транспортный отдел (Автопарк)
    path('transport/', views.transport_view, name='transport_dashboard'),
    path('transport/create/', views.vehicle_create_view, name='vehicle_create'),
    path('transport/vehicle/<int:pk>/update-inline/', views.vehicle_update_inline, name='vehicle_update_inline'),
    path('transport/vehicle/<int:pk>/delete/', views.vehicle_delete, name='vehicle_delete'),
    path('transport/maintenance/', views.transport_maintenance_view, name='transport_maintenance'),
    path('transport/maintenance/add-ajax/', views.add_maintenance_ajax, name='add_maintenance_ajax'),
    path('transport/maintenance/vehicle/<int:vehicle_id>/', views.vehicle_maintenance_detail_view,
         name='vehicle_maintenance_detail'),

    # Транспортный отдел (Водители)
    path('transport/drivers/', views.transport_drivers_view, name='transport_drivers'),
    path('transport/drivers/absence-add/', views.add_driver_absence_ajax, name='add_driver_absence_ajax'),
    path('transport/drivers/toggle-shift/', views.toggle_driver_shift_ajax, name='toggle_driver_shift'),
    path('transport/drivers/<int:pk>/update/', views.update_driver_ajax, name='update_driver_ajax'),
    path('api/driver/<int:pk>/data/', views.get_driver_data_api, name='api_driver_data'),

    # График рейсов
    path('transport/schedule/', views.transport_schedule_view, name='transport_schedule'),
    path('api/transport/schedule/<str:date_str>/', views.transport_schedule_api, name='transport_schedule_api'),
    path('api/transport/calendar-events/', views.transport_calendar_events_api, name='api_transport_calendar_events'),

    # Профиль и восстановление пароля
    path('password-reset/', views.password_reset_request, name='password_reset_request'),
    path('profile/', views.profile_view, name='profile'),
    path('profile/update/', views.profile_update_ajax, name='profile_update'),
    path('profile/password/', views.profile_change_password, name='profile_change_password'),
    path('profile/delete/', views.profile_delete_account, name='profile_delete_account'),

]
