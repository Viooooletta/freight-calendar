from django.shortcuts import render, redirect
from .forms import RegisterForm
from django.contrib.auth import authenticate, login
from django.contrib.auth.forms import AuthenticationForm

#Главная
def index(request):
    return render(request, 'main/index.html')

# Регистрация
def register_view(request):
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('/login/')
    else:
        form = RegisterForm()

    return render(request, 'main/register.html', {'form': form})

#Вход
def login_view(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            if user.role == "admin":
                return redirect('/admin/')
            if user.role == 'logistics':
                return redirect('logistics_dashboard')
            elif user.role == 'transport':
                return redirect('transport_dashboard')
            return redirect('/')
    else:
        form = AuthenticationForm()

    return render(request, 'main/login.html', {'form': form})

# Главная страница логистического отдела
def logistics_view(request):
    return render(request, 'main/logistics.html')

# Главная страница транспортного отдела
def transport_view(request):
    return render(request, 'main/transport.html')