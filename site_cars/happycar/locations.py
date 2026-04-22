"""Korean administrative-location translations for HappyCar storage locations.

Locations come as `<province> <district>` (e.g. `전북 전주시`).
Covers all 17 provinces/metropolitan cities plus every district seen in the
scraped data (≈130 unique districts). Unknown districts fall back to the
Korean text plus a translated suffix (시/군/구).

The `translate(loc, lang)` helper returns a nicely formatted string for EN/AR
and the original for Korean.
"""
from __future__ import annotations

# 17 top-level administrative divisions
PROVINCES: dict[str, dict[str, str]] = {
    '서울': {'en': 'Seoul',            'ar': 'سيول'},
    '부산': {'en': 'Busan',            'ar': 'بوسان'},
    '인천': {'en': 'Incheon',          'ar': 'إنتشون'},
    '대구': {'en': 'Daegu',            'ar': 'دايغو'},
    '광주': {'en': 'Gwangju',          'ar': 'غوانغجو'},
    '대전': {'en': 'Daejeon',          'ar': 'دايجون'},
    '울산': {'en': 'Ulsan',            'ar': 'أولسان'},
    '세종': {'en': 'Sejong',           'ar': 'سيجونغ'},
    '경기': {'en': 'Gyeonggi',         'ar': 'كيونغي'},
    '강원': {'en': 'Gangwon',          'ar': 'غانغوون'},
    '충남': {'en': 'Chungnam',         'ar': 'تشونغنام'},
    '충북': {'en': 'Chungbuk',         'ar': 'تشونغبوك'},
    '전남': {'en': 'Jeonnam',          'ar': 'جيونام'},
    '전북': {'en': 'Jeonbuk',          'ar': 'جيونبوك'},
    '경남': {'en': 'Gyeongnam',        'ar': 'كيونغنام'},
    '경북': {'en': 'Gyeongbuk',        'ar': 'كيونغبوك'},
    '제주': {'en': 'Jeju',             'ar': 'جيجو'},
}

# Suffix meanings (Korea's administrative divisions)
SUFFIX: dict[str, dict[str, str]] = {
    '시': {'en': '',        'ar': ''},          # city — usually dropped in EN
    '군': {'en': 'County',  'ar': 'مقاطعة'},
    '구': {'en': 'District','ar': 'حي'},
    '면': {'en': 'Township','ar': 'ناحية'},
    '읍': {'en': 'Town',    'ar': 'بلدة'},
}

