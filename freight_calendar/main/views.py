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
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.db.models import Sum, Max
from django.utils import timezone
from datetime import timedelta
from .models import Order, Vehicle, VehicleMaintenance


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
from dateutil.relativedelta import relativedelta


def get_next_dates(start_date, frequency, horizon_months=2):
    """Генерирует список дат для периодических заказов согласно интервалу"""
    dates = [start_date]
    curr = start_date
    end_date = start_date + relativedelta(months=horizon_months)

    delta = {
        Order.Frequency.WEEKLY: relativedelta(weeks=1),
        Order.Frequency.BIWEEKLY: relativedelta(weeks=2),
        Order.Frequency.TRIWEEKLY: relativedelta(weeks=3),
        Order.Frequency.MONTHLY: relativedelta(months=1),
        Order.Frequency.HALFYEARLY: relativedelta(months=6),
    }.get(frequency)

    if delta:
        while True:
            curr += delta
            if curr > end_date: break
            dates.append(curr)
    return dates


@transaction.atomic
def generate_plan_view(request):
    """Стандартная кнопка 'Сформировать план' теперь тоже использует общую функцию"""
    if request.method == 'POST':
        order_ids = request.POST.getlist('order_ids')
        if not order_ids:
            return redirect('planning_dashboard')

        selected_orders = Order.objects.filter(id__in=order_ids)
        target_dates = set()

        # Обработка периодичности (создаем копии на будущее)
        for original_order in selected_orders:
            if original_order.delivery_type == Order.DeliveryType.PERIODIC:
                future_dates = get_next_dates(original_order.delivery_data, original_order.frequency)
                for i, date in enumerate(future_dates):
                    target_dates.add(date)
                    if i > 0:
                        Order.objects.get_or_create(
                            address=original_order.address,
                            volume=original_order.volume,
                            weight=original_order.weight,
                            delivery_type=Order.DeliveryType.URGENT,
                            delivery_data=date,
                            defaults={'status': Order.Status.PENDING}
                        )
            else:
                target_dates.add(original_order.delivery_data)

        # Запускаем наше автоматическое планирование
        auto_plan_for_dates(list(target_dates))

        return redirect('planning_dashboard')
    return redirect('planning_dashboard')


def calendar_events_api(request):
    """API для календаря: считает баланс и красит дни"""
    start_str = request.GET.get('start', '').split('T')[0]
    end_str = request.GET.get('end', '').split('T')[0]

    if not (start_str and end_str):
        return JsonResponse([], safe=False)

    start_date = dt.datetime.strptime(start_str, '%Y-%m-%d').date()
    end_date = dt.datetime.strptime(end_str, '%Y-%m-%d').date()

    fleet = Vehicle.objects.aggregate(tw=Sum('capacity_weight'), tv=Sum('capacity_volume'))
    total_w = fleet['tw'] or 0
    total_v = fleet['tv'] or 0

    events = []
    curr = start_date
    while curr < end_date:
        # 1. Доступные ресурсы (минус ремонт)
        maint = VehicleMaintenance.objects.filter(
            start_date__lte=curr, end_date__gte=curr
        ).aggregate(lw=Sum('vehicle__capacity_weight'), lv=Sum('vehicle__capacity_volume'))

        avail_w = total_w - (maint['lw'] or 0)
        avail_v = total_v - (maint['lv'] or 0)

        # 2. Статистика заказов на день
        day_orders = Order.objects.filter(delivery_data=curr).exclude(status=Order.Status.CANCELED)
        orders_stats = day_orders.aggregate(cw=Sum('weight'), cv=Sum('volume'))

        cur_w = orders_stats['cw'] or 0
        cur_v = orders_stats['cv'] or 0

        # 3. ГЛАВНОЕ: Проверяем, есть ли нераспределенные заказы
        # Если заказ остался PENDING — значит он не влез ни в одну машину
        has_pending = day_orders.filter(status=Order.Status.PENDING).exists()

        # 4. Логика цвета
        # День красный, если: общий перегруз ИЛИ есть хоть один нераспределенный заказ
        is_overloaded = (cur_w > avail_w) or (cur_v > avail_v) or has_pending

        if is_overloaded:
            title = "⚠ Требуется перепланирование"
            bg_color = '#dc3545'  # Красный (danger)
            detail = f"Дефицит ресурсов или заказы не влезли в авто.\nЗаказы: {int(cur_w)}/{int(avail_w)} кг"
        else:
            # Показываем плашку только если есть хотя бы один запланированный заказ
            if day_orders.exists():
                title = "✅ Ресурсы в норме"
                bg_color = '#198754'  # Зеленый (success)
                detail = f"Все заказы распределены.\nЗагрузка: {int(cur_w)}/{int(avail_w)} кг"
            else:
                # Если заказов нет вообще, можно не выводить событие или сделать его серым
                curr += dt.timedelta(days=1)
                continue

        events.append({
            'title': title,
            'start': curr.isoformat(),
            'backgroundColor': bg_color,
            'borderColor': bg_color,
            'allDay': True,
            'extendedProps': {
                'detail_text': detail
            }
        })
        curr += dt.timedelta(days=1)

    return JsonResponse(events, safe=False)


