"""Fill Arabic names for makes/models that currently fall back to English.

Only writes rows whose name_ar is empty, so hand edits are never clobbered.
The daily import uses get_or_create keyed on name (defaults exclude name_ar),
so these values survive re-imports.
"""
from django.core.management.base import BaseCommand
from django.db.models import Q

from cars.models import CarModel, Manufacturer

MAKES = {
    "kg mobility (ssangyong)": "كي جي موبيليتي (سانغ يونغ)",
    "renault samsung": "رينو سامسونج",
    "tata daewoo": "تاتا دايو",
    "daewoo bus": "دايو باص",
    "daewoo": "دايو",
    "camping trailer": "مقطورة تخييم",
    "isuzu": "إيسوزو",
    "mohave": "موهافي",
    "man truck": "مان",
    "scania": "سكانيا",
    "iveco": "إيفيكو",
    "citroën": "ستروين",
    "citroen": "ستروين",
    "sunlong": "صن لونج",
    "ds": "دي إس",
    "korea": "كوريا",
    "suzoki": "سوزوكي",
    "shin yuan (jeis mobility)": "شين يوان",
    "myve (kst)": "مايف",
    "other": "أخرى",
    "unknown": "غير معروف",
    "no manufacturer": "غير محدد",
}

MODELS = {
    # Mercedes-Benz
    "e-class": "الفئة E", "s-class": "الفئة S", "c-class": "الفئة C",
    "a-class": "الفئة A", "b-class": "الفئة B", "g-class": "الفئة G",
    "gle-class": "الفئة GLE", "glc-class": "الفئة GLC", "glb-class": "الفئة GLB",
    "gla-class": "الفئة GLA", "gls-class": "الفئة GLS", "cls-class": "الفئة CLS",
    "cla-class": "الفئة CLA", "cle-class": "الفئة CLE",
    "eqe": "EQE", "eqs": "EQS",
    # BMW
    "1-series": "الفئة الأولى", "2-series": "الفئة الثانية", "3-series": "الفئة الثالثة",
    "4-series": "الفئة الرابعة", "5-series": "الفئة الخامسة", "6-series": "الفئة السادسة",
    "7-series": "الفئة السابعة", "m5": "إم 5", "x2 (f39)": "إكس 2", "i4": "آي 4",
    # Audi
    "a3": "إيه 3", "a4": "إيه 4", "a5": "إيه 5", "a6": "إيه 6", "a7": "إيه 7", "a8": "إيه 8",
    "q3": "كيو 3", "q5": "كيو 5", "q7": "كيو 7", "q8": "كيو 8", "sq5": "إس كيو 5",
    "e-tron": "إي-ترون",
    # Korean
    "tiboli": "تيفولي", "the new bongo iii": "بونغو 3 الجديد", "bongo iii": "بونغو 3",
    "sm3": "إس إم 3", "sm5": "إس إم 5", "sm6": "إس إم 6", "sm7": "إس إم 7",
    "qm3": "كيو إم 3", "qm5": "كيو إم 5", "eq900": "إي كيو 900",
    "ioniq5": "أيونيك 5", "ioniq6": "أيونيك 6",
    "mighty": "مايتي", "e-mighty": "إي مايتي", "mighty qt": "مايتي كيو تي",
    "mega truck": "ميجا ترك", "new county": "نيو كاونتي",
    "veracruz": "فيراكروز", "stonic": "ستونيك", "azera": "أزيرا",
    "avante ad": "أفانتي AD", "lf sonata": "سوناتا LF", "all-new grandeur": "جراندير الجديدة",
    "grand koleos": "جراند كوليوس", "alpheon": "ألفيون", "labo": "لابو",
    "musso": "موسو", "actyon": "أكتيون", "tasman": "تاسمان", "pavise": "بافيز",
    "cilo": "سيلو", "elantra": "إلنترا", "matiz": "ماتيز", "arkana": "أركانا",
    # Volvo
    "xc40": "إكس سي 40", "xc60": "إكس سي 60", "xc90": "إكس سي 90",
    "s60": "إس 60", "s90": "إس 90",
    # Lexus / Infiniti / Jaguar
    "es": "إي إس", "nx": "إن إكس", "ls": "إل إس", "q50": "كيو 50",
    "xe": "إكس إي", "xf": "إكس إف", "xj": "إكس جي",
    # Others
    "gran turismo": "جران توريزمو", "911": "911",
    "model 3": "موديل 3", "model y": "موديل Y",
    "colorado": "كولورادو", "jetta": "جيتا", "captiva": "كابتيفا",
    "traverse": "ترافيرس", "impala": "إمبالا", "cr-v": "سي آر-في",
    "cooper convertible": "كوبر مكشوفة", "defender": "ديفندر", "odyssey": "أوديسي",
    "compass": "كومباس", "cc": "سي سي", "rav4": "راف 4", "ct6": "سي تي 6",
    "master": "ماستر", "f150": "إف 150", "express van": "إكسبريس فان",
    "porte": "بورتيه", "2008": "2008", "3008": "3008", "5008": "5008",
    # ── second pass: the remaining tail on default (encar + auction) sites ──
    "mohave": "موهافي", "rx": "آر إكس", "ux": "يو إكس", "is": "آي إس",
    "polestar 2": "بولستار 2", "eqa": "EQA", "e300": "إي 300", "e250": "إي 250",
    "8-series": "الفئة الثامنة", "5 series": "الفئة الخامسة",
    "ev9": "إي في 9", "ev3": "إي في 3", "equinox": "إكوينوكس", "damas": "داماس",
    "corsair": "كورسير", "bongo iii truck": "بونغو 3 شاحنة", "sportage r": "سبورتاج R",
    "mkz": "إم كي زد", "mkx": "إم كي إكس", "mkc": "إم كي سي",
    "sl-class": "الفئة SL", "glk-class": "الفئة GLK", "slk-class": "الفئة SLK",
    "m-class": "الفئة M", "dossen": "دوسن", "508": "508", "308": "308", "500": "500",
    "v40": "في 40", "v90": "في 90", "s80": "إس 80", "g330": "جي 330",
    "beatle": "بيتل", "q4 e-tron": "كيو 4 إي-ترون", "nautilus": "نوتيلوس",
    "camaro": "كامارو", "bolt ev": "بولت EV", "all-new niro": "نيرو الجديدة",
    "niro ev": "نيرو EV", "bronco": "برونكو", "forte": "فورتي",
    "ram pick up": "رام بيك أب", "cts": "سي تي إس", "t-roc": "تي-روك",
    "elantra md": "إلنترا MD", "cube": "كيوب", "i7": "آي 7", "q30": "كيو 30",
    "juke": "جوك", "f-type": "إف-تايب", "e-pace": "إي-بيس", "e-county": "إي كاونتي",
    "x6m": "إكس 6 إم", "x5m": "إكس 5 إم", "x4m": "إكس 4 إم", "r8": "آر 8",
    "id.4": "آي دي 4", "maxen": "ماكسن", "q70": "كيو 70", "qx60": "كيو إكس 60",
    "ct200h": "سي تي 200 إتش", "crown": "كراون", "navigator": "نافيجيتور",
    "g": "جي", "m": "إم", "others": "أخرى",
    # Korean-script names (unreadable for Arabic visitors)
    "버스형": "حافلة", "카고트럭": "شاحنة بضائع", "마이티": "مايتي",
    "노부스 중형트럭": "نوفوس شاحنة متوسطة",
}


class Command(BaseCommand):
    help = "Fill empty name_ar on manufacturers and car models (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        blank = Q(name_ar__isnull=True) | Q(name_ar="")
        totals = {}
        for label, Model, mapping in (("manufacturers", Manufacturer, MAKES),
                                      ("models", CarModel, MODELS)):
            rows = hit = 0
            for name, ar in mapping.items():
                qs = Model.objects.filter(blank, name__iexact=name)
                n = qs.count()
                if not n:
                    continue
                hit += 1
                rows += n
                if not dry:
                    qs.update(name_ar=ar)
            totals[label] = (hit, rows)
            self.stdout.write(
                f"  {label}: {'would set' if dry else 'set'} {rows} row(s) "
                f"from {hit}/{len(mapping)} names")
        self.stdout.write(self.style.SUCCESS(
            "Dry run — nothing written." if dry else "Done."))
