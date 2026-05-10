from django.shortcuts import render, redirect, get_object_or_404
from .forms import RegisterForm, VehicleCreateForm, OrderCreateForm  # <-- Добавлен OrderCreateForm
from django.contrib.auth import authenticate, login
from django.contrib.auth.forms import AuthenticationForm
from .models import Order, Vehicle, DeliveryPlan, PlanItem
from django.http import JsonResponse
import json
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.db.models import Count
from django.template.loader import render_to_string
from django.utils import timezone
import datetime


# Главная
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


# Вход
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


# Главная страница логистического отдела/ Страница управления заказами
def logistics_view(request):
    orders = Order.objects.all().order_by('-id')

    # Фильтры
    address_query = request.GET.get('address')
    if address_query:
        orders = orders.filter(address__icontains=address_query)

    date_query = request.GET.get('date')
    if date_query:
        orders = orders.filter(delivery_data=date_query)

    volume_query = request.GET.get('volume')
    if volume_query:
        orders = orders.filter(volume__gte=volume_query)

    weight_query = request.GET.get('weight')
    if weight_query:
        orders = orders.filter(weight__gte=weight_query)

    # Контекст вынесен наружу, чтобы данные были всегда
    context = {
        'orders': orders,
        'count_pending': Order.objects.filter(status='pending').count(),
        'count_planned': Order.objects.filter(status='planned').count(),
        'count_in_transit': Order.objects.filter(status='shipped').count(),
        'count_delivered': Order.objects.filter(status='delivered').count(),
        'total_orders': Order.objects.count(),
    }
    return render(request, 'main/logistics.html', context)

# Страница создания заказа
def order_create_view(request):
    if request.method == 'POST':
        form = OrderCreateForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('logistics_dashboard')
    else:
        form = OrderCreateForm()

    # Используем тот же шаблон или структуру для единообразия
    return render(request, 'main/order_form.html', {'form': form})


# Редактирование заказа
def order_update_inline(request, pk):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            order = get_object_or_404(Order, pk=pk)

            order.address = data.get('address')
            order.volume = data.get('volume')
            order.weight = data.get('weight')
            order.delivery_data = data.get('delivery_data')

            # ВОТ ЭТА СТРОЧКА:
            order.status = data.get('status', order.status)

            order.save()
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return JsonResponse({'status': 'error'}, status=405)