# District base names (stripped of suffix) → (en, ar)
_DISTRICT_BASES: dict[str, dict[str, str]] = {
    # -시 (cities)
    '전주':     {'en': 'Jeonju',        'ar': 'جونجو'},
    '창원':     {'en': 'Changwon',      'ar': 'تشانغوون'},
    '용인':     {'en': 'Yongin',        'ar': 'يونغين'},
    '광주':     {'en': 'Gwangju',       'ar': 'غوانغجو'},
    '수원':     {'en': 'Suwon',         'ar': 'سوون'},
    '천안':     {'en': 'Cheonan',       'ar': 'تشونان'},
    '청주':     {'en': 'Cheongju',      'ar': 'تشونغجو'},
    '김해':     {'en': 'Gimhae',        'ar': 'جيمهاي'},
    '화성':     {'en': 'Hwaseong',      'ar': 'هواسونغ'},
    '고양':     {'en': 'Goyang',        'ar': 'غويانغ'},
    '구미':     {'en': 'Gumi',          'ar': 'غومي'},
    '평택':     {'en': 'Pyeongtaek',    'ar': 'بيونغتايك'},
    '오산':     {'en': 'Osan',          'ar': 'أوسان'},
    '안산':     {'en': 'Ansan',         'ar': 'أنسان'},
    '남양주':   {'en': 'Namyangju',     'ar': 'نامبانغجو'},
    '성남':     {'en': 'Seongnam',      'ar': 'سونغنام'},
    '부천':     {'en': 'Bucheon',       'ar': 'بوتشون'},
    '의정부':   {'en': 'Uijeongbu',     'ar': 'أويجونغبو'},
    '김포':     {'en': 'Gimpo',         'ar': 'جيمبو'},
    '목포':     {'en': 'Mokpo',         'ar': 'موكبو'},
    '영천':     {'en': 'Yeongcheon',    'ar': 'يونغتشون'},
    '안양':     {'en': 'Anyang',        'ar': 'أنيانغ'},
    '시흥':     {'en': 'Siheung',       'ar': 'سيهونغ'},
    '순천':     {'en': 'Suncheon',      'ar': 'سونتشون'},
    '거제':     {'en': 'Geoje',         'ar': 'غوجي'},
    '영주':     {'en': 'Yeongju',       'ar': 'يونغجو'},
    '파주':     {'en': 'Paju',          'ar': 'باجو'},
    '제천':     {'en': 'Jecheon',       'ar': 'جيتشون'},
    '포항':     {'en': 'Pohang',        'ar': 'بوهانغ'},
    '진주':     {'en': 'Jinju',         'ar': 'جينجو'},
    '당진':     {'en': 'Dangjin',       'ar': 'دانغجين'},
    '충주':     {'en': 'Chungju',       'ar': 'تشونغجو'},
    '공주':     {'en': 'Gongju',        'ar': 'غونغجو'},
    '제주':     {'en': 'Jeju',          'ar': 'جيجو'},
    '안성':     {'en': 'Anseong',       'ar': 'أنسونغ'},
    '양산':     {'en': 'Yangsan',       'ar': 'يانغسان'},
    '하남':     {'en': 'Hanam',         'ar': 'هانام'},
    '나주':     {'en': 'Naju',          'ar': 'ناجو'},
    '태백':     {'en': 'Taebaek',       'ar': 'تايبايك'},
    '서귀포':   {'en': 'Seogwipo',      'ar': 'سوغويبو'},
    '아산':     {'en': 'Asan',          'ar': 'أسان'},
    '익산':     {'en': 'Iksan',         'ar': 'إكسان'},
    '여수':     {'en': 'Yeosu',         'ar': 'يوسو'},
    '안동':     {'en': 'Andong',        'ar': 'أندونغ'},
    '군산':     {'en': 'Gunsan',        'ar': 'غونسان'},
    '사천':     {'en': 'Sacheon',       'ar': 'ساتشون'},
    '원주':     {'en': 'Wonju',         'ar': 'وونجو'},
    '경주':     {'en': 'Gyeongju',      'ar': 'كيونغجو'},
    '이천':     {'en': 'Icheon',        'ar': 'إتشون'},
    '통영':     {'en': 'Tongyeong',     'ar': 'تونغيونغ'},
    '논산':     {'en': 'Nonsan',        'ar': 'نونسان'},
    '군포':     {'en': 'Gunpo',         'ar': 'غونبو'},
    '상주':     {'en': 'Sangju',        'ar': 'سانغجو'},
    '김천':     {'en': 'Gimcheon',      'ar': 'جيمتشون'},
    '동해':     {'en': 'Donghae',       'ar': 'دونغاي'},
    '계룡':     {'en': 'Gyeryong',      'ar': 'كيريونغ'},
    '정읍':     {'en': 'Jeongeup',      'ar': 'جونغوب'},
    '광명':     {'en': 'Gwangmyeong',   'ar': 'غوانغميونغ'},
    '서산':     {'en': 'Seosan',        'ar': 'سوسان'},
    '광양':     {'en': 'Gwangyang',     'ar': 'غوانغيانغ'},
    '삼척':     {'en': 'Samcheok',      'ar': 'سامتشوك'},
    '김제':     {'en': 'Gimje',         'ar': 'جيمجي'},
    '보령':     {'en': 'Boryeong',      'ar': 'بوريونغ'},
    '밀양':     {'en': 'Miryang',       'ar': 'ميريانغ'},
    '양주':     {'en': 'Yangju',        'ar': 'يانغجو'},
    '여주':     {'en': 'Yeoju',         'ar': 'يوجو'},
    '남원':     {'en': 'Namwon',        'ar': 'نامون'},
    '춘천':     {'en': 'Chuncheon',     'ar': 'تشونتشون'},
    # -군 (counties)
    '달성':     {'en': 'Dalseong',      'ar': 'دالسونغ'},
    '기장':     {'en': 'Gijang',        'ar': 'غيجانغ'},
    '함평':     {'en': 'Hampyeong',     'ar': 'هامبيونغ'},
    '칠곡':     {'en': 'Chilgok',       'ar': 'تشيلغوك'},
    '울주':     {'en': 'Ulju',          'ar': 'أولجو'},
    '고흥':     {'en': 'Goheung',       'ar': 'غوهونغ'},
    '음성':     {'en': 'Eumseong',      'ar': 'أومسونغ'},
    '홍천':     {'en': 'Hongcheon',     'ar': 'هونغتشون'},
    '부안':     {'en': 'Buan',          'ar': 'بوان'},
    '예산':     {'en': 'Yesan',         'ar': 'يسان'},
    '홍성':     {'en': 'Hongseong',     'ar': 'هونغسونغ'},
    '진천':     {'en': 'Jincheon',      'ar': 'جينتشون'},
    '무안':     {'en': 'Muan',          'ar': 'موان'},
    '신안':     {'en': 'Sinan',         'ar': 'سينان'},
    '합천':     {'en': 'Hapcheon',      'ar': 'هابتشون'},
    '창녕':     {'en': 'Changnyeong',   'ar': 'تشانغنيونغ'},
    '의성':     {'en': 'Uiseong',       'ar': 'أويسونغ'},
    '양평':     {'en': 'Yangpyeong',    'ar': 'يانغبيونغ'},
    '남해':     {'en': 'Namhae',        'ar': 'نامهاي'},
    '함안':     {'en': 'Haman',         'ar': 'هامان'},
    '옥천':     {'en': 'Okcheon',       'ar': 'أوكتشون'},
    '고령':     {'en': 'Goryeong',      'ar': 'غوريونغ'},
    '청도':     {'en': 'Cheongdo',      'ar': 'تشونغدو'},
    '장흥':     {'en': 'Jangheung',     'ar': 'جانغهونغ'},
    '서천':     {'en': 'Seocheon',      'ar': 'سوتشون'},
    '영암':     {'en': 'Yeongam',       'ar': 'يونغام'},
    '철원':     {'en': 'Cheorwon',      'ar': 'تشوروون'},
    # -구 (districts)
    '서':       {'en': 'Seo',           'ar': 'سو'},          # compass "west"
    '동':       {'en': 'Dong',          'ar': 'دونغ'},         # "east"
    '남':       {'en': 'Nam',           'ar': 'نام'},          # "south"
    '북':       {'en': 'Buk',           'ar': 'بوك'},          # "north"
    '중':       {'en': 'Jung',          'ar': 'جونغ'},         # "center"
    '광산':     {'en': 'Gwangsan',      'ar': 'غوانغسان'},
    '부평':     {'en': 'Bupyeong',      'ar': 'بوبيونغ'},
    '사상':     {'en': 'Sasang',        'ar': 'ساسانغ'},
    '계양':     {'en': 'Gyeyang',       'ar': 'كيانغ'},
    '영등포':   {'en': 'Yeongdeungpo',  'ar': 'يونغ دينغبو'},
    '성동':     {'en': 'Seongdong',     'ar': 'سونغ دونغ'},
    '대덕':     {'en': 'Daedeok',       'ar': 'دايدوك'},
    '해운대':   {'en': 'Haeundae',      'ar': 'هيوندي'},
    '남동':     {'en': 'Namdong',       'ar': 'نام دونغ'},
    '유성':     {'en': 'Yuseong',       'ar': 'يوسونغ'},
    '금정':     {'en': 'Geumjeong',     'ar': 'غيومجونغ'},
    '수성':     {'en': 'Suseong',       'ar': 'سوسونغ'},
    '달서':     {'en': 'Dalseo',        'ar': 'دالسو'},
    '송파':     {'en': 'Songpa',        'ar': 'سونغبا'},
    '강동':     {'en': 'Gangdong',      'ar': 'غانغ دونغ'},
    '강서':     {'en': 'Gangseo',       'ar': 'غانغ سو'},
    '서대문':   {'en': 'Seodaemun',     'ar': 'سودايمون'},
    '동작':     {'en': 'Dongjak',       'ar': 'دونغ جاك'},
    '도봉':     {'en': 'Dobong',        'ar': 'دوبونغ'},
    '중랑':     {'en': 'Jungnang',      'ar': 'جونغ نانغ'},
    '관악':     {'en': 'Gwanak',        'ar': 'غواناك'},
    '동대문':   {'en': 'Dongdaemun',    'ar': 'دونغ دايمون'},
    '금천':     {'en': 'Geumcheon',     'ar': 'غيومتشون'},
    '강북':     {'en': 'Gangbuk',       'ar': 'غانغ بوك'},
    '사하':     {'en': 'Saha',          'ar': 'ساها'},
    '양천':     {'en': 'Yangcheon',     'ar': 'يانغ تشون'},
    '구로':     {'en': 'Guro',          'ar': 'غورو'},
    '동래':     {'en': 'Dongnae',       'ar': 'دونغ ناي'},
    '영도':     {'en': 'Yeongdo',       'ar': 'يونغ دو'},
    '노원':     {'en': 'Nowon',         'ar': 'نوون'},
    '마포':     {'en': 'Mapo',          'ar': 'مابو'},
    # -면 / -읍 (townships / towns)
    '소정':     {'en': 'Sojeong',       'ar': 'سوجونغ'},
    '금남':     {'en': 'Geumnam',       'ar': 'غيومنام'},
    '조치원':   {'en': 'Jochiwon',      'ar': 'جوتشيون'},
    # special
    '세종':     {'en': 'Sejong',        'ar': 'سيجونغ'},
    '확인중':   {'en': 'Pending',       'ar': 'قيد التحقق'},
}


