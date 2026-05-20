import json
import calendar
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Sum, Max, Q
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from .models import (
    Order, PlanItem, ActionLog, DeliveryPlan, Vehicle,
    VehicleMaintenance, CustomUser, Driver, DriverAbsence, DriverSchedule
)
from .forms import RegisterForm, VehicleCreateForm, OrderCreateForm, DriverCreateForm
from django.core.mail import EmailMessage  # Импортируем расширенный класс
from django.contrib import messages
from django.utils.crypto import get_random_string
from django.template.loader import render_to_string


def password_reset_request(request):
    if request.method == "POST":
        email = request.POST.get('email')
        associated_user = CustomUser.objects.filter(email=email).first()

        if associated_user:
            new_password = get_random_string(length=10)
            associated_user.set_password(new_password)
            associated_user.save()

            # Формируем тему и текст
            subject = f"Новый пароль для аккаунта '{associated_user.username}' в системе Freight Calendar"
            message = (
                f"Здравствуйте, {associated_user.username}!\n\n"
                f"Вы запросили восстановление доступа в системе Freight Calendar.\n"
                f"Ваш новый временный пароль: {new_password}\n\n"
                f"Пожалуйста, используйте его для входа и смените в настройках профиля."
            )

            # Используем EmailMessage для корректной работы с кодировкой UTF-8
            email_msg = EmailMessage(
                subject=subject,
                body=message,
                to=[associated_user.email],
            )
            email_msg.encoding = 'utf-8'  # Явно указываем кодировку

            try:
                email_msg.send()
                messages.success(request, 'Проверьте вашу указанную почту — мы отправили новый пароль.')
                log_action(associated_user, "Сброс пароля", "Запрошен новый пароль на почту")
                return redirect('login')
            except Exception as e:
                # Выводим более понятную ошибку, если что-то пойдет не так
                messages.error(request, f'Ошибка при отправке письма. Убедитесь, что настройки SMTP верны.')
                print(f"Email error: {e}")
        else:
            messages.error(request, 'Пользователь с таким email не найден в системе.')

    return render(request, 'main/password_reset.html')


# ==========================================
# 1. СИСТЕМНЫЕ ФУНКЦИИ И АУТЕНТИФИКАЦИЯ
# ==========================================

def log_action(user, action_type, description):
    """Универсальный регистратор действий для журнала ответственности"""
    if user.is_authenticated:
        ActionLog.objects.create(user=user, action_type=action_type, description=description)


def index(request):
    return render(request, 'main/index.html')


def register_view(request):
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            log_action(user, "Регистрация", "Пользователь зарегистрировался в системе")
            return redirect('login')  # Именованный URL, а не /login/
    else:
        form = RegisterForm()
    return render(request, 'main/register.html', {'form': form})