# Удаление заказа
def order_delete_view(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if request.method == 'POST':
        order.delete()
        return JsonResponse({'status': 'success'})  # Возвращаем JSON вместо редиректа
    return JsonResponse({'status': 'error'}, status=400)


# Страница формирования плана
def planning_dashboard(request):
    pending_orders = Order.objects.filter(status=Order.Status.PENDING).order_by('delivery_data')
    return render(request, 'main/planning.html', {'orders': pending_orders})


# Формирование плана
def generate_plan_view(request):
    if request.method == 'POST':
        order_ids = request.POST.getlist('order_ids')

        if not order_ids:
            # Если ничего не выбрали, просто возвращаемся назад
            return redirect('planning_dashboard')

        # 1. Загружаем выбранные заказы и сортируем по дате и объему (от больших к малым)
        orders = Order.objects.filter(id__in=order_ids).order_by('delivery_data', '-volume')

        # 2. Получаем все доступные машины
        vehicles = list(Vehicle.objects.all())

        # Используем транзакцию, чтобы если что-то упадет, база не изменилась наполовину
        with transaction.atomic():
            for order in orders:
                # Ищем подходящий черновик плана на эту дату для этого заказа
                # Или создаем новый, если машина свободна

                plan_found = False

                # Пробуем "засунуть" заказ в уже существующие черновики планов на эту дату
                existing_plans = DeliveryPlan.objects.filter(
                    date=order.delivery_data,
                    status=DeliveryPlan.Status.DRAFT
                )

                for plan in existing_plans:
                    # Считаем текущую загрузку машины в этом плане
                    items = PlanItem.objects.filter(plan=plan)
                    current_volume = sum(item.order.volume for item in items)
                    current_weight = sum(item.order.weight for item in items)

                    # Проверяем, влезет ли новый заказ
                    if (current_volume + order.volume <= plan.vehicle.capacity_volume and
                            current_weight + order.weight <= plan.vehicle.capacity_weight):
                        PlanItem.objects.create(plan=plan, order=order)
                        order.status = Order.Status.PLANNED
                        order.save()
                        plan_found = True
                        break

                if plan_found:
                    continue

                # Если в существующие планы не влезло, ищем пустую машину
                # (которая еще не занята в этот день)
                busy_vehicles_ids = DeliveryPlan.objects.filter(
                    date=order.delivery_data
                ).values_list('vehicle_id', flat=True)

                available_vehicle = Vehicle.objects.exclude(id__in=busy_vehicles_ids).first()

                if available_vehicle:
                    # Создаем новый план (черновик)
                    new_plan = DeliveryPlan.objects.create(
                        date=order.delivery_data,
                        vehicle=available_vehicle,
                        status=DeliveryPlan.Status.DRAFT
                    )
                    PlanItem.objects.create(plan=new_plan, order=order)
                    order.status = Order.Status.PLANNED
                    order.save()
                else:
                    # Тут можно добавить логику, если машин не хватило вообще
                    # Пока просто оставим заказ PENDING
                    pass

        return redirect('review_drafts')

    return redirect('planning_dashboard')

# Пересмотр плана
def review_drafts_view(request):
    # Берем только черновики
    drafts = DeliveryPlan.objects.filter(status=DeliveryPlan.Status.DRAFT).prefetch_related('planitem_set__order')

    return render(request, 'main/review_drafts.html', {'drafts': drafts})

# Утверждение плана
def approve_all_drafts_view(request):
    if request.method == 'POST':
        # Находим все черновики и меняем статус на "Утвержден"
        updated_count = DeliveryPlan.objects.filter(status=DeliveryPlan.Status.DRAFT).update(
            status=DeliveryPlan.Status.APPROVED)

        # Можно добавить сообщение об успехе (опционально)
        return redirect('logistics_dashboard')  # Возвращаемся на главную
    return redirect('review_drafts')

# Календарь плана на месяц
def calendar_events_api(request):
    # Группируем планы по датам и считаем, сколько машин задействовано в каждый день
    plans = DeliveryPlan.objects.values('date', 'status').annotate(total=Count('id'))

    events = []
    for p in plans:
        # Цвет зависит от статуса: черновики — оранжевые, утвержденные — зеленые
        color = '#ffc107' if p['status'] == DeliveryPlan.Status.DRAFT else '#198754'
        events.append({
            'title': f"Планов: {p['total']}",
            'start': p['date'].isoformat(),
            'backgroundColor': color,
            'borderColor': color,
            'extendedProps': {'status': p['status']}
        })
    return JsonResponse(events, safe=False)

# План на день
def plan_detail_api(request, date_str):
    # Получаем детальную информацию о планах на конкретный день для модального окна
    plans = DeliveryPlan.objects.filter(date=date_str).prefetch_related('planitem_set__order', 'vehicle')

    html = render_to_string('main/plan_day_modal.html', {'plans': plans, 'date': date_str})
    return JsonResponse({'html': html})

# Главная страница транспортного отдела/ Страница управления автопарком
def transport_view(request):
    # Начинаем со всех машин
    vehicles = Vehicle.objects.all().order_by('-id')

    # 1. Поиск по названию/номеру
    search_query = request.GET.get('search')
    if search_query:
        vehicles = vehicles.filter(name__icontains=search_query)

    # 2. Фильтр по минимальному объему
    min_volume = request.GET.get('min_volume')
    if min_volume and min_volume.strip():
        try:
            vehicles = vehicles.filter(capacity_volume__gte=float(min_volume))
        except ValueError:
            pass  # Если ввели не число, просто пропускаем

    # 3. Фильтр по минимальному весу
    min_weight = request.GET.get('min_weight')
    if min_weight and min_weight.strip():
        try:
            vehicles = vehicles.filter(capacity_weight__gte=float(min_weight))
        except ValueError:
            pass

    return render(request, 'main/transport.html', {'vehicles': vehicles})


# Страница добавления транспорта
def vehicle_create_view(request):
    if request.method == 'POST':
        form = VehicleCreateForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('transport_dashboard')
    else:
        form = VehicleCreateForm()

    return render(request, 'main/vehicle_form.html', {'form': form})


# Редактирование транспорта
def vehicle_update_inline(request, pk):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            vehicle = get_object_or_404(Vehicle, pk=pk)
            vehicle.name = data.get('name')
            vehicle.capacity_weight = data.get('capacity_weight')
            vehicle.capacity_volume = data.get('capacity_volume')
            vehicle.save()
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return JsonResponse({'status': 'error'}, status=405)


# Удаление транспорта
def vehicle_delete_view(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk)
    if request.method == 'POST':
        vehicle.delete()
        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error'}, status=400)


# Страница графика рейсов
def transport_schedule_view(request):
    today = timezone.now().date()
    # Загружаем планы на сегодня
    today_plans = DeliveryPlan.objects.filter(
        date=today,
        status=DeliveryPlan.Status.APPROVED
    ).prefetch_related('planitem_set__order', 'vehicle')

    return render(request, 'main/transport_schedule.html', {
        'today_plans': today_plans,
        'today': today
    })

# API для смены статуса заказа
def update_order_status_ajax(request, pk):
    if request.method == 'POST':
        data = json.loads(request.body)
        new_status = data.get('status')

        # Получаем список всех разрешенных статусов из модели Order
        valid_statuses = [choice[0] for choice in Order.Status.choices]

        if new_status in valid_statuses:
            order = get_object_or_404(Order, pk=pk)
            order.status = new_status
            order.save()
            return JsonResponse({'status': 'success'})
        else:
            # Если статус не подошел, выводим ошибку прямо в терминал
            print(f"ОШИБКА СТАТУСА: Сервер получил '{new_status}', но в БД разрешены только {valid_statuses}")
            return JsonResponse({'status': 'error', 'message': f'Недопустимый статус: {new_status}'}, status=400)

    return JsonResponse({'status': 'error', 'message': 'Разрешены только POST-запросы'}, status=400)

# План на определенную дату
def get_plans_for_date_api(request, date_str):
    """Возвращает HTML-код планов на указанную дату"""
    try:
        selected_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'status': 'error', 'message': 'Неверный формат даты'}, status=400)

    plans = DeliveryPlan.objects.filter(
        date=selected_date,
        status=DeliveryPlan.Status.APPROVED
    ).prefetch_related('planitem_set__order', 'vehicle')

    # Рендерим нужный HTML-фрагмент (мы можем использовать тот же шаблон, что и для модального окна, или отдельный небольшой блок)
    html = render_to_string('main/schedule_plans_list.html', {
        'today_plans': plans,
        'date': selected_date
    })
    return JsonResponse({'html': html})