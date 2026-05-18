from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),

    path('logistics/management/', views.logistics_view, name='logistics_dashboard'),
    path('logistics/management/orders/create/', views.order_create_view, name='order_create'),
    path('logistics/management/orders/<int:pk>/update-inline/', views.order_update_inline, name='order_update_inline'),
    path('logistics/management/orders/<int:pk>/delete/', views.order_delete_view, name='order_delete'),

    path('logistics/planning/', views.planning_dashboard, name='planning_dashboard'),
    path('logistics/planning/generate-plan/', views.generate_plan_view, name='generate_plan'),
    path('logistics/planning/review-drafts/', views.review_drafts_view, name='review_drafts'),
    path('logistics/planning/approve-all/', views.approve_all_drafts_view, name='approve_all_drafts'),

    path('api/order/<int:pk>/reschedule/', views.update_order_date_ajax, name='api_order_reschedule'),
    path('logistics/api/calendar-events/', views.calendar_events_api, name='api_calendar_events'),
    path('api/plan-detail/<str:date_str>/', views.plan_detail_api, name='api_plan_detail'),

    path('transport/', views.transport_view, name='transport_dashboard'),
    path('transport/create/', views.vehicle_create_view, name='vehicle_create'),
    path('transport/vehicle/<int:pk>/update-inline/', views.vehicle_update_inline, name='vehicle_update_inline'),
    path('transport/vehicle/<int:pk>/delete/', views.vehicle_delete, name='vehicle_delete'),
    path('transport/schedule/', views.transport_schedule_view, name='transport_schedule'),
    path('transport/order/<int:pk>/status/', views.update_order_status_ajax, name='update_order_status'),
    path('transport/api/schedule/<str:date_str>/', views.get_plans_for_date_api, name='api_schedule_for_date'),
    path('api/transport/schedule/<str:date_str>/', views.transport_schedule_api, name='transport_schedule_api'),
    path('transport/maintenance/', views.transport_maintenance_view, name='transport_maintenance'),
    path('transport/maintenance/add-ajax/', views.add_maintenance_ajax, name='add_maintenance_ajax'),
    path('transport/maintenance/vehicle/<int:vehicle_id>/', views.vehicle_maintenance_detail_view,
         name='vehicle_maintenance_detail'),
    path('transport/maintenance/add-ajax/', views.add_maintenance_ajax, name='add_maintenance_ajax'),
    path('api/approve-plans-date/<str:date_str>/', views.approve_plans_by_date_api, name='approve_plans_date'),
    path('api/order/<int:pk>/suggest-date/', views.suggest_optimal_date_api, name='api_suggest_date'),
path('api/transport/calendar-events/', views.transport_calendar_events_api, name='api_transport_calendar_events'),]