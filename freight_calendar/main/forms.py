from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import CustomUser, Order, Vehicle


class RegisterForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ['username', 'password1', 'password2', 'role']

class OrderCreateForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['address', 'volume', 'weight','delivery_data']
        widgets = {
            'address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Улица, дом, квартира'}),
            'volume': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1', 'placeholder': 'м³'}),
            'weight': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1', 'placeholder': 'кг'}),
            'delivery_data': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }

class VehicleCreateForm(forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = ['name', 'capacity_volume', 'capacity_weight']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '0000 AA-0'}),
            'capacity_volume': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1', 'placeholder': 'м³'}),
            'capacity_weight': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1', 'placeholder': 'кг'}),
        }