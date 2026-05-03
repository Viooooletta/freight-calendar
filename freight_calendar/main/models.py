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

    class Meta:
        verbose_name = 'Заказ'
        verbose_name_plural = 'Заказы'

    address = models.CharField(max_length=255, verbose_name="Адрес доставки")
    volume = models.FloatField(verbose_name="Объем (м³)", default=0.0)
    weight = models.FloatField(verbose_name="Вес (кг)", default=0.0)
    delivery_data = models.DateField(verbose_name="Дата доставки")
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="Статус заказа"
    )

    def __str__(self):
        # Отобразит, например: Заказ №21 — ул. Ленина, 10 (12.05.2026)
        return f"Заказ №{self.id} — {self.address} ({self.delivery_data.strftime('%d.%m.%Y')})"


class Vehicle(models.Model):
    class Meta:
        verbose_name = 'Транспортное средство'
        verbose_name_plural = 'Транспортные средства'

    name = models.CharField(max_length=100, verbose_name="Название/Номер авто")
    capacity_volume = models.FloatField(verbose_name="Грузоподъемность по объему (м³)", default=0.0)
    capacity_weight = models.FloatField(verbose_name="Грузоподъемность по весу (кг)", default=0.0)

    def __str__(self):
        # Отобразит, например: КАМАЗ АА 7777 (25.0 м³ | 10000.0 кг)
        return f"{self.name} ({self.capacity_volume} м³ | {self.capacity_weight} кг)"


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