def login_view(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            log_action(user, "Авторизация", "Успешный вход в систему")
            if user.role == 'admin': return redirect('admin_users')
            if user.role == 'logistics': return redirect('logistics_dashboard')
            return redirect('transport_dashboard')
    return render(request, 'main/login.html', {'form': AuthenticationForm()})


# ==========================================
# 2. ВСПОМОГАТЕЛЬНЫЕ АЛГОРИТМЫ И ЛОГИКА ОКП
# ==========================================

def check_order_fits_day(order, target_date):
    """
    УМНАЯ ПРОВЕРКА МОЩНОСТИ:
    Проверяет, влезет ли заказ в парк с учетом графиков, ТО и текущей загрузки.
    """
    # 1. Находим все исправные машины на эту дату
    available_vehicles = Vehicle.objects.exclude(
        vehiclemaintenance__start_date__lte=target_date,
        vehiclemaintenance__end_date__gte=target_date
    ).order_by('-capacity_weight')

    # 2. Находим количество доступных водителей (есть смена и нет больничного)
    all_drivers = Driver.objects.all()
    available_drivers_count = len([d for d in all_drivers if d.is_available(target_date)])

    if available_drivers_count == 0 or not available_vehicles.exists():
        return False

    # 3. Эффективный флот (Бутылочное горлышко: мы не можем выпустить машин больше, чем водителей)
    # Берем N самых мощных машин, где N - кол-во водителей
    effective_vehicles = available_vehicles[:available_drivers_count]

    # Считаем общую грузоподъемность этого эффективного флота
    fleet_capacity = effective_vehicles.aggregate(
        tw=Sum('capacity_weight'),
        tv=Sum('capacity_volume')
    )
    total_w = fleet_capacity['tw'] or 0
    total_v = fleet_capacity['tv'] or 0

    # 4. Считаем текущую загрузку (все заказы на этот день, кроме перемещаемого)
    current_load = Order.objects.filter(
        delivery_data=target_date
    ).exclude(
        Q(status=Order.Status.CANCELED) | Q(id=order.id)
    ).aggregate(sw=Sum('weight'), sv=Sum('volume'))

    used_w = current_load['sw'] or 0
    used_v = current_load['sv'] or 0

    # 5. Проверка: Хватит ли общего остатка места?
    if (total_w - used_w) < order.weight or (total_v - used_v) < order.volume:
        return False

    # 6. Физическая проверка: Есть ли в этот день хотя бы одна машина,
    # в которую этот заказ влезет целиком по её ТТХ?
    can_physically_fit = available_vehicles.filter(
        capacity_weight__gte=order.weight,
        capacity_volume__gte=order.volume
    ).exists()

    return can_physically_fit


@transaction.atomic
def auto_plan_for_dates(dates_list):
    """
    АЛГОРИТМ БАЛАНСИРОВКИ (ОКП):
    Распределяет заказы, учитывая 'Бутылочное горлышко' (min от машин и водителей).
    Устойчив к дубликатам заказов в БД.
    """
    unique_dates = sorted(list(set(dates_list)))

    for target_date in unique_dates:
        # 1. Сбрасываем старые черновики планов и статус заказов для перепланирования на этот день
        DeliveryPlan.objects.filter(date=target_date, status=DeliveryPlan.Status.DRAFT).delete()

        # Заказы, которые были PLANNED на эту дату, возвращаем в PENDING для перерасчета
        # Это важно для функции "ракета", чтобы заказ мог быть перенесен
        Order.objects.filter(planitem__plan__date=target_date, planitem__plan__status=DeliveryPlan.Status.DRAFT).update(
            status=Order.Status.PENDING)

        # 2. Заказы на день (от тяжелых к легким), которые все еще "Ожидают"
        day_orders = Order.objects.filter(delivery_data=target_date, status=Order.Status.PENDING).order_by('-weight',
                                                                                                           '-volume')
        if not day_orders.exists():
            continue

        # 3. Машины (не в ремонте)
        available_vehicles = list(Vehicle.objects.exclude(
            vehiclemaintenance__start_date__lte=target_date,
            vehiclemaintenance__end_date__gte=target_date
        ).order_by('-capacity_weight'))

        # 4. Водители (есть смена и нет больничного)
        available_drivers = [d for d in Driver.objects.all() if d.is_available(target_date)]

        # 5. Лимит рейсов = сколько у нас полных экипажей (бутылочное горлышко)
        num_trips = min(len(available_vehicles), len(available_drivers))

        fleet_pool = []
        for i in range(num_trips):
            fleet_pool.append({
                'vehicle': available_vehicles[i],
                'driver': available_drivers[i],
                'rem_w': available_vehicles[i].capacity_weight,
                'rem_v': available_vehicles[i].capacity_volume,
                'plan': None  # Будущий план для этого экипажа
            })

        # 6. Распределение Best Fit
        for order in day_orders:
            assigned = False
            for trip in fleet_pool:
                if trip['rem_w'] >= order.weight and trip['rem_v'] >= order.volume:
                    if not trip['plan']:
                        trip['plan'] = DeliveryPlan.objects.create(
                            date=target_date, vehicle=trip['vehicle'],
                            driver=trip['driver'], status=DeliveryPlan.Status.DRAFT
                        )
                    PlanItem.objects.create(plan=trip['plan'], order=order)
                    trip['rem_w'] -= order.weight
                    trip['rem_v'] -= order.volume
                    order.status = Order.Status.PLANNED
                    order.save()
                    assigned = True
                    break
            # Если заказ не удалось распределить, он остается PENDING и отображается в красном дне
            if not assigned:
                # Статус уже PENDING, так что ничего менять не нужно, просто он не попал в план
                pass


# ==========================================
# 3. ЛОГИСТИКА: УПРАВЛЕНИЕ ЗАКАЗАМИ И ПЛАНИРОВАНИЕ
# ==========================================

@login_required
def logistics_view(request):
    orders = Order.objects.all().order_by('-id')

    # Фильтры
    if request.GET.get('address'): orders = orders.filter(address__icontains=request.GET.get('address'))
    if request.GET.get('date'): orders = orders.filter(delivery_data=request.GET.get('date'))
    if request.GET.get('volume'): orders = orders.filter(volume__gte=request.GET.get('volume'))
    if request.GET.get('weight'): orders = orders.filter(weight__gte=request.GET.get('weight'))

    context = {
        'orders': orders,
        'count_pending': Order.objects.filter(status='pending').count(),
        'count_planned': Order.objects.filter(status='planned').count(),
        'count_in_transit': Order.objects.filter(status='shipped').count(),
        'count_delivered': Order.objects.filter(status='delivered').count(),
        'total_orders': Order.objects.count(),
    }
    return render(request, 'main/logistics.html', context)


@login_required
def order_create_view(request):
    if request.method == 'POST':
        form = OrderCreateForm(request.POST)
        if form.is_valid():
            order = form.save()
            log_action(request.user, "Заказ", f"Создан новый заказ №{order.id}")
            return redirect('logistics_dashboard')
    return render(request, 'main/order_form.html', {'form': OrderCreateForm()})


@login_required
@require_POST
def order_update_inline(request, pk):
    order = get_object_or_404(Order, pk=pk)
    try:
        data = json.loads(request.body)
        order.address = data.get('address', order.address)
        order.volume = float(data.get('volume', order.volume))
        order.weight = float(data.get('weight', order.weight))
        order.delivery_data = data.get('delivery_data', order.delivery_data)
        order.status = data.get('status', order.status)
        order.delivery_type = data.get('delivery_type', order.delivery_type)
        order.frequency = data.get('frequency', order.frequency)
        order.save()
        log_action(request.user, "Изменение заказа", f"Обновлен заказ №{order.id}")
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


@login_required
@require_POST
def order_delete_view(request, pk):
    order = get_object_or_404(Order, pk=pk)
    order_id = order.id
    order.delete()
    log_action(request.user, "Удаление заказа", f"Заказ №{order_id} был удален")
    return JsonResponse({'status': 'success'})


@login_required
def planning_dashboard(request):
    """
    Отображает только 'крайние' заказы для каждой периодической цепочки.
    Это позволяет продлевать планирование, выбирая последний созданный заказ.
    """
    # 1. Берем все обычные (срочные) заказы в ожидании
    urgent_orders = Order.objects.filter(
        status=Order.Status.PENDING,
        delivery_type=Order.DeliveryType.URGENT
    )

    # 2. Логика для периодических: находим максимальную дату для каждой группы (адрес + тип + частота)
    # Чтобы в списке был только "хвост" цепочки, который можно продлить
    latest_periodic_ids = Order.objects.filter(
        status=Order.Status.PENDING,
        delivery_type=Order.DeliveryType.PERIODIC
    ).values('address', 'frequency').annotate(max_id=Max('id')).values_list('max_id', flat=True)

    periodic_orders = Order.objects.filter(id__in=latest_periodic_ids)

    # Объединяем списки
    orders = urgent_orders | periodic_orders
    orders = orders.order_by('delivery_data')

    return render(request, 'main/planning.html', {'orders': orders})


@login_required
@transaction.atomic
def generate_plan_view(request):
    """
    Создает 8 будущих периодов для выбранных заказов.
    """
    if request.method == 'POST':
        ids = request.POST.getlist('order_ids')
        selected_orders = Order.objects.filter(id__in=ids)
        target_dates = set()

        for o in selected_orders:
            # Добавляем текущую дату в календарь
            target_dates.add(o.delivery_data)

            # Если заказ периодический, создаем цепочку из 8 ПОВТОРЕНИЙ
            if o.delivery_type == Order.DeliveryType.PERIODIC and o.frequency != Order.Frequency.NONE:
                delta = {
                    Order.Frequency.WEEKLY: relativedelta(weeks=1),
                    Order.Frequency.BIWEEKLY: relativedelta(weeks=2),
                    Order.Frequency.TRIWEEKLY: relativedelta(weeks=3),
                    Order.Frequency.MONTHLY: relativedelta(months=1),
                    Order.Frequency.HALFYEARLY: relativedelta(months=6),
                }.get(o.frequency)

                if delta:
                    curr_d = o.delivery_data
                    for i in range(1, 9):  # Ровно 8 новых повторений
                        curr_d += delta

                        # Проверка на дубликаты перед созданием
                        exists = Order.objects.filter(
                            address=o.address,
                            delivery_data=curr_d,
                            weight=o.weight
                        ).exists()

                        if not exists:
                            Order.objects.create(
                                address=o.address,
                                weight=o.weight,
                                volume=o.volume,
                                delivery_data=curr_d,
                                delivery_type=o.delivery_type,
                                frequency=o.frequency,
                                status=Order.Status.PENDING
                            )
                        target_dates.add(curr_d)

        # Сразу пытаемся распределить созданные заказы по машинам (балансировка)
        auto_plan_for_dates(list(target_dates))

        log_action(request.user, "ОКП", f"Сформирован план на период (8 циклов) для {selected_orders.count()} позиций")

    return redirect('planning_dashboard')


@login_required
def suggest_optimal_date_api(request, pk):
    """
    ЛОГИКА КНОПКИ 'МАГИЯ' (🪄):
    Ищет ближайший день в будущем, где есть реальная мощность под этот заказ.
    """
    try:
        order = get_object_or_404(Order, pk=pk)
        start_search = order.delivery_data + timedelta(days=1)

        # Ищем оптимальный день в горизонте 60 дней
        for i in range(60):
            test_date = start_search + timedelta(days=i)

            # Пропускаем выходные, если у вас парк не работает (опционально)
            # if test_date.weekday() in [5, 6]: continue

            if check_order_fits_day(order, test_date):
                return JsonResponse({
                    'status': 'success',
                    'optimal_date': test_date.isoformat(),
                    'message': f'✨ Магия сработала! Найдено свободное место на {test_date.strftime("%d.%m.%Y")}.'
                })

        return JsonResponse({
            'status': 'error',
            'message': 'К сожалению, на ближайшие 2 месяца свободных мощностей под такой заказ не найдено.'
        }, status=404)

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@login_required
def review_drafts_view(request):
    """Страница для просмотра и утверждения черновиков планов"""
    drafts = DeliveryPlan.objects.filter(status=DeliveryPlan.Status.DRAFT).prefetch_related('planitem_set__order')
    return render(request, 'main/review_drafts.html', {'drafts': drafts})


@login_required
@transaction.atomic
def approve_all_drafts_view(request):
    """Утверждает все черновики планов в системе"""
    if request.method == 'POST':
        draft_plans = DeliveryPlan.objects.filter(status=DeliveryPlan.Status.DRAFT)
        for plan in draft_plans:
            plan.status = DeliveryPlan.Status.APPROVED
            plan.save()
            Order.objects.filter(planitem__plan=plan).update(status=Order.Status.SHIPPED)
        log_action(request.user, "Утверждение", f"Все черновики планов утверждены")
        return redirect('logistics_dashboard')
    return redirect('review_drafts')


@require_POST
@transaction.atomic
def approve_plans_by_date_api(request, date_str):
    """Утверждает черновики планов на конкретную дату"""
    target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    plans = DeliveryPlan.objects.filter(date=target_date, status=DeliveryPlan.Status.DRAFT)
    for p in plans:
        p.status = DeliveryPlan.Status.APPROVED
        p.save()
        # Все заказы, привязанные к этому плану, переводятся в статус "В пути"
        Order.objects.filter(planitem__plan=p).update(status=Order.Status.SHIPPED)
    log_action(request.user, "Утверждение", f"План на {date_str} переведен в статус рейсов")
    return JsonResponse({'status': 'success'})


# ==========================================
# 4. API КАЛЕНДАРЯ И ДЕТАЛИЗАЦИЯ ДНЕЙ
# ==========================================

@login_required
def calendar_events_api(request):
    """API для календаря логиста: индикация состояния ресурсов (красный/зеленый/синий)"""
    start_str = request.GET.get('start', '').split('T')[0]
    end_str = request.GET.get('end', '').split('T')[0]

    if not (start_str and end_str): return JsonResponse([], safe=False)

    start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
    end_date = datetime.strptime(end_str, '%Y-%m-%d').date()

    fleet = Vehicle.objects.aggregate(tw=Sum('capacity_weight'), tv=Sum('capacity_volume'))
    total_w, total_v = fleet['tw'] or 0, fleet['tv'] or 0

    events = []
    curr = start_date
    while curr < end_date:
        maint = VehicleMaintenance.objects.filter(
            start_date__lte=curr, end_date__gte=curr
        ).aggregate(lw=Sum('vehicle__capacity_weight'), lv=Sum('vehicle__capacity_volume'))

        avail_w = total_w - (maint['lw'] or 0)
        avail_v = total_v - (maint['lv'] or 0)

        # Берем все заказы на этот день, включая те, что не попали в план (PENDING)
        day_orders = Order.objects.filter(delivery_data=curr).exclude(status=Order.Status.CANCELED)
        orders_stats = day_orders.aggregate(cw=Sum('weight'), cv=Sum('volume'))

        cur_w, cur_v = orders_stats['cw'] or 0, orders_stats['cv'] or 0

        has_pending_unplanned = day_orders.filter(status=Order.Status.PENDING).exists()
        has_drafts = DeliveryPlan.objects.filter(date=curr, status=DeliveryPlan.Status.DRAFT).exists()
        has_approved_plans = DeliveryPlan.objects.filter(date=curr, status=DeliveryPlan.Status.APPROVED).exists()

        is_overloaded = (cur_w > avail_w) or (cur_v > avail_v) or has_pending_unplanned

        if is_overloaded:
            title = "⚠ Требуется перепланирование"
            bg_color = '#dc3545'  # Красный
            events.append({
                'title': title, 'start': curr.isoformat(),
                'backgroundColor': bg_color, 'borderColor': bg_color, 'allDay': True,
                'extendedProps': {'detail_text': "Дефицит ресурсов или есть нераспределенные заказы."}
            })
        elif has_drafts:
            title = "✅ Ресурсы в норме"
            bg_color = '#198754'  # Зеленый
            events.append({
                'title': title, 'start': curr.isoformat(),
                'backgroundColor': bg_color, 'borderColor': bg_color, 'allDay': True,
                'extendedProps': {'detail_text': "План сформирован, ожидает утверждения."}
            })
        elif has_approved_plans:
            # Если все утверждено, показываем синий фон и плашку "Рейсы утверждены"
            events.append({
                'start': curr.isoformat(), 'display': 'background', 'backgroundColor': '#e7f1ff', 'allDay': True,
            })
            events.append({
                'title': "🗓 Рейсы утверждены", 'start': curr.isoformat(),
                'backgroundColor': '#0d6efd', 'borderColor': '#0d6efd', 'allDay': True,
            })
        curr += timedelta(days=1)
    return JsonResponse(events, safe=False)


@login_required
def plan_detail_api(request, date_str):
    """Детализация дня в календаре ОКП для логиста (модальное окно)"""
    try:
        sel_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': 'Неверный формат даты'}, status=400)

    trucks_query = Vehicle.objects.exclude(
        vehiclemaintenance__start_date__lte=sel_date,
        vehiclemaintenance__end_date__gte=sel_date
    ).order_by('-capacity_weight')

    all_drivers = Driver.objects.all()
    d_available = [d for d in all_drivers if d.is_available(sel_date)]

    effective_fleet_ids = trucks_query.values_list('id', flat=True)[:len(d_available)]
    effective_fleet = Vehicle.objects.filter(id__in=effective_fleet_ids)
    res = effective_fleet.aggregate(w=Sum('capacity_weight'), v=Sum('capacity_volume'))

    html = render_to_string('main/plan_day_modal.html', {
        'date': sel_date,
        'date_str': date_str,
        'avail_w': res['w'] or 0,
        'avail_v': res['v'] or 0,
        'trucks_online': trucks_query.count(),
        'drivers_online': len(d_available),
        'day_plans': DeliveryPlan.objects.filter(date=sel_date).select_related('vehicle', 'driver'),
        'orders': Order.objects.filter(delivery_data=sel_date).order_by('status'),
        'has_drafts': DeliveryPlan.objects.filter(date=sel_date, status=DeliveryPlan.Status.DRAFT).exists()
    })
    return JsonResponse({'html': html})


@require_POST
def update_order_status_ajax(request, pk):
    try:
        order = get_object_or_404(Order, pk=pk)
        data = json.loads(request.body)
        new_status = data.get('status')

        # Список разрешенных статусов из твоей модели Order
        if new_status in [choice[0] for choice in Order.Status.choices]:
            order.status = new_status
            order.save()
            log_action(request.user, "Статус заказа", f"Заказ №{order.id} изменен на {new_status}")
            return JsonResponse({'status': 'success'})
        return JsonResponse({'status': 'error', 'message': 'Недопустимый статус'}, status=400)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


# ==========================================
# 5. ТРАНСПОРТНЫЙ ОТДЕЛ: АВТОПАРК И ТО
# ==========================================

@login_required
def transport_view(request):
    vehicles = Vehicle.objects.all().order_by('-id')
    # Фильтры
    if request.GET.get('search'): vehicles = vehicles.filter(name__icontains=request.GET.get('search'))
    if request.GET.get('min_volume'): vehicles = vehicles.filter(
        capacity_volume__gte=float(request.GET.get('min_volume')))
    if request.GET.get('min_weight'): vehicles = vehicles.filter(
        capacity_weight__gte=float(request.GET.get('min_weight')))
    return render(request, 'main/transport.html', {'vehicles': vehicles})


@login_required
def vehicle_create_view(request):
    if request.method == 'POST':
        form = VehicleCreateForm(request.POST)
        if form.is_valid():
            form.save()
            log_action(request.user, "Транспорт", f"Добавлен новый автомобиль {form.instance.name}")
            return redirect('transport_dashboard')
    return render(request, 'main/vehicle_form.html', {'form': VehicleCreateForm()})


@require_POST
def vehicle_update_inline(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk)
    try:
        data = json.loads(request.body)
        vehicle.name = data.get('name', vehicle.name)
        vehicle.capacity_weight = float(data.get('capacity_weight', vehicle.capacity_weight))
        vehicle.capacity_volume = float(data.get('capacity_volume', vehicle.capacity_volume))
        vehicle.save()
        log_action(request.user, "Транспорт", f"Обновлен автомобиль {vehicle.name}")
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


@require_POST
def vehicle_delete(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk)
    vehicle_name = vehicle.name
    vehicle.delete()
    log_action(request.user, "Транспорт", f"Удален автомобиль {vehicle_name}")
    return JsonResponse({'status': 'success'})


@login_required
def vehicle_maintenance_detail_view(request, vehicle_id):
    vehicle = get_object_or_404(Vehicle, id=vehicle_id)
    maintenances = VehicleMaintenance.objects.filter(vehicle=vehicle).order_by('-start_date')
    return render(request, 'main/vehicle_maintenance_detail.html', {
        'vehicle': vehicle, 'maintenances': maintenances, 'today': timezone.now().date().isoformat()
    })


@login_required
def transport_maintenance_view(request):
    """Страница ТО с расчетом KPI простоев (круговые диаграммы)"""
    vehicles = Vehicle.objects.all().order_by('name')
    total_perf_w = vehicles.aggregate(total=Sum('capacity_weight'))['total'] or 0
    total_perf_v = vehicles.aggregate(total=Sum('capacity_volume'))['total'] or 0

    date_str = request.GET.get('date', timezone.now().date().isoformat())
    sel_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    for v in vehicles:
        v.is_busy = v.is_on_maintenance(sel_date)

    # Расчет на день
    day_maint = VehicleMaintenance.objects.filter(start_date__lte=sel_date, end_date__gte=sel_date)
    lost_w = day_maint.aggregate(total=Sum('vehicle__capacity_weight'))['total'] or 0
    lost_v = day_maint.aggregate(total=Sum('vehicle__capacity_volume'))['total'] or 0

    # Расчет на месяц (для KPI)
    year, month = sel_date.year, sel_date.month
    days_in_month = calendar.monthrange(year, month)[1]
    perf_month_v = total_perf_v * days_in_month
    month_maints = VehicleMaintenance.objects.filter(
        start_date__lte=date(year, month, days_in_month), end_date__gte=date(year, month, 1)
    )
    lost_month_v = 0
    for m in month_maints:
        overlap = (min(m.end_date, date(year, month, days_in_month)) - max(m.start_date, date(year, month, 1))).days + 1
        lost_month_v += m.vehicle.capacity_volume * max(0, overlap)  # Учитываем только положительное пересечение

    pct_month_vol = int(((perf_month_v - lost_month_v) / perf_month_v * 100)) if perf_month_v else 100

    context = {
        'vehicles': vehicles,
        'maintenances': VehicleMaintenance.objects.all().order_by('-start_date'),
        'selected_date': sel_date,
        'actual_day_weight': total_perf_w - lost_w,
        'actual_day_volume': total_perf_v - lost_v,
        'lost_day_weight': lost_w,
        'lost_day_volume': lost_v,
        'pct_month_vol': pct_month_vol,
    }

    # Расчет для круговых диаграмм (CSS offsets)
    offset_month = 282.6 - (282.6 * pct_month_vol) / 100
    color_month = 'color-high' if pct_month_vol > 85 else ('color-medium' if pct_month_vol > 60 else 'color-low')

    # Даты для навигации по месяцам
    prev_month_date = (date(year, month, 1) - timedelta(days=1)).isoformat()
    next_month_date = (date(year, month, 1) + timedelta(days=32)).replace(day=1).isoformat()

    context.update({
        'offset_month': offset_month,
        'color_month': color_month,
        'prev_month_date': prev_month_date,
        'next_month_date': next_month_date,
    })
    return render(request, 'main/transport_maintenance.html', context)


@require_POST
@csrf_protect
def add_maintenance_ajax(request):
    """AJAX-обработчик для регистрации ТО"""
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        try:
            data = json.loads(request.body)
            vehicle_id = data.get('vehicle_id')
            start_date_str = data.get('start_date')
            end_date_str = data.get('end_date')
            reason = data.get('reason', 'Техническое обслуживание')

            if not all([vehicle_id, start_date_str, end_date_str]):
                return JsonResponse({'status': 'error', 'message': 'Заполните все поля дат.'}, status=400)

            vehicle = get_object_or_404(Vehicle, id=vehicle_id)
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()

            if start_date > end_date:
                return JsonResponse(
                    {'status': 'error', 'message': 'Дата начала не может быть позже окончания ремонта.'}, status=400)

            VehicleMaintenance.objects.create(
                vehicle=vehicle, start_date=start_date, end_date=end_date, reason=reason
            )
            log_action(request.user, "ТО", f"Добавлен ремонт для {vehicle.name}")
            return JsonResponse({'status': 'success', 'message': 'Ремонт успешно зарегистрирован.'})

        except ValueError:
            return JsonResponse({'status': 'error', 'message': 'Неверный формат дат.'}, status=400)
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    return JsonResponse({'status': 'error', 'message': 'Недопустимый тип запроса.'}, status=400)


# ==========================================
# 6. ТРАНСПОРТНЫЙ ОТДЕЛ: ВОДИТЕЛИ И ГРАФИКИ
# ==========================================

@login_required
def transport_drivers_view(request):
    if request.user.role not in ['transport', 'admin']: raise PermissionDenied

    if request.method == 'POST':
        form = DriverCreateForm(request.POST)
        if form.is_valid():
            driver = form.save()  # email сохраняется по умолчанию из формы
            log_action(request.user, "Кадры", f"Нанят водитель {driver.name}")
            return redirect('transport_drivers')

    date_str = request.GET.get('date', timezone.now().date().isoformat())
    selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    drivers = Driver.objects.all().order_by('name')

    active_count = 0
    for d in drivers:
        # Проверяем отсутствие
        absence = DriverAbsence.objects.filter(driver=d, start_date__lte=selected_date,
                                               end_date__gte=selected_date).first()
        if absence:
            d.is_absent_today = True
            d.absence_reason = absence.get_absence_type_display()
        else:
            # Проверяем наличие смены
            has_shift = DriverSchedule.objects.filter(driver=d, date=selected_date, is_work_day=True).exists()
            d.is_absent_today = not has_shift
            if has_shift: active_count += 1  # Если есть смена и нет отсутствия, водитель активен

    pct_coverage = int((active_count / drivers.count() * 100)) if drivers.exists() else 0

    context = {
        'drivers': drivers,
        'selected_date': selected_date,
        'active_drivers_count': active_count,
        'pct_coverage': pct_coverage,
        'offset_coverage': 282.6 - (282.6 * pct_coverage / 100),  # Для круговой диаграммы
        'form': DriverCreateForm(),
        'prev_month_date': (date(selected_date.year, selected_date.month, 1) - timedelta(days=1)).isoformat(),
        'next_month_date': (date(selected_date.year, selected_date.month, 1) + timedelta(days=32)).replace(
            day=1).isoformat(),
    }
    return render(request, 'main/transport_drivers.html', context)


@require_POST
@csrf_protect
def add_driver_absence_ajax(request):
    """AJAX-обработчик для регистрации больничных/отпусков"""
    try:
        data = json.loads(request.body)
        driver_id = data.get('driver_id')
        start_date = datetime.strptime(data.get('start_date'), '%Y-%m-%d').date()
        end_date = datetime.strptime(data.get('end_date'), '%Y-%m-%d').date()
        absence_type = data.get('absence_type')

        driver = get_object_or_404(Driver, id=driver_id)

        DriverAbsence.objects.create(
            driver=driver,
            start_date=start_date,
            end_date=end_date,
            absence_type=absence_type
        )
        log_action(request.user, "График персонала", f"Добавлена запись об отсутствии для {driver.name}")
        # После добавления отсутствия, нужно перепланировать все затронутые даты
        dates_to_replan = []
        curr = start_date
        while curr <= end_date:
            dates_to_replan.append(curr)
            curr += timedelta(days=1)
        auto_plan_for_dates(dates_to_replan)  # Запускаем перепланирование
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


@login_required
@require_POST
def toggle_driver_shift_ajax(request):
    """AJAX для переключения рабочей смены водителя на дату"""
    data = json.loads(request.body)
    date_str = data.get('date')
    driver_id = data.get('driver_id')
    is_work_day = data.get('is_work_day')

    schedule_entry, created = DriverSchedule.objects.update_or_create(
        driver_id=driver_id,
        date=date_str,
        defaults={
            'is_work_day': is_work_day,
            'start_time': data.get('start_time', '08:00'),  # Дефолтные значения
            'end_time': data.get('end_time', '17:00')  # Дефолтные значения
        }
    )
    log_action(request.user, "График персонала",
               f"Смена {schedule_entry.driver.name} на {date_str} {'установлена' if is_work_day else 'отменена'}")
    auto_plan_for_dates([date_str])  # Пересчитываем план дня при изменении смены
    return JsonResponse({'status': 'success'})


@require_POST
def update_driver_ajax(request, pk):
    """Обновление данных водителя (ФИО, телефон, email)"""
    driver = get_object_or_404(Driver, pk=pk)
    data = json.loads(request.body)
    try:
        driver.name = data.get('name', driver.name)
        driver.phone = data.get('phone', driver.phone)
        driver.email = data.get('email', driver.email)
        driver.save()
        log_action(request.user, "Кадры", f"Изменен профиль: {driver.name}")
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


# ==========================================
# 7. ГРАФИК РЕЙСОВ И СТАТУСЫ ЗАКАЗОВ
# ==========================================

@login_required
def transport_schedule_view(request):
    today = timezone.now().date()
    # Анотируем планы количеством заказов и фильтруем только те, где заказы > 0
    today_plans = DeliveryPlan.objects.annotate(
        items_count=Count('planitem')
    ).filter(
        date=today,
        status=DeliveryPlan.Status.APPROVED,
        items_count__gt=0
    ).select_related('vehicle', 'driver').prefetch_related('planitem_set__order')

    return render(request, 'main/transport_schedule.html', {
        'today_plans': today_plans,
        'today': today
    })


@login_required
def transport_schedule_api(request, date_str):
    """API для получения списка рейсов на определенную дату (для графика рейсов)"""
    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()

        plans = DeliveryPlan.objects.annotate(
            items_count=Count('planitem')
        ).filter(
            date=target_date,
            status=DeliveryPlan.Status.APPROVED,
            items_count__gt=0
        ).select_related('vehicle', 'driver').prefetch_related('planitem_set__order')

        html_content = render_to_string('main/schedule_plans_list.html', {
            'today_plans': plans,
            'selected_date': target_date  # Передаем дату для корректного отображения в шаблоне
        }, request=request)

        return JsonResponse({'html': html_content})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def transport_calendar_events_api(request):
    """API специально для страницы графика рейсов: только отметки о наличии утвержденных планов"""
    start_str = request.GET.get('start', '').split('T')[0]
    end_str = request.GET.get('end', '').split('T')[0]

    if not (start_str and end_str): return JsonResponse([], safe=False)

    start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
    end_date = datetime.strptime(end_str, '%Y-%m-%d').date()

    # Ищем даты, на которые есть утвержденные планы
    active_dates = DeliveryPlan.objects.filter(
        date__range=[start_date, end_date],
        status=DeliveryPlan.Status.APPROVED
    ).values_list('date', flat=True).distinct()

    events = []
    for date in active_dates:
        events.append({
            'title': '📌',  # Иконка, указывающая на наличие рейсов
            'start': date.isoformat(),
            'allDay': True,
            'display': 'block',
            'backgroundColor': 'transparent',  # Прозрачный фон
            'borderColor': 'transparent',  # Без границ
            'textColor': '#000',  # Цвет иконки
            'classNames': ['pin-event']  # Специальный класс для CSS (если нужен)
        })
    return JsonResponse(events, safe=False)


# ==========================================
# 8. АДМИНИСТРИРОВАНИЕ И ЛОГИ
# ==========================================

@staff_member_required
def admin_users_list(request):
    if request.user.role != 'admin': raise PermissionDenied
    return render(request, 'main/admin_users.html', {'users': CustomUser.objects.all().order_by('-id')})


@staff_member_required
@require_POST
def update_user_ajax(request, pk):
    """Универсальное обновление полей пользователя через AJAX"""
    user = get_object_or_404(CustomUser, pk=pk)
    data = json.loads(request.body)

    field = data.get('field')
    value = data.get('value')

    try:
        if field == 'username':
            user.username = value
        elif field == 'email':
            user.email = value
        elif field == 'role':
            user.role = value
        elif field == 'is_active':
            user.is_active = (value == 'true' or value is True)
        elif field == 'is_staff':
            user.is_staff = (value == 'true' or value is True)

        user.save()
        log_action(request.user, "Изменение персонала", f"Изменено поле '{field}' у пользователя {user.username}")
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


@staff_member_required
@require_POST
def change_password_ajax(request, pk):
    """Смена пароля пользователя через AJAX"""
    user = get_object_or_404(CustomUser, pk=pk)
    data = json.loads(request.body)
    new_password = data.get('password')

    if new_password:
        user.set_password(new_password)
        user.save()
        log_action(request.user, "Смена пароля", f"Пароль пользователя {user.username} изменен")
        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error', 'message': 'Пароль не может быть пустым'}, status=400)


@staff_member_required
@require_POST
def fire_user_ajax(request, pk):
    """Удаление (увольнение) сотрудника"""
    user = get_object_or_404(CustomUser, pk=pk)
    if user.is_superuser:
        return JsonResponse({'status': 'error', 'message': 'Нельзя уволить суперпользователя'}, status=400)
    user.delete()
    log_action(request.user, "Увольнение", f"Сотрудник {user} был удален из системы")
    return JsonResponse({'status': 'success'})


@staff_member_required
def event_log_view(request):
    if request.user.role != 'admin': raise PermissionDenied
    context = {
        'users': CustomUser.objects.annotate(log_count=Count('actionlog')).order_by('-log_count'),
        'total_actions': ActionLog.objects.count(),
        'today_actions': ActionLog.objects.filter(timestamp__date=timezone.now().date()).count(),
        'top_user': CustomUser.objects.annotate(log_count=Count('actionlog')).order_by('-log_count').first(),
        'logs': ActionLog.objects.all().order_by('-timestamp')[:100]  # Последние 100 записей
    }
    return render(request, 'main/admin_log.html', context)


@staff_member_required
def user_history_api(request, user_id):
    """Возвращает HTML историю конкретного пользователя для модалки"""
    logs = ActionLog.objects.filter(user_id=user_id).order_by('-timestamp')
    html = render_to_string('main/user_history_fragment.html', {'logs': logs})
    return JsonResponse({'html': html})


@login_required
def get_driver_data_api(request, pk):
    """Возвращает текущие смены и отсутствия водителя на 30 дней"""
    driver = get_object_or_404(Driver, pk=pk)
    today = date.today()
    end_date = today + timedelta(days=30)

    # Получаем смены
    schedules = DriverSchedule.objects.filter(driver=driver, date__range=[today, end_date])
    sched_dict = {s.date.isoformat(): {'is_work': s.is_work_day, 'start': s.start_time.strftime('%H:%M'),
                                       'end': s.end_time.strftime('%H:%M')} for s in schedules}

    # Получаем отсутствия
    absences = DriverAbsence.objects.filter(driver=driver, end_date__gte=today).order_by('start_date')
    abs_list = []
    for a in absences:
        abs_list.append({
            'id': a.id,
            'type': a.get_absence_type_display(),
            'start': a.start_date.strftime('%d.%m.%Y'),
            'end': a.end_date.strftime('%d.%m.%Y')
        })

    return JsonResponse({
        'shifts': sched_dict,
        'absences': abs_list
    })