def _translate_district(district: str, lang: str) -> str:
    """Translate e.g. '전주시' → 'Jeonju' / 'جونجو'."""
    if not district:
        return district
    # strip trailing suffix, translate base, optionally attach suffix label
    for suf, tr in SUFFIX.items():
        if district.endswith(suf):
            base = district[: -len(suf)]
            en_base = _DISTRICT_BASES.get(base, {}).get('en', base)
            ar_base = _DISTRICT_BASES.get(base, {}).get('ar', base)
            if lang == 'en':
                suf_lbl = tr['en']
                return f'{en_base} {suf_lbl}'.strip()
            if lang == 'ar':
                suf_lbl = tr['ar']
                return f'{suf_lbl} {ar_base}'.strip() if suf_lbl else ar_base
            return district
    # no suffix — look up directly
    if lang in ('en', 'ar'):
        hit = _DISTRICT_BASES.get(district)
        if hit:
            return hit[lang]
    return district


def translate(loc: str, lang: str) -> str:
    """Translate e.g. '전북 전주시' → 'Jeonju, Jeonbuk' / 'جونجو، جيونبوك'.

    For Korean (`lang='ko'`) and unknown input, returns the input unchanged.
    """
    if not loc or lang == 'ko':
        return loc or ''
    parts = loc.strip().split(maxsplit=1)
    if len(parts) == 2:
        province, district = parts
        pn = PROVINCES.get(province, {}).get(lang, province)
        dn = _translate_district(district, lang)
        if lang == 'en':
            return f'{dn}, {pn}'
        if lang == 'ar':
            return f'{dn}، {pn}'  # Arabic comma U+060C
    # single-word location
    if lang in ('en', 'ar'):
        hit = _DISTRICT_BASES.get(loc.strip())
        if hit:
            return hit[lang]
        hit = PROVINCES.get(loc.strip())
        if hit:
            return hit[lang]
    return loc
