from django.db import models
from django.contrib.auth.models import AbstractUser

class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Ожидает'
        PLANNED = 'planned', 'Запланирован'
        SHIPPED = 'shipped', 'В пути'
        DELIVERED = 'delivered', 'Доставлен'
        CANCELLED = 'cancelled', 'Отменен'
    class Meta:
        verbose_name = 'Заказ'
        verbose_name_plural = 'Заказы'

    address = models.CharField(max_length=255, verbose_name="Адрес доставки")
    volume = models.FloatField(verbose_name="Объем (м³)")
    delivery_data = models.DateField(verbose_name="Дата доставки")
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="Статус заказа"
    )

class Vehicle(models.Model):
    class Meta:
        verbose_name = 'Транспортное средство'
        verbose_name_plural = 'Транспортные средства'
    name = models.CharField(max_length=100, verbose_name="Название/Номер авто")
    capacity_volume = models.FloatField(verbose_name="Грузоподъемность по объему (м³)")
    capacity_weight = models.FloatField(verbose_name="Грузоподъемность по весу (кг)", default=0.0)

class DeliveryPlan(models.Model):
    class Meta:
        verbose_name = 'План доставки'
        verbose_name_plural = 'Планы доставки'
    date = models.DateField(verbose_name="Дата плана")
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, verbose_name="Транспорт")

class PlanItem(models.Model):
    class Meta:
        verbose_name = 'Пункт плана'
        verbose_name_plural = 'Пункты плана'
    plan = models.ForeignKey(DeliveryPlan, on_delete=models.CASCADE)
    order = models.ForeignKey(Order, on_delete=models.CASCADE)

class CustomUser(AbstractUser):
    # Константы для ролей
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

    # Настраиваем, чтобы при создании через форму пользователь был "неактивен"
    # Это и будет "запросом на регистрацию"
    is_active = models.BooleanField(
        default=False,
        verbose_name="Активен (подтвержден)"
    )

    def __str__(self):
        return self.username