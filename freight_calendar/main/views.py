from django.shortcuts import render, redirect
from .forms import RegisterForm, VehicleCreateForm, OrderCreateForm
from django.contrib.auth import login
from django.contrib.auth.forms import AuthenticationForm
from .models import Order, PlanItem
import traceback
import calendar
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
import datetime
from django.template.loader import render_to_string
from datetime import datetime
from .models import DeliveryPlan
import json
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST
from .models import Vehicle
from django.db.models import Sum
from .models import VehicleMaintenance
import datetime as dt
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST


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

            # Обновляем старые поля
            order.address = data.get('address')
            order.volume = float(data.get('volume', 0))
            order.weight = float(data.get('weight', 0))
            order.delivery_data = data.get('delivery_data')
            order.status = data.get('status', order.status)

            # ОБНОВЛЯЕМ НОВЫЕ ПОЛЯ
            order.delivery_type = data.get('delivery_type', order.delivery_type)
            order.frequency = data.get('frequency', order.frequency)

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
        # Если нажата кнопка "на неделю" и список пуст, берем все PENDING заказы на 7 дней вперед
        if not order_ids:
            today = timezone.now().date()
            next_week = today + dt.timedelta(days=7)
            orders = Order.objects.filter(
                status=Order.Status.PENDING,
                delivery_data__range=[today, next_week]
            ).order_by('delivery_data', '-weight')
        else:
            orders = Order.objects.filter(id__in=order_ids).order_by('delivery_data', '-weight')

        with transaction.atomic():
            for order in orders:
                # 1. Ищем существующий черновик плана на эту дату и этот груз
                # (Логика вашего старого распределения по машинам)
                # ... ваш существующий код поиска available_vehicle ...

                # В конце цикла обязательно:
                order.status = Order.Status.PLANNED
                order.save()

        return redirect('transport_schedule')


