"""Korean → Arabic translation for auction-feed extras (usage type + the
auctioneer's inspection/defect notes).

The Lotte/AutoHub feeds deliver `use` and `notes` in Korean. `use` is a small
enum; `notes` is a controlled defect vocabulary (comma-separated terms). We
translate to Arabic (the site's primary language) and pass through any term not
yet in the dictionary, so coverage degrades gracefully — extend over time.
"""

# prior usage  (렌트 / 자가 / 리스 / 업무 …)
USAGE_KO = {
    "렌트": "تأجير",
    "자가": "خاص",
    "리스": "ليس (تأجير تمويلي)",
    "금융리스(일반계산서발행)": "ليس تمويلي",
    "금융리스": "ليس تمويلي",
    "업무": "أعمال",
    "관용": "حكومي",
    "영업용": "تجاري",
    "직수입": "استيراد مباشر",
}

# inspection / defect terms (component + condition)
NOTE_TERMS = {
    "PS불량": "عطل في المقود (الباور)",
    "실내내장재불량": "عيب في التجهيزات الداخلية",
    "시트불량": "عيب في المقاعد",
    "엔진오일누유": "تسريب زيت المحرك",
    "엔진오일누유심함": "تسريب شديد لزيت المحرك",
    "하체이음": "صوت في الهيكل السفلي",
    "언더커버불량": "عيب في الغطاء السفلي",
    "언더커버/로워패널불량": "عيب الغطاء السفلي/اللوح السفلي",
    "엔진이음": "صوت في المحرك",
    "트렁크내장재불량": "عيب في تجهيزات الصندوق",
    "미션불량": "عيب في ناقل الحركة",
    "하체꺾임": "انثناء في الهيكل السفلي",
    "엔진부조": "تذبذب/اهتزاز المحرك",
    "스텝몰딩불량": "عيب في حلية العتبة",
    "몰딩불량": "عيب في الحلية",
    "터보불량": "عيب في التيربو",
    "조인트불량": "عيب في المفصل (الجوية)",
    "냉각수누수": "تسريب ماء التبريد",
    "적재함불량": "عيب في صندوق التحميل",
    "에어컨불량": "عطل المكيف",
    "타이어불량": "عيب في الإطارات",
    "미션오일누유": "تسريب زيت ناقل الحركة",
    "렌트이력": "سجل تأجير سابق",
    "TPMS경고등점등": "إضاءة لمبة ضغط الإطارات (TPMS)",
    "공조장치불량": "عطل نظام التكييف",
    "침수확인점검요": "يلزم فحص الغمر بالماء",
    "공사현장차량점검요": "مركبة موقع إنشاءات - يلزم الفحص",
    "차체/하체부식": "صدأ في الهيكل/الهيكل السفلي",
    "엔진체크등점등": "إضاءة لمبة فحص المحرك",
    "실내/하체/엔진룸 흙먼지오염": "اتساخ بالغبار (المقصورة/الهيكل/حجرة المحرك)",
    "제동불량": "عيب في الفرامل",
    "실차확인요/클레임불가": "يلزم المعاينة على الطبيعة/لا تُقبل المطالبات",
    "전기장치불량": "عطل في الأجهزة الكهربائية",
    "충전장치/배터리불량": "عطل نظام الشحن/البطارية",
    "배출가스/매연발생": "انبعاث عوادم/دخان",
    "차대번호부식": "صدأ في رقم الشاسيه",
    "외판불량": "عيب في الصاج الخارجي",
    "도장불량": "عيب في الطلاء",
}


def translate_usage(value):
    v = (value or "").strip()
    return USAGE_KO.get(v, v)


def translate_notes(value):
    """Comma-separated Korean defect terms → ' • '-joined Arabic phrases."""
    if not value:
        return ""
    out = []
    for raw in str(value).replace("，", ",").split(","):
        t = raw.strip()
        if not t:
            continue
        out.append(NOTE_TERMS.get(t, t))   # pass through unknowns
    return " • ".join(out)
