from django.urls import path
from . import views

urlpatterns = [
    path('', views.index),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logistics/', views.logistics_view, name='logistics_dashboard'),
    path('transport/', views.transport_view, name='transport_dashboard'),
]