def transport_maintenance_view(request):
    vehicles = Vehicle.objects.all().order_by('name')
    total_perfect_weight = Vehicle.objects.aggregate(total=Sum('capacity_weight'))['total'] or 0
    total_perfect_volume = Vehicle.objects.aggregate(total=Sum('capacity_volume'))['total'] or 0

    date_str = request.GET.get('date', timezone.now().date().isoformat())
    selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    for vehicle in vehicles:
        vehicle.is_busy_on_selected_date = vehicle.is_on_maintenance(selected_date)

    year = selected_date.year
    month = selected_date.month

    days_in_month = calendar.monthrange(year, month)[1]
    days_in_year = 366 if calendar.isleap(year) else 365

    perfect_month_volume = total_perfect_volume * days_in_month
    perfect_month_weight = total_perfect_weight * days_in_month
    perfect_year_volume = total_perfect_volume * days_in_year
    perfect_year_weight = total_perfect_weight * days_in_year

    # Расчет на день
    day_maintenance = VehicleMaintenance.objects.filter(start_date__lte=selected_date, end_date__gte=selected_date)
    lost_day_weight = day_maintenance.aggregate(total=Sum('vehicle__capacity_weight'))['total'] or 0
    lost_day_volume = day_maintenance.aggregate(total=Sum('vehicle__capacity_volume'))['total'] or 0

    actual_day_weight = total_perfect_weight - lost_day_weight
    actual_day_volume = total_perfect_volume - lost_day_volume

    # Расчет на месяц
    month_maintenances = VehicleMaintenance.objects.filter(
        start_date__lte=datetime(year, month, days_in_month).date(),
        end_date__gte=datetime(year, month, 1).date()
    ).select_related('vehicle')

    lost_month_volume = 0
    lost_month_weight = 0
    for m in month_maintenances:
        overlap_start = max(m.start_date, datetime(year, month, 1).date())
        overlap_end = min(m.end_date, datetime(year, month, days_in_month).date())
        overlap_days = (overlap_end - overlap_start).days + 1
        if overlap_days > 0:
            lost_month_volume += m.vehicle.capacity_volume * overlap_days
            lost_month_weight += m.vehicle.capacity_weight * overlap_days

    actual_month_volume = max(0, perfect_month_volume - lost_month_volume)
    actual_month_weight = max(0, perfect_month_weight - lost_month_weight)

    pct_month_vol = int((actual_month_volume / perfect_month_volume * 100)) if perfect_month_volume else 100
    pct_month_wgt = int((actual_month_weight / perfect_month_weight * 100)) if perfect_month_weight else 100

    # Расчет на год
    year_maintenances = VehicleMaintenance.objects.filter(
        start_date__lte=datetime(year, 12, 31).date(),
        end_date__gte=datetime(year, 1, 1).date()
    ).select_related('vehicle')

    lost_year_volume = 0
    lost_year_weight = 0
    for m in year_maintenances:
        overlap_start = max(m.start_date, datetime(year, 1, 1).date())
        overlap_end = min(m.end_date, datetime(year, 12, 31).date())
        overlap_days = (overlap_end - overlap_start).days + 1
        if overlap_days > 0:
            lost_year_volume += m.vehicle.capacity_volume * overlap_days
            lost_year_weight += m.vehicle.capacity_weight * overlap_days

    actual_year_volume = max(0, perfect_year_volume - lost_year_volume)
    actual_year_weight = max(0, perfect_year_weight - lost_year_weight)

    pct_year_vol = int((actual_year_volume / perfect_year_volume * 100)) if perfect_year_volume else 100
    pct_year_wgt = int((actual_year_weight / perfect_year_weight * 100)) if perfect_year_weight else 100

    maintenances = VehicleMaintenance.objects.select_related('vehicle').order_by('-start_date')

    context = {
        'vehicles': vehicles,
        'maintenances': maintenances,
        'selected_date': selected_date,
        'actual_day_weight': actual_day_weight,
        'actual_day_volume': actual_day_volume,
        'lost_day_weight': lost_day_weight,
        'lost_day_volume': lost_day_volume,
        'pct_month_vol': pct_month_vol,
        'pct_year_wgt': pct_year_wgt,
    }

    prev_month_date = (datetime(year, month, 1) - dt.timedelta(days=1)).date()
    next_month_date = (datetime(year, month, 1) + dt.timedelta(days=32)).date()

    offset_month = 282.6 - (282.6 * pct_month_vol) / 100
    offset_year = 282.6 - (282.6 * pct_year_wgt) / 100

    color_month = 'color-high' if pct_month_vol > 85 else ('color-medium' if pct_month_vol > 60 else 'color-low')
    color_year = 'color-high' if pct_year_wgt > 85 else ('color-medium' if pct_year_wgt > 60 else 'color-low')

    context.update({
        'offset_month': offset_month,
        'offset_year': offset_year,
        'color_month': color_month,
        'color_year': color_year,
        'prev_month_date': prev_month_date.isoformat(),
        'next_month_date': next_month_date.isoformat(),
    })
    return render(request, 'main/transport_maintenance.html', context)


@require_POST
@csrf_protect
def add_maintenance_ajax(request):
    """Оригинальная AJAX-обработка с валидацией дат для твоей модели VehicleMaintenance"""
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        try:
            data = json.loads(request.body)
            vehicle_id = data.get('vehicle_id')
            start_date_str = data.get('start_date')
            end_date_str = data.get('end_date')
            reason = data.get('reason', 'Техническое обслуживание')

            if not all([vehicle_id, start_date_str, end_date_str]):
                return JsonResponse({'status': 'error', 'message': 'Заполните все поля дат.'}, status=400)

            # Безопасное получение объекта автомобиля
            vehicle = get_object_or_404(Vehicle, id=vehicle_id)

            # Превращаем строки 'YYYY-MM-DD' в полноценные объекты дат Python
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()

            if start_date > end_date:
                return JsonResponse(
                    {'status': 'error', 'message': 'Дата начала не может быть позже окончания ремонта.'}, status=400)

            # Запись строго по твоей модели
            VehicleMaintenance.objects.create(
                vehicle=vehicle,
                start_date=start_date,
                end_date=end_date,
                reason=reason
            )

            return JsonResponse({'status': 'success', 'message': 'Ремонт успешно зарегистрирован.'})

        except ValueError:
            return JsonResponse({'status': 'error', 'message': 'Неверный формат дат.'}, status=400)
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    return JsonResponse({'status': 'error', 'message': 'Недопустимый тип запроса.'}, status=400)

