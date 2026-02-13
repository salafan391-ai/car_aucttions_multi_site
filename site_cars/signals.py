from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.utils import timezone


@receiver(pre_save, sender='site_cars.SiteOrder')
def order_completed_handler(sender, instance, **kwargs):
    """When an order is marked as 'completed', mark the ApiCar as 'sold'
    and create a SiteSoldCar record."""
    if not instance.pk:
        return

    from .models import SiteOrder, SiteSoldCar

    try:
        old = SiteOrder.objects.get(pk=instance.pk)
    except SiteOrder.DoesNotExist:
        return

    if old.status != 'completed' and instance.status == 'completed':
        instance.completed_at = timezone.now()

        car = instance.car
        car.status = 'sold'
        car.save(update_fields=['status'])

        SiteSoldCar.objects.get_or_create(
            car=car,
            defaults={
                'buyer': instance.user,
                'sale_price': instance.offer_price,
                'original_price': car.price,
            },
        )
