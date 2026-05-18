from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.text import slugify


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Ожидает'
        PLANNED = 'planned', 'Запланирован'
        SHIPPED = 'shipped', 'В пути'
        DELIVERED = 'delivered', 'Доставлен'
        CANCELED = 'canceled', 'Отменен'

    # Новые перечисления
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

    # Поля для новой логики
    delivery_type = models.CharField(
        max_length=10,
        choices=DeliveryType.choices,
        default=DeliveryType.URGENT,
        verbose_name="Тип доставки"
    )
    frequency = models.CharField(
        max_length=15,
        choices=Frequency.choices,
        default=Frequency.NONE,
        verbose_name="Периодичность"
    )

    delivery_data = models.DateField(verbose_name="Дата доставки / Старт периода")

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="Статус заказа"
    )

    class Meta:
        verbose_name = 'Заказ'
        verbose_name_plural = 'Заказы'

    def __str__(self):
        return f"Заказ №{self.id} — {self.address}"

class Vehicle(models.Model):
    class Meta:
        verbose_name = 'Транспортное средство'
        verbose_name_plural = 'Транспортные средства'

    name = models.CharField(max_length=100, verbose_name="Название/Номер авто")
    capacity_volume = models.FloatField(verbose_name="Грузоподъемность по объему (м³)", default=0.0)
    capacity_weight = models.FloatField(verbose_name="Грузоподъемность по весу (кг)", default=0.0)

    def __str__(self):
        return f"{self.name} ({self.capacity_volume} м³ | {self.capacity_weight} кг)"

    def is_on_maintenance(self, date):
        """Проверяет, находится ли машина в ремонте на указанную дату"""
        return self.vehiclemaintenance_set.filter(start_date__lte=date, end_date__gte=date).exists()


class DeliveryPlan(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Черновик'
        APPROVED = 'approved', 'Утвержден'
        COMPLETED = 'completed', 'Выполнен'

    class Meta:
        verbose_name = 'План доставки'
        verbose_name_plural = 'Планы доставки'

    date = models.DateField(verbose_name="Дата плана")
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, verbose_name="Транспорт")
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name="Статус плана"
    )

    def __str__(self):
        # Отобразит, например: План доставки от 12.05.2026 (КАМАЗ АА 7777)
        return f"План доставки от {self.date.strftime('%d.%m.%Y')} ({self.vehicle.name})"


class PlanItem(models.Model):
    class Meta:
        verbose_name = 'Пункт плана'
        verbose_name_plural = 'Пункты плана'

    plan = models.ForeignKey(DeliveryPlan, on_delete=models.CASCADE)
    order = models.ForeignKey(Order, on_delete=models.CASCADE)

    def __str__(self):
        # Отобразит логичную связь, например: Доставка в Заказ №21 (План: 12.05.2026)
        return f"Пункт плана: {self.order} (План: {self.plan.date.strftime('%d.%m.%Y')})"


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

    def __str__(self):
        # Отобразит логин пользователя и его роль (чтобы сразу видеть, кто работает)
        role_display = dict(self.ROLE_CHOICES).get(self.role, self.role)
        return f"{self.username} — {role_display}"

class VehicleMaintenance(models.Model):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, verbose_name="Транспорт")
    start_date = models.DateField(verbose_name="Дата начала ремонта/ТО")
    end_date = models.DateField(verbose_name="Дата окончания")
    reason = models.CharField(max_length=255, verbose_name="Причина", default="Техническое обслуживание")