# Пересмотр плана
def review_drafts_view(request):
    # Берем только черновики
    drafts = DeliveryPlan.objects.filter(status=DeliveryPlan.Status.DRAFT).prefetch_related('planitem_set__order')

    return render(request, 'main/review_drafts.html', {'drafts': drafts})


# Утверждение плана
def approve_all_drafts_view(request):
    if request.method == 'POST':
        with transaction.atomic():
            # Берем все черновики
            draft_plans = DeliveryPlan.objects.filter(status=DeliveryPlan.Status.DRAFT)

            for plan in draft_plans:
                # Меняем статус самого плана
                plan.status = DeliveryPlan.Status.APPROVED
                plan.save()

                # Ищем все заказы, привязанные к этому плану, и ставим им "В пути"
                Order.objects.filter(planitem__plan=plan).update(status=Order.Status.SHIPPED)

        return redirect('logistics_dashboard')
    return redirect('review_drafts')

# Календарь плана на месяц
def calendar_events_api(request):
    start_str = request.GET.get('start', '').split('T')[0]
    end_str = request.GET.get('end', '').split('T')[0]

    if not start_str or not end_str:
        return JsonResponse([], safe=False)

    start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
    end_date = datetime.strptime(end_str, '%Y-%m-%d').date()

    # 1. Считаем общую идеальную мощность всего парка
    fleet_stats = Vehicle.objects.aggregate(
        total_w=Sum('capacity_weight'),
        total_v=Sum('capacity_volume')
    )
    total_w = fleet_stats['total_w'] or 0
    total_v = fleet_stats['total_v'] or 0

    events = []
    curr = start_date
    while curr < end_date:
        # 2. Считаем потери из-за СТО на этот день
        maint_stats = VehicleMaintenance.objects.filter(
            start_date__lte=curr, end_date__gte=curr
        ).aggregate(
            lost_w=Sum('vehicle__capacity_weight'),
            lost_v=Sum('vehicle__capacity_volume')
        )

        # Доступно = Всего - СТО
        avail_w = total_w - (maint_stats['lost_w'] or 0)
        avail_v = total_v - (maint_stats['lost_v'] or 0)

        # 3. Считаем сумму заказов на этот день
        order_stats = Order.objects.filter(
            delivery_data=curr
        ).exclude(status=Order.Status.CANCELED).aggregate(
            cur_w=Sum('weight'),
            cur_v=Sum('volume')
        )
        cur_w = order_stats['cur_w'] or 0
        cur_v = order_stats['cur_v'] or 0

        # 4. ЛОГИКА ПРОВЕРКИ (Перегруз по весу ИЛИ по объему)
        is_overloaded = (cur_w > avail_w) or (cur_v > avail_v)

        if is_overloaded:
            title = "⚠ Дефицит ресурсов"
            bg_color = '#dc3545'  # Красный
        else:
            title = "✅ Ресурсы в норме"
            bg_color = '#198754'  # Зеленый

        events.append({
            'title': title,
            'start': curr.isoformat(),
            'backgroundColor': bg_color,
            'borderColor': bg_color,
            'allDay': True,
            'extendedProps': {
                'is_overloaded': is_overloaded,
                'detail_text': f"Вес: {int(cur_w)}/{int(avail_w)} кг\nОбъем: {round(cur_v, 1)}/{round(avail_v, 1)} м³"
            }
        })
        curr += dt.timedelta(days=1)

    return JsonResponse(events, safe=False)