def suggest_optimal_date_api(request, pk):
    """API интеллектуального поиска даты"""
    try:
        order = get_object_or_404(Order, pk=pk)

        # Предварительная проверка: есть ли в парке машина, способная это поднять в принципе
        limits = Vehicle.objects.aggregate(mw=Max('capacity_weight'), mv=Max('capacity_volume'))
        if order.weight > (limits['mw'] or 0) or order.volume > (limits['mv'] or 0):
            return JsonResponse({
                'status': 'error',
                'message': f'Заказ слишком велик для нашего парка (Макс. авто: {limits["mw"]}кг)'
            }, status=400)

        # Начинаем поиск со следующего дня
        start_date = order.delivery_data

        # Ищем на 60 дней вперед
        for i in range(1, 61):
            test_date = start_date + timedelta(days=i)

            # Если день подходит по всем параметрам
            if check_order_fits_day(order, test_date):
                return JsonResponse({
                    'status': 'success',
                    'optimal_date': test_date.isoformat(),
                    'message': f'Найдено свободное окно на {test_date.strftime("%d.%m.%Y")}'
                })

        return JsonResponse({'status': 'error', 'message': 'На ближайшие 2 месяца свободных мест нет.'}, status=404)

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


def auto_plan_for_dates(dates_list):
    """
    Универсальная функция, которая перепланирует черновики для списка дат.
    Вызывается и при нажатии кнопки 'Сформировать', и автоматически при переносе.
    """
    with transaction.atomic():
        # Очищаем старые черновики на эти даты
        # Мы удаляем черновики, чтобы алгоритм перераспределил машины с нуля максимально эффективно
        DeliveryPlan.objects.filter(date__in=dates_list, status=DeliveryPlan.Status.DRAFT).delete()

        # Сбрасываем заказы, которые были в этих черновиках, обратно в "Ожидает"
        Order.objects.filter(delivery_data__in=dates_list, status=Order.Status.PLANNED).update(
            status=Order.Status.PENDING)

        # Проходим по каждой дате и запускаем алгоритм Best Fit
        for target_date in sorted(list(dates_list)):
            # Берем все заказы на день (кроме отмененных и уже утвержденных в рейсах)
            day_orders = Order.objects.filter(
                delivery_data=target_date,
                status=Order.Status.PENDING
            ).order_by('-weight', '-volume')

            # Состояние машин на эту дату (не в ремонте)
            vehicles_pool = []
            for v in Vehicle.objects.all().order_by('-capacity_weight'):
                if not v.is_on_maintenance(target_date):
                    vehicles_pool.append({
                        'obj': v,
                        'rem_w': v.capacity_weight,
                        'rem_v': v.capacity_volume,
                        'plan': None
                    })

            # Пытаемся разложить каждый заказ по машинам
            for order in day_orders:
                for v_data in vehicles_pool:
                    if v_data['rem_w'] >= order.weight and v_data['rem_v'] >= order.volume:
                        # Если для этой машины еще нет черновика на сегодня — создаем
                        if not v_data['plan']:
                            v_data['plan'] = DeliveryPlan.objects.create(
                                date=target_date,
                                vehicle=v_data['obj'],
                                status=DeliveryPlan.Status.DRAFT
                            )
                        # Добавляем заказ в машину
                        PlanItem.objects.create(plan=v_data['plan'], order=order)
                        v_data['rem_w'] -= order.weight
                        v_data['rem_v'] -= order.volume
                        order.status = Order.Status.PLANNED
                        order.save()
                        break


# --- 2. ОБНОВЛЯЕМ ОБРАБОТЧИК ПЕРЕНОСА (РАКЕТА) ---
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
@require_POST
def update_order_date_ajax(request, pk):
    """Обновляет дату заказа и СРАЗУ запускает перепланирование"""
    try:
        data = json.loads(request.body)
        new_date_str = data.get('new_date')
        new_date = datetime.strptime(new_date_str, '%Y-%m-%d').date()

        order = get_object_or_404(Order, pk=pk)
        old_date = order.delivery_data  # Запоминаем старую дату

        # 1. Обновляем данные заказа
        order.delivery_data = new_date
        # Удаляем из любых существующих планов
        PlanItem.objects.filter(order=order).delete()
        order.status = Order.Status.PENDING
        order.save()

        # 2. АВТОМАТИЧЕСКИ запускаем перепланирование для двух дат
        # Это нужно, чтобы на старой дате уплотнить заказы, а на новой - впихнуть этот
        auto_plan_for_dates([old_date, new_date])

        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


# --- 3. ОБНОВЛЯЕМ ГЛАВНУЮ КНОПКУ "СФОРМИРОВАТЬ ПЛАН" ---


# Удаление транспорта
@require_POST
def vehicle_delete(request, pk):
    """
    Удаляет автомобиль из базы данных по его ID.
    """
    vehicle = get_object_or_404(Vehicle, pk=pk)
    vehicle.delete()
    return JsonResponse({'status': 'success'})


