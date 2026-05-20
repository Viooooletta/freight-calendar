from django.db import models
from django.contrib.auth.models import AbstractUser

# 1. ПОЛЬЗОВАТЕЛИ
class CustomUser(AbstractUser):
    LOGISTICS = 'logistics'
    TRANSPORT = 'transport'
    ADMIN = 'admin'

    ROLE_CHOICES = [
        (LOGISTICS, 'Логистический отдел'),
        (TRANSPORT, 'Транспортный отдел'),
        (ADMIN, 'Администратор')
    ]

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default=LOGISTICS,
        verbose_name="Роль"
    )

    is_active = models.BooleanField(
        default=False,
        verbose_name="Активен (подтвержден)"
    )
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True, verbose_name="Фото профиля")

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"


# 2. ТРАНСПОРТ
class Vehicle(models.Model):
    name = models.CharField(max_length=100, verbose_name="Название/Номер авто")
    capacity_volume = models.FloatField(verbose_name="Грузоподъемность по объему (м³)", default=0.0)
    capacity_weight = models.FloatField(verbose_name="Грузоподъемность по весу (кг)", default=0.0)

    class Meta:
        verbose_name = 'Транспортное средство'
        verbose_name_plural = 'Транспортные средства'

    def __str__(self):
        return f"{self.name} ({self.capacity_volume} м³ | {self.capacity_weight} кг)"

    def is_on_maintenance(self, date):
        """Проверка ремонта на конкретную дату"""
        return self.vehiclemaintenance_set.filter(start_date__lte=date, end_date__gte=date).exists()


# 3. ВОДИТЕЛИ
class Driver(models.Model):
    name = models.CharField(max_length=100, verbose_name="ФИО Водителя")
    phone = models.CharField(max_length=20, verbose_name="Телефон")
    email = models.EmailField(verbose_name="Email", null=True, blank=True)
    photo = models.ImageField(upload_to='drivers/', null=True, blank=True, verbose_name="Фото")
    assigned_vehicle = models.ForeignKey(
        'Vehicle', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Предпочтительное ТС"
    )

    class Meta:
        verbose_name = 'Водитель'
        verbose_name_plural = 'Водители'

    def __str__(self):
        return self.name

    def is_available(self, date):
        """Проверка доступности: есть смена и нет больничного/отпуска"""
        has_shift = DriverSchedule.objects.filter(driver=self, date=date, is_work_day=True).exists()
        has_absence = DriverAbsence.objects.filter(driver=self, start_date__lte=date, end_date__gte=date).exists()
        return has_shift and not has_absence


class DriverSchedule(models.Model):
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, verbose_name="Водитель")
    date = models.DateField(verbose_name="Дата")
    is_work_day = models.BooleanField(default=True, verbose_name="Рабочий день")
    start_time = models.TimeField(default="08:00", verbose_name="Начало смены")
    end_time = models.TimeField(default="17:00", verbose_name="Конец смены")

    class Meta:
        unique_together = ('driver', 'date') # Защита от дублей смен
        verbose_name = 'Смена водителя'
        verbose_name_plural = 'Смены водителей'


# 4. ЗАКАЗЫ (Сердце ОКП)
class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Ожидает'
        PLANNED = 'planned', 'Запланирован'
        SHIPPED = 'shipped', 'В пути'
        DELIVERED = 'delivered', 'Доставлен'
        CANCELED = 'canceled', 'Отменен'

    class DeliveryType(models.TextChoices):
        URGENT = 'urgent', 'Срочно (в указанный день)'
        PERIODIC = 'periodic', 'Периодическая'

    class Frequency(models.TextChoices):
        NONE = 'none', 'Разово'
        WEEKLY = 'weekly', 'Каждую неделю'
        BIWEEKLY = 'biweekly', 'Каждые 2 недели'
        TRIWEEKLY = 'triweekly', 'Каждые 3 недели'
        MONTHLY = 'monthly', 'Раз в месяц'
        HALFYEARLY = 'half_yearly', 'Раз в полгода'

    address = models.CharField(max_length=255, verbose_name="Адрес доставки")
    volume = models.FloatField(verbose_name="Объем (м³)", default=0.0)
    weight = models.FloatField(verbose_name="Вес (кг)", default=0.0)
    delivery_type = models.CharField(max_length=10, choices=DeliveryType.choices, default=DeliveryType.URGENT)
    frequency = models.CharField(max_length=15, choices=Frequency.choices, default=Frequency.NONE)
    delivery_data = models.DateField(verbose_name="Дата доставки")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)

    class Meta:
        verbose_name = 'Заказ'
        verbose_name_plural = 'Заказы'
        # Добавляем индекс для быстрого поиска по дате (важно для ОКП)
        indexes = [models.Index(fields=['delivery_data', 'status'])]

    def __str__(self):
        return f"№{self.id} | {self.address} ({self.delivery_data})"


# 5. ПЛАНИРОВАНИЕ
class DeliveryPlan(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Черновик'
        APPROVED = 'approved', 'Утвержден'
        COMPLETED = 'completed', 'Выполнен'

    date = models.DateField(verbose_name="Дата плана")
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, verbose_name="Транспорт")
    driver = models.ForeignKey(Driver, on_delete=models.SET_NULL, null=True, verbose_name="Водитель")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)

    class Meta:
        verbose_name = 'План доставки (Рейс)'
        verbose_name_plural = 'Планы доставки (Рейсы)'

    def __str__(self):
        return f"Рейс {self.date}: {self.vehicle.name} ({self.get_status_display()})"


class PlanItem(models.Model):
    plan = models.ForeignKey(DeliveryPlan, on_delete=models.CASCADE)
    order = models.ForeignKey(Order, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('plan', 'order') # Один заказ не может быть в одном рейсе дважды


# 6. ВСПОМОГАТЕЛЬНЫЕ МОДЕЛИ
class VehicleMaintenance(models.Model):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, verbose_name="Транспорт")
    start_date = models.DateField(verbose_name="Начало ТО")
    end_date = models.DateField(verbose_name="Конец ТО")
    reason = models.CharField(max_length=255, verbose_name="Причина", default="Техническое обслуживание")

    class Meta:
        verbose_name = 'Ремонт/ТО'
        verbose_name_plural = 'Ремонты и ТО'

    # ДОБАВЬ ВОТ ЭТО:
    @property
    def duration_days(self):
        delta = self.end_date - self.start_date
        return delta.days + 1  # +1 чтобы учитывался и день начала, и день конца


class DriverAbsence(models.Model):
    class Type(models.TextChoices):
        SICK = 'sick', 'Больничный'
        VACATION = 'vacation', 'Отпуск'
        DAY_OFF = 'day_off', 'Отгул'

    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, verbose_name="Водитель")
    absence_type = models.CharField(max_length=10, choices=Type.choices, verbose_name="Причина")
    start_date = models.DateField(verbose_name="С")
    end_date = models.DateField(verbose_name="По")

    class Meta:
        verbose_name = 'Отсутствие водителя'
        verbose_name_plural = 'Отсутствие водителей'


class ActionLog(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, verbose_name="Пользователь")
    action_type = models.CharField(max_length=100, verbose_name="Действие")
    description = models.TextField(verbose_name="Описание")
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="Время")

    class Meta:
        verbose_name = 'Лог действия'
        verbose_name_plural = 'Журнал действий'