# План на день
def plan_detail_api(request, date_str):
    selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()

    # Считаем текущие показатели для сводки в модальном окне
    total_w = Vehicle.objects.aggregate(s=Sum('capacity_weight'))['s'] or 0
    total_v = Vehicle.objects.aggregate(s=Sum('capacity_volume'))['s'] or 0

    lost = VehicleMaintenance.objects.filter(start_date__lte=selected_date, end_date__gte=selected_date).aggregate(
        lw=Sum('vehicle__capacity_weight'), lv=Sum('vehicle__capacity_volume'))

    avail_w = total_w - (lost['lw'] or 0)
    avail_v = total_v - (lost['lv'] or 0)

    orders_stats = Order.objects.filter(delivery_data=selected_date).exclude(status=Order.Status.CANCELED).aggregate(
        ow=Sum('weight'), ov=Sum('volume'))

    orders = Order.objects.filter(delivery_data=selected_date).order_by('status')

    html = render_to_string('main/plan_day_modal.html', {
        'orders': orders,
        'date': selected_date,
        'avail_w': avail_w,
        'avail_v': avail_v,
        'cur_w': orders_stats['ow'] or 0,
        'cur_v': orders_stats['ov'] or 0,
    })
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
@require_POST
def vehicle_update_inline(request, pk):
    """
    Принимает AJAX JSON-запрос от фронтенда,
    валидирует данные и обновляет характеристики автомобиля.
    """
    vehicle = get_object_or_404(Vehicle, pk=pk)
    try:
        # Декодируем JSON, пришедший из JavaScript payload
        data = json.loads(request.body)

        # Обновляем поля модели
        vehicle.name = data.get('name')
        vehicle.capacity_weight = float(data.get('capacity_weight', 0))
        vehicle.capacity_volume = float(data.get('capacity_volume', 0))

        # Сохраняем изменения в базу данных
        vehicle.save()

        return JsonResponse({'status': 'success'})
    except (ValueError, TypeError, json.JSONDecodeError) as e:
        # Если прилетели некорректные числа или сломался JSON
        return JsonResponse({'status': 'error', 'message': 'Неверный формат данных'}, status=400)


@require_POST
def update_order_date_ajax(request, pk):
    try:
        data = json.loads(request.body)
        new_date = data.get('new_date')
        order = get_object_or_404(Order, pk=pk)
        order.delivery_data = new_date
        # Если заказ был в плане, удаляем его из плана при переносе даты, чтобы перепланировать
        PlanItem.objects.filter(order=order).delete()
        order.status = Order.Status.PENDING
        order.save()
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

# Удаление транспорта
@require_POST
def vehicle_delete(request, pk):
    """
    Удаляет автомобиль из базы данных по его ID.
    """
    vehicle = get_object_or_404(Vehicle, pk=pk)
    vehicle.delete()
    return JsonResponse({'status': 'success'})


# Страница графика рейсов
def transport_schedule_view(request):
    today = timezone.now().date()
    # Анотируем планы количеством заказов и фильтруем только те, где заказы > 0
    today_plans = DeliveryPlan.objects.annotate(
        items_count=Count('planitem')
    ).filter(
        date=today,
        status=DeliveryPlan.Status.APPROVED,
        items_count__gt=0  # ПОБЕДА НАД БАГОМ: только планы с заказами
    ).prefetch_related('planitem_set__order', 'vehicle')

    return render(request, 'main/transport_schedule.html', {
        'today_plans': today_plans,
        'today': today
    })

#
def transport_schedule_api(request, date_str):
    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()

        # Фильтруем пустые планы здесь тоже
        plans = DeliveryPlan.objects.annotate(
            items_count=Count('planitem')
        ).filter(
            date=target_date,
            status=DeliveryPlan.Status.APPROVED,
            items_count__gt=0
        ).select_related('vehicle').prefetch_related('planitem_set__order')

        html_content = render_to_string('main/schedule_plans_list.html', {
            'today_plans': plans
        }, request=request)

        return JsonResponse({'html': html_content})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

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


# Отображение страницы конкретной машины и её истории простоев
def vehicle_maintenance_detail_view(request, vehicle_id):
    # Получаем конкретную машину
    vehicle = get_object_or_404(Vehicle, id=vehicle_id)

    # ИСПРАВЛЕНО: .order_by вместо .order_of_by
    maintenances = VehicleMaintenance.objects.filter(vehicle=vehicle).order_by('-start_date')

    context = {
        'vehicle': vehicle,
        'maintenances': maintenances,
        'today': timezone.now().date().isoformat()
    }
    return render(request, 'main/vehicle_maintenance_detail.html', context)