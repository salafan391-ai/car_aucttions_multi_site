from django.core.management.base import BaseCommand
from cars.models import Manufacturer


ARABIC_NAMES = {
    "Hyundai": "هيونداي",
    "Kia": "كيا",
    "Mercedes-Benz": "مرسيدس بنز",
    "BMW": "بي إم دبليو",
    "Genesis": "جينيسيس",
    "ChevroletGMDaewoo": "شيفروليه جي إم دايو",
    "KG_Mobility_Ssangyong": "كي جي موبيليتي سانغ يونغ",
    "Renault-KoreaSamsung": "رينو كوريا سامسونج",
    "Audi": "أودي",
    "Volkswagen": "فولكس واجن",
    "Porsche": "بورشه",
    "Mini": "ميني",
    "Land Rover": "لاند روفر",
    "Jeep": "جيب",
    "Ford": "فورد",
    "Volvo": "فولفو",
    "Tesla": "تسلا",
    "Lexus": "لكزس",
    "Toyota": "تويوتا",
    "Lincoln": "لينكولن",
    "Honda": "هوندا",
    "Jaguar": "جاكوار",
    "Peugeot": "بيجو",
    "Maserati": "مازيراتي",
    "Cadillac": "كاديلاك",
    "Infiniti": "إنفينيتي",
    "Nissan": "نيسان",
    "Bentley": "بنتلي",
    "Ferrari": "فيراري",
    "Rolls-Royce": "رولز رويس",
    "Chevrolet": "شيفروليه",
    "Lamborghini": "لامبورغيني",
    "Citroen-DS": "ستروين دي إس",
    "Chrysler": "كرايسلر",
    "Fiat": "فيات",
    "Polestar": "بولستار",
    "Dodge": "دودج",
    "Others": "أخرى",
    "Suzuki": "سوزوكي",
    "Mclaren": "ماكلارين",
    "Smart": "سمارت",
    "GMC": "جي إم سي",
    "Astonmartin": "أستون مارتن",
    "Hummer": "هامر",
    "DFSK": "دي إف إس كي",
    "Daihatsu": "دايهاتسو",
    "Lotus": "لوتس",
    "Xin yuan": "شين يوان",
    "BYD": "بي واي دي",
    "etc": "أخرى",
    "Saab": "ساب",
    "Mazda": "مازدا",
    "Mitsubishi": "ميتسوبيشي",
    "Geely": "جيلي",
    "Subaru": "سوبارو",
    "Maybach": "مايباخ",
    "Baic Yinxiang": "بايك يين شيانغ",
    "Ineos": "إنيوس",
    "Mitsuoka": "ميتسوكا",
    "Acura": "أكيورا",
    "Alfa Romeo": "ألفا روميو",
    "Scion": "سايون",
    "Mercury": "ميركوري",
    "Renault": "رينو",
}


class Command(BaseCommand):
    help = "Set Arabic names for manufacturers"

    def handle(self, *args, **options):
        updated = 0
        not_found = []

        for name, name_ar in ARABIC_NAMES.items():
            qs = Manufacturer.objects.filter(name=name)
            if not qs.exists():
                qs = Manufacturer.objects.filter(name__iexact=name)
            if not qs.exists():
                qs = Manufacturer.objects.filter(name__icontains=name.split("-")[0].split(" ")[0])

            if qs.exists():
                count = qs.update(name_ar=name_ar)
                updated += count
                self.stdout.write(f"  ✓ {name} → {name_ar}")
            else:
                not_found.append(name)

        self.stdout.write(self.style.SUCCESS(f"\nDone! Updated {updated} manufacturers."))
        if not_found:
            self.stdout.write(self.style.WARNING(f"Not found in DB: {', '.join(not_found)}"))
