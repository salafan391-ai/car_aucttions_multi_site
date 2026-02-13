from django.core.management.base import BaseCommand
from core.models import ApiCar
from django.db.models import Count


class Command(BaseCommand):
    help = 'Remove duplicate cars based on lot_number, keeping only the first occurrence'
    
    def handle(self, *args, **options):
        # Find all lot_numbers that have duplicates
        duplicates = (
            ApiCar.objects.values('lot_number')
            .annotate(count=Count('id'))
            .filter(count__gt=1)
        )
        
        total_duplicates = duplicates.count()
        self.stdout.write(f'Found {total_duplicates} lot_numbers with duplicates')
        
        deleted_count = 0
        for dup in duplicates:
            lot_number = dup['lot_number']
            # Get all cars with this lot_number, ordered by id (keep first, delete rest)
            cars = ApiCar.objects.filter(lot_number=lot_number).order_by('id')
            # Keep the first one, delete the rest by getting their IDs
            first_id = cars.first().id
            count = ApiCar.objects.filter(lot_number=lot_number).exclude(id=first_id).delete()[0]
            deleted_count += count
            if count > 0:
                self.stdout.write(f'Deleted {count} duplicate(s) for lot_number {lot_number}')
        
        self.stdout.write(self.style.SUCCESS(
            f'Cleanup complete: removed {deleted_count} duplicate cars'
        ))
        self.stdout.write(self.style.SUCCESS(
            f'Total unique cars now: {ApiCar.objects.count()}'
        ))