def check_order_fits_day(order, target_date):
    """
    Улучшенная проверка: влезет ли заказ на конкретную дату с учетом
    всех существующих заказов (и ожидающих, и запланированных).
    """
    # 1. Считаем суммарный СПРОС на этот день (все заказы: и Pending, и Planned)
    # Мы исключаем текущий заказ из расчета, чтобы не считать его дважды
    day_stats = Order.objects.filter(
        delivery_data=target_date
    ).exclude(
        status=Order.Status.CANCELED
    ).exclude(
        id=order.id  # Важно: не считаем самого себя
    ).aggregate(sw=Sum('weight'), sv=Sum('volume'))

    current_demand_w = day_stats['sw'] or 0
    current_demand_v = day_stats['sv'] or 0

    # 2. Считаем РЕСУРСЫ парка на этот день (все авто минус те, что в ремонте)
    fleet_stats = Vehicle.objects.exclude(
        vehiclemaintenance__start_date__lte=target_date,
        vehiclemaintenance__end_date__gte=target_date
    ).aggregate(tw=Sum('capacity_weight'), tv=Sum('capacity_volume'))

    total_fleet_w = fleet_stats['tw'] or 0
    total_fleet_v = fleet_stats['tv'] or 0

    # 3. ПРОВЕРКА 1: Есть ли вообще свободное место в общем объеме парка?
    if (total_fleet_w - current_demand_w) < order.weight:
        return False
    if (total_fleet_v - current_demand_v) < order.volume:
        return False

    # 4. ПРОВЕРКА 2: Есть ли в этот день хотя бы одна подходящая по габаритам машина,
    # которая физически сможет поднять этот вес (даже если она будет пустая)
    suitable_vehicle_exists = Vehicle.objects.exclude(
        vehiclemaintenance__start_date__lte=target_date,
        vehiclemaintenance__end_date__gte=target_date
    ).filter(
        capacity_weight__gte=order.weight,
        capacity_volume__gte=order.volume
    ).exists()

    return suitable_vehicle_exists


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


@transaction.atomic
@require_POST
def approve_plans_by_date_api(request, date_str):
    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        # Ищем все черновики на эту дату
        draft_plans = DeliveryPlan.objects.filter(date=target_date, status=DeliveryPlan.Status.DRAFT)

        if not draft_plans.exists():
            return JsonResponse({'status': 'error', 'message': 'Нет черновиков на эту дату'}, status=404)

        for plan in draft_plans:
            plan.status = DeliveryPlan.Status.APPROVED
            plan.save()
            # Обновляем статус заказов в этом плане
            Order.objects.filter(planitem__plan=plan).update(status=Order.Status.SHIPPED)

        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


# 2. Обновим plan_detail_api (уже есть у вас, убедитесь, что передаете нужные данные в шаблон)
def plan_detail_api(request, date_str):
    selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()

    # Статистика ресурсов
    fleet = Vehicle.objects.aggregate(tw=Sum('capacity_weight'), tv=Sum('capacity_volume'))
    lost = VehicleMaintenance.objects.filter(start_date__lte=selected_date, end_date__gte=selected_date).aggregate(
        lw=Sum('vehicle__capacity_weight'), lv=Sum('vehicle__capacity_volume'))

    avail_w = (fleet['tw'] or 0) - (lost['lw'] or 0)
    avail_v = (fleet['tv'] or 0) - (lost['lv'] or 0)

    # Заказы на этот день
    orders = Order.objects.filter(delivery_data=selected_date).order_by('status')

    # Проверка: есть ли черновики для утверждения?
    has_drafts = DeliveryPlan.objects.filter(date=selected_date, status=DeliveryPlan.Status.DRAFT).exists()

    html = render_to_string('main/plan_day_modal.html', {
        'orders': orders,
        'date': selected_date,
        'date_str': date_str,
        'avail_w': avail_w,
        'avail_v': avail_v,
        'has_drafts': has_drafts,
    })
    return JsonResponse({'html': html})

def transport_calendar_events_api(request):
    """API специально для страницы графика рейсов: только отметки о наличии планов"""
    start_str = request.GET.get('start', '').split('T')[0]
    end_str = request.GET.get('end', '').split('T')[0]

    if not (start_str and end_str):
        return JsonResponse([], safe=False)

    start_date = dt.datetime.strptime(start_str, '%Y-%m-%d').date()
    end_date = dt.datetime.strptime(end_str, '%Y-%m-%d').date()

    # Ищем даты, на которые есть утвержденные планы
    active_dates = DeliveryPlan.objects.filter(
        date__range=[start_date, end_date],
        status=DeliveryPlan.Status.APPROVED
    ).values_list('date', flat=True).distinct()

    events = []
    for date in active_dates:
        events.append({
            'title': '📌',  # Наш стикер кнопки
            'start': date.isoformat(),
            'allDay': True,
            'display': 'block',
            'backgroundColor': 'transparent', # Прозрачный фон
            'borderColor': 'transparent',     # Без границ
            'textColor': '#000',             # Цвет иконки
            'classNames': ['pin-event']       # Специальный класс для CSS
        })

    return JsonResponse(events, safe=False)