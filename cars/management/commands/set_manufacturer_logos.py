from django.core.management.base import BaseCommand
from cars.models import Manufacturer


MANUFACTURER_LOGOS = {
    "Hyundai": "https://carstat.dev/images/brands/hyundai.svg",
    "Kia": "https://carstat.dev/images/brands/kia.svg",
    "Mercedes-Benz": "https://carstat.dev/images/brands/mercedes.svg",
    "BMW": "https://carstat.dev/images/brands/bmw.svg",
    "Genesis": "https://carstat.dev/images/brands/genesis.svg",
    "Audi": "https://carstat.dev/images/brands/audi.svg",
    "Volkswagen": "https://carstat.dev/images/brands/volkswagen.svg",
    "Porsche": "https://carstat.dev/images/brands/porche.svg",
    "Land Rover": "https://carstat.dev/images/brands/land-rover.svg",
    "Jeep": "https://carstat.dev/images/brands/jeep.svg",
    "Ford": "https://carstat.dev/images/brands/ford.svg",
    "Volvo": "https://carstat.dev/images/brands/volvo.svg",
    "Tesla": "https://carstat.dev/images/brands/tesla.svg",
    "Lexus": "https://carstat.dev/images/brands/lexus.svg",
    "Toyota": "https://carstat.dev/images/brands/toyota.svg",
    "Lincoln": "https://carstat.dev/images/brands/lincoln.svg",
    "Honda": "https://carstat.dev/images/brands/honda.svg",
    "Jaguar": "https://carstat.dev/images/brands/jaguar.svg",
    "Peugeot": "https://carstat.dev/images/brands/peugeot.svg",
    "Maserati": "https://carstat.dev/images/brands/maserati.svg",
    "Cadillac": "https://carstat.dev/images/brands/cadillac.svg",
    "Infiniti": "https://carstat.dev/images/brands/infiniti.svg",
    "Nissan": "https://carstat.dev/images/brands/nissan.svg",
    "Bentley": "https://carstat.dev/images/brands/bentley.svg",
    "Ferrari": "https://carstat.dev/images/brands/ferrari.svg",
    "Rolls-Royce": "https://carstat.dev/images/brands/rolls-royce.svg",
    "Chevrolet": "https://carstat.dev/images/brands/chevrolet.svg",
    "Lamborghini": "https://carstat.dev/images/brands/lamborghini.svg",
    "Chrysler": "https://carstat.dev/images/brands/chrysler.svg",
    "Fiat": "https://carstat.dev/images/brands/fiat.svg",
    "Polestar": "https://carstat.dev/images/brands/Polestar.svg",
    "Dodge": "https://carstat.dev/images/brands/dodge.svg",
    "Suzuki": "https://carstat.dev/images/brands/suzuki.svg",
    "Smart": "https://carstat.dev/images/brands/smart.png",
    "GMC": "https://carstat.dev/images/brands/gmc.svg",
    "Hummer": "https://carstat.dev/images/brands/Hummer.svg",
    "Daihatsu": "https://carstat.dev/images/brands/daihatsu.png",
    "Lotus": "https://carstat.dev/images/brands/Lotus.svg",
    "BYD": "https://carstat.dev/images/brands/byd.svg",
    "Saab": "https://carstat.dev/images/brands/Saab.svg",
    "Mazda": "https://carstat.dev/images/brands/mazda.svg",
    "Mitsubishi": "https://carstat.dev/images/brands/mitsubishi.svg",
    "Geely": "https://carstat.dev/images/brands/Geely.svg",
    "Subaru": "https://carstat.dev/images/brands/subaru.svg",
    "Maybach": "https://carstat.dev/images/brands/Maybach.svg",
    "Mitsuoka": "https://carstat.dev/images/brands/Mitsuoka.svg",
    "Acura": "https://carstat.dev/images/brands/acura.svg",
    "Alfa Romeo": "https://carstat.dev/images/brands/alfa-romeo.svg",
    "Scion": "https://carstat.dev/images/brands/Scion.svg",
    "Mercury": "https://carstat.dev/images/brands/Mercury.svg",
    "Renault": "https://carstat.dev/images/brands/renault.svg",
}


class Command(BaseCommand):
    help = "Set manufacturer logos from predefined mapping"

    def handle(self, *args, **options):
        updated = 0
        not_found = []

        for name, logo_url in MANUFACTURER_LOGOS.items():
            # Try exact match first, then case-insensitive
            qs = Manufacturer.objects.filter(name=name)
            if not qs.exists():
                qs = Manufacturer.objects.filter(name__iexact=name)
            if not qs.exists():
                # Try partial match (e.g. "Mercedes-Benz" matching "Mercedes" or "Mercedes Benz")
                qs = Manufacturer.objects.filter(name__icontains=name.split("-")[0].split(" ")[0])

            if qs.exists():
                count = qs.update(logo=logo_url)
                updated += count
                self.stdout.write(f"  ✓ {name} → {count} record(s) updated")
            else:
                not_found.append(name)

        self.stdout.write(self.style.SUCCESS(f"\nDone! Updated {updated} manufacturers."))
        if not_found:
            self.stdout.write(self.style.WARNING(f"Not found in DB: {', '.join(not_found)}"))
