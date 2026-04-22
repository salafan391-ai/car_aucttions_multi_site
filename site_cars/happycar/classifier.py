"""Classify a HappyCar title into make / model / trim + translations.

Primary data source: the translation tables in `transelations.py`
  - `makes`: 227 rows (ko, ar, en)
  - `translated_models`: 1412 rows (ko, ar, en)
  - `make_model_translated`: 571 rows (ko, ar, en, make_ar, make_en)
  - `fuel`: 38 rows  - `missions`: 16 rows (transmissions)

Strategy:
  1. If the title starts with a known Korean make name (e.g. `벤츠`, `아우디`,
     `테슬라`), that fixes the make. We then search the rest for a model name.
  2. Otherwise, try the make+model table (`make_model_translated`) for a
     longest Korean substring match — this covers most Korean-brand cars
     where the model name alone identifies the make (e.g. `K3` → Kia).
  3. Otherwise, try the model-only table and back-fill the make from a
     canonical model→make map.
  4. Finally, fall back to a tiny hand-rolled rules table for edge cases.

Returns per-language fields: make_en/ar/ko, model_en/ar/ko, plus trim/tag.
"""
from __future__ import annotations
import re, sys, types

# transelations.py imports pandas but only uses it in dead code — stub it
if 'pandas' not in sys.modules:
    _stub = types.ModuleType('pandas')
    _stub.DataFrame = lambda *a, **k: None  # type: ignore[attr-defined]
    sys.modules['pandas'] = _stub

from .transelations import (  # noqa: E402
    makes as _MAKES_TBL,
    translated_models as _MODELS_TBL,
    make_model_translated as _MM_TBL,
    fuel as _FUEL_TBL,
    missions as _TRANS_TBL,
)

# ---------- lookups ----------
_MAKE_EN_TO_AR: dict[str, str] = {}
for ko, ar, en in _MAKES_TBL:
    _MAKE_EN_TO_AR.setdefault(en, ar)

# Canonical Korean display for each English make. The raw `makes` table has
# noisy rows (K3→Kia, 뉴→Hyundai, etc.) so we pin clean labels here.
_MAKE_EN_TO_KO: dict[str, str] = {
    'Hyundai': '현대', 'Kia': '기아', 'Genesis': '제네시스',
    'Chevrolet': '쉐보레', 'Daewoo': '대우', 'SsangYong': '쌍용',
    'Ssangyong': '쌍용',
    'Renault': '르노', 'Renault Samsung': '르노삼성',
    'Samsung': '삼성', 'Korea': '한국',
    'BMW': 'BMW', 'Mercedes-Benz': '벤츠',
    'Audi': '아우디', 'Volkswagen': '폭스바겐', 'Porsche': '포르쉐',
    'MINI': '미니', 'Mini': '미니', 'Smart': '스마트',
    'Tesla': '테슬라', 'Polestar': '폴스타', 'Volvo': '볼보',
    'Toyota': '토요타', 'Lexus': '렉서스',
    'Honda': '혼다', 'Nissan': '닛산', 'Infiniti': '인피니티',
    'Mazda': '마쓰다', 'Mitsubishi': '미쓰비시', 'Subaru': '스바루',
    'Ford': '포드', 'Jeep': '지프', 'Chrysler': '크라이슬러',
    'Cadillac': '캐딜락', 'Lincoln': '링컨', 'Dodge': '닷지',
    'Hummer': '허머',
    'Peugeot': '푸조', 'Citroën': '시트로엥',
    'Jaguar': '재규어', 'Land Rover': '랜드로버',
    'Fiat': '피아트', 'Alfa Romeo': '알파로메오',
    'Maserati': '마세라티', 'Ferrari': '페라리', 'Lamborghini': '람보르기니',
    'Bentley': '벤틀리', 'Rolls-Royce': '롤스로이스', 'Rolls Royce': '롤스로이스',
    'Aston Martin': '애스턴마틴', 'Acura': '어큐라',
    'Unknown': '미분류',
}

# Make prefixes (Korean forms likely to appear at start of title).
# Map each to (make_en, make_ar).
_LEADING_MAKES: dict[str, tuple[str, str]] = {
    '벤츠': ('Mercedes-Benz', 'مرسيدس'),
    '메르세데스': ('Mercedes-Benz', 'مرسيدس'),
    '메르세데스-벤츠': ('Mercedes-Benz', 'مرسيدس'),
    '아우디': ('Audi', 'أودي'),
    '폭스바겐': ('Volkswagen', 'فولكس واجن'),
    '포르쉐': ('Porsche', 'بورش'),
    '테슬라': ('Tesla', 'تسلا'),
    '폴스타': ('Polestar', 'بولستار'),
    '볼보': ('Volvo', 'فولفو'),
    '토요타': ('Toyota', 'تويوتا'),
    '도요타': ('Toyota', 'تويوتا'),
    '렉서스': ('Lexus', 'لكسز'),
    '혼다': ('Honda', 'هوندا'),
    '닛산': ('Nissan', 'نيسان'),
    '인피니티': ('Infiniti', 'إنفينيتي'),
    '마쓰다': ('Mazda', 'مازدا'),
    '미쓰비시': ('Mitsubishi', 'ميتسوبيشي'),
    '스바루': ('Subaru', 'سوبارو'),
    '포드': ('Ford', 'فورد'),
    '지프': ('Jeep', 'جيب'),
    '짚': ('Jeep', 'جيب'),
    '크라이슬러': ('Chrysler', 'كرايسلير'),
    '캐딜락': ('Cadillac', 'كاديلاك'),
    '링컨': ('Lincoln', 'لينكون'),
    '닷지': ('Dodge', 'دودج'),
    '푸조': ('Peugeot', 'بيجوت'),
    '시트로엥': ('Citroën', 'سيتروين'),
    '르노': ('Renault', 'رينو'),
    '재규어': ('Jaguar', 'جاقوار'),
    '랜드로버': ('Land Rover', 'لاند روفر'),
    '피아트': ('Fiat', 'فيات'),
    '알파로메오': ('Alfa Romeo', 'ألفا روميو'),
    '마세라티': ('Maserati', 'مازيراتي'),
    '페라리': ('Ferrari', 'فيراري'),
    '람보르기니': ('Lamborghini', 'لامبورغيني'),
    '벤틀리': ('Bentley', 'بينتلي'),
    '롤스로이스': ('Rolls-Royce', 'رولز رويس'),
    '애스턴마틴': ('Aston Martin', 'أستون مارتن'),
    '스마트': ('Smart', 'سمارت'),
    '미니': ('Mini', 'ميني'),
    '쉐보레': ('Chevrolet', 'شيفروليه'),
    '쉐보레(GM대우)': ('Chevrolet', 'شيفروليه'),
    '현대': ('Hyundai', 'هيونداي'),
    '기아': ('Kia', 'كيا'),
    '제네시스': ('Genesis', 'جينسس'),
    '쌍용': ('SsangYong', 'سانغ يونغ'),
    '대우': ('Daewoo', 'دايو'),
    '허머': ('Hummer', 'همر'),
    'BMW': ('BMW', 'BMW'),
    'DS': ('DS', 'دي إس'),
}
# Latin-case alternatives too (tables may have both)
_LEADING_MAKES_EN = {k.upper(): v for k, v in _LEADING_MAKES.items() if k.isascii()}

# Fallback model → make, for titles where only the model is present
_MODEL_TO_MAKE: dict[str, str] = {
    # Hyundai
    '쏘나타': 'Hyundai', 'NF쏘나타': 'Hyundai', 'YF쏘나타': 'Hyundai',
    'LF쏘나타': 'Hyundai', 'EF쏘나타': 'Hyundai', 'DN8': 'Hyundai',
    '아반떼': 'Hyundai', '아반테': 'Hyundai', '아반떼HD': 'Hyundai',
    '아반떼AD': 'Hyundai', '아반떼MD': 'Hyundai', '아반테XD': 'Hyundai',
    '그랜저': 'Hyundai', '그랜저HG': 'Hyundai', '그랜저IG': 'Hyundai',
    '그랜저TG': 'Hyundai', '에쿠스': 'Hyundai',
    '엑센트': 'Hyundai', '베르나': 'Hyundai', '클릭': 'Hyundai',
    '싼타페': 'Hyundai', '산타페': 'Hyundai',
    '투싼': 'Hyundai', '투싼ix': 'Hyundai',
    '테라칸': 'Hyundai', '베라크루즈': 'Hyundai',
    '팰리세이드': 'Hyundai', '코나': 'Hyundai', '캐스퍼': 'Hyundai',
    '벨로스터': 'Hyundai', '아이오닉': 'Hyundai',
    '포터': 'Hyundai', '포터II': 'Hyundai',
    '스타렉스': 'Hyundai', '스타리아': 'Hyundai', '마이티': 'Hyundai',
    '엑시언트': 'Hyundai', '쏠라티': 'Hyundai', '라페스타': 'Hyundai',
    '넥쏘': 'Hyundai', '투스카니': 'Hyundai', '트라제': 'Hyundai',
    '트라제XG': 'Hyundai', '에어로타운': 'Hyundai', '카운티': 'Hyundai',
    '유니버스': 'Hyundai', '갤로퍼': 'Hyundai', '티뷰론': 'Hyundai',
    'i30': 'Hyundai', 'i40': 'Hyundai',
    # Kia
    'K3': 'Kia', 'K5': 'Kia', 'K7': 'Kia', 'K8': 'Kia', 'K9': 'Kia',
    '모닝': 'Kia', '레이': 'Kia', '프라이드': 'Kia', '리오': 'Kia',
    '쏘울': 'Kia', '스토닉': 'Kia', '셀토스': 'Kia',
    '스포티지': 'Kia', '스포티지R': 'Kia',
    '쏘렌토': 'Kia', '쏘렌토R': 'Kia',
    '모하비': 'Kia', '텔루라이드': 'Kia',
    '카니발': 'Kia', '카니발R': 'Kia', '그랜드 카니발': 'Kia',
    '봉고': 'Kia', '봉고III': 'Kia', '봉고1톤': 'Kia',
    '니로': 'Kia', 'EV3': 'Kia', 'EV4': 'Kia', 'EV6': 'Kia', 'EV9': 'Kia',
    '오피러스': 'Kia', '카렌스': 'Kia', '스팅어': 'Kia', '포르테': 'Kia',
    '로체': 'Kia', '쎄라토': 'Kia',
    # Genesis
    'G70': 'Genesis', 'G80': 'Genesis', 'G90': 'Genesis',
    'GV60': 'Genesis', 'GV70': 'Genesis', 'GV80': 'Genesis', 'EQ900': 'Genesis',
    '제네시스': 'Genesis',
    # Chevrolet / GM
    '스파크': 'Chevrolet', '말리부': 'Chevrolet', '트랙스': 'Chevrolet',
    '올란도': 'Chevrolet', '이쿼녹스': 'Chevrolet', '볼트': 'Chevrolet',
    '캡티바': 'Chevrolet', '아베오': 'Chevrolet', '크루즈': 'Chevrolet',
    '알페온': 'Chevrolet', '카마로': 'Chevrolet', '임팔라': 'Chevrolet',
    '트레일블레이저': 'Chevrolet',
    # Daewoo
    '마티즈': 'Daewoo', '라세티': 'Daewoo', '다마스': 'Daewoo',
    '레간자': 'Daewoo', '매그너스': 'Daewoo', '토스카': 'Daewoo',
    '윈스톰': 'Daewoo', '칼로스': 'Daewoo', '젠트라': 'Daewoo',
    '누비라': 'Daewoo',
    # Renault Samsung / Renault Korea
    'SM3': 'Renault Samsung', 'SM5': 'Renault Samsung',
    'SM6': 'Renault Samsung', 'SM7': 'Renault Samsung',
    'QM3': 'Renault Samsung', 'QM5': 'Renault Samsung',
    'QM6': 'Renault Samsung', 'XM3': 'Renault Samsung',
    'SM520': 'Renault Samsung', 'SM520V': 'Renault Samsung',
    'SM525': 'Renault Samsung', 'SM530': 'Renault Samsung',
    'SM528': 'Renault Samsung',
    # SsangYong
    '티볼리': 'SsangYong', '코란도': 'SsangYong', '코란도C': 'SsangYong',
    '코란도스포츠': 'SsangYong',
    '렉스턴': 'SsangYong', '렉스턴W': 'SsangYong',
    '체어맨': 'SsangYong', '체어맨H': 'SsangYong',
    '무쏘': 'SsangYong', '액티언': 'SsangYong',
    '카이런': 'SsangYong', '로디우스': 'SsangYong', '토레스': 'SsangYong',
    # Other
    '엑스트렉': 'Nissan', '엑스트레일': 'Nissan',
    '포르자750': 'Honda',
}

# Transliterations for models that are NOT in the user's translation tables.
# Maps Korean model name -> (english, arabic).
_EXTRA_MODEL_TR: dict[str, tuple[str, str]] = {
    '투스카니':     ('Tuscani',    'توسكاني'),
    '아반테XD':    ('Avante XD',  'النترا XD'),
    '봉고1톤':     ('Bongo 1T',   'بونغو 1 طن'),
    '엑스트렉':     ('X-Trail',    'إكس تريل'),
    '엑스트레일':    ('X-Trail',    'إكس تريل'),
    '카이런':      ('Kyron',      'كايرون'),
    '토스카':      ('Tosca',      'توسكا'),
    '클릭':       ('Click',      'كليك'),
    '포르자750':   ('Forza 750',  'فورزا 750'),
    '에어로타운':   ('Aero Town',  'إيرو تاون'),
    '포르토피노':   ('Portofino',  'بورتوفينو'),
    '쿠페':       ('Coupe',      'كوبيه'),
    '제네시스':     ('Genesis',    'جينسس'),
    '커맨더':      ('Commander',  'كوماندر'),
}

# Model table -> (ar, en) indexed by Korean
_MODEL_AR: dict[str, str] = {}
_MODEL_EN: dict[str, str] = {}
for ko, ar, en in _MODELS_TBL:
    if ko:
        _MODEL_AR.setdefault(ko, ar)
        _MODEL_EN.setdefault(ko, en)
for ko, ar, en, _m_ar, _m_en in _MM_TBL:
    if ko:
        _MODEL_AR.setdefault(ko, ar)
        _MODEL_EN.setdefault(ko, en)

def _has_hangul(s: str) -> bool:
    return any('가' <= c <= '힣' for c in (s or ''))


# Build a cleaner index per Korean model key. Some mm rows have polluted
# Arabic (e.g. '포터II' -> 'بور터 II' — literal Hangul stuck in the Arabic).
# If translated_models has a clean entry for the same key, prefer its ar/en
# strings while keeping the mm row's make info.
_models_by_ko: dict[str, dict] = {}
for ko, ar, en, m_ar, m_en in _MM_TBL:
    if not ko:
        continue
    _models_by_ko.setdefault(ko, {
        'ko': ko, 'ar': ar, 'en': en,
        'm_en': m_en, 'm_ar': m_ar,
    })
for ko, ar, en in _MODELS_TBL:
    if not ko:
        continue
    cur = _models_by_ko.get(ko)
    if cur is None:
        _models_by_ko[ko] = {'ko': ko, 'ar': ar, 'en': en,
                             'm_en': None, 'm_ar': None}
        continue
    # overwrite Arabic/English from models table when mm version is dirty
    if _has_hangul(cur['ar']) and not _has_hangul(ar):
        cur['ar'] = ar
    if _has_hangul(cur['en']) and not _has_hangul(en):
        cur['en'] = en

_ALL_MODELS: list[tuple[str, str, str, str | None, str | None]] = sorted(
    [(r['ko'], r['ar'], r['en'], r['m_ar'], r['m_en'])
     for r in _models_by_ko.values()],
    key=lambda r: -len(r[0]))

_PREFIX_TAG = re.compile(r'^\((부품|이륜|수출|렌트)\)\s*')

TAG_I18N: dict[str, dict[str, str]] = {
    '부품': {'en': 'Parts',     'ar': 'قطع غيار',    'ko': '부품'},
    '이륜': {'en': 'Two-wheel', 'ar': 'دراجة نارية', 'ko': '이륜'},
    '수출': {'en': 'Export',    'ar': 'تصدير',       'ko': '수출'},
    '렌트': {'en': 'Rental',    'ar': 'تأجير',       'ko': '렌트'},
}

# Fuel / transmission lookups (case-insensitive on key)
_FUEL_AR: dict[str, str] = {}
_FUEL_EN: dict[str, str] = {}
for ko, ar, en in _FUEL_TBL:
    if ko:
        _FUEL_AR.setdefault(ko.lower(), ar)
        _FUEL_EN.setdefault(ko.lower(), en)

_TRANS_AR: dict[str, str] = {}
_TRANS_EN: dict[str, str] = {}
for ko, ar, en in _TRANS_TBL:
    if ko:
        _TRANS_AR.setdefault(ko.lower(), ar)
        _TRANS_EN.setdefault(ko.lower(), en)


# ---------- main classify ----------
def _make_record(make_en: str) -> dict[str, str]:
    return {
        'make': make_en, 'make_en': make_en,
        'make_ar': _MAKE_EN_TO_AR.get(make_en, make_en),
        'make_ko': _MAKE_EN_TO_KO.get(make_en, make_en),
    }


def _is_latin_word(s: str) -> bool:
    return any(c.isascii() and (c.isalpha() or c.isdigit()) for c in s)


def _token_pos(text: str, needle: str) -> int:
    """Return position where `needle` appears as a standalone token in `text`,
    or -1 if not found. For Latin models (e.g. `S60`, `K3`, `GLS 450D`) the
    match must be delimited by non-alphanumeric chars on each side, so `S60`
    does NOT match inside `GLS600`. For pure-Korean models, a plain substring
    match is fine.
    """
    if not needle:
        return -1
    latin = _is_latin_word(needle)
    start = 0
    while True:
        i = text.find(needle, start)
        if i < 0:
            return -1
        if not latin:
            return i
        before_ok = i == 0 or not (
            text[i - 1].isascii() and text[i - 1].isalnum())
        end = i + len(needle)
        after_ok = end == len(text) or not (
            text[end].isascii() and text[end].isalnum())
        if before_ok and after_ok:
            return i
        start = i + 1


def _find_model_in(text: str) -> tuple[str, str, str, str | None, int] | None:
    """Find the longest known model name in `text`.
    Returns (ko, ar, en, make_en?, pos) or None."""
    for ko, ar, en, _m_ar, m_en in _ALL_MODELS:
        pos = _token_pos(text, ko)
        if pos >= 0:
            return ko, ar, en, m_en, pos
    return None


def _strip_tag(title: str) -> tuple[str, str]:
    if m := _PREFIX_TAG.match(title):
        return title[m.end():].strip(), m.group(1)
    return title, ''


def classify(title: str) -> dict[str, str]:
    raw = (title or '').strip()
    title_, tag = _strip_tag(raw)

    out: dict[str, str] = {
        'make': 'Unknown', 'make_en': 'Unknown',
        'make_ar': _MAKE_EN_TO_AR.get('Unknown', 'غير مصنّف'),
        'make_ko': '미분류',
        'model': title_, 'model_en': title_,
        'model_ar': title_, 'model_ko': title_,
        'trim': '', 'tag': tag, 'origin': 'unknown',
    }

    # 1) title starts with a leading make name (applies to most imports)
    leading = None
    for ko in sorted(_LEADING_MAKES, key=lambda s: -len(s)):
        if title_.startswith(ko + ' ') or title_ == ko:
            leading = ko
            break
    if leading:
        make_en, make_ar = _LEADING_MAKES[leading]
        out.update(_make_record(make_en))
        out['make_ar'] = make_ar or out['make_ar']
        rest = title_[len(leading):].strip()
        found = _find_model_in(rest) if rest else None
        if found:
            ko, ar, en, _mk, pos = found
            trim = (rest[:pos] + ' ' + rest[pos + len(ko):]).strip()
            out.update({'model': en, 'model_en': en,
                        'model_ar': ar, 'model_ko': ko,
                        'trim': trim, 'origin': 'prefix+model'})
        else:
            # try extra translation fallback on the rest (or the leading
            # token itself if no rest, e.g. standalone "제네시스")
            probe = rest or leading
            hit_ko: str | None = None
            for ko in sorted(_EXTRA_MODEL_TR, key=lambda s: -len(s)):
                if _token_pos(probe, ko) >= 0:
                    hit_ko = ko
                    break
            if hit_ko:
                en, ar = _EXTRA_MODEL_TR[hit_ko]
                pos = _token_pos(probe, hit_ko)
                trim = (probe[:pos] + ' ' + probe[pos + len(hit_ko):]).strip()
                out.update({'model': en, 'model_en': en,
                            'model_ar': ar, 'model_ko': hit_ko,
                            'trim': trim, 'origin': 'prefix+extra'})
            else:
                out.update({'model': probe, 'model_en': probe,
                            'model_ar': probe, 'model_ko': probe,
                            'origin': 'prefix'})
        return out

    # 2) no leading make — try model tables against whole title
    found = _find_model_in(title_)
    if found:
        ko, ar, en, m_en, pos = found
        trim = (title_[:pos] + ' ' + title_[pos + len(ko):]).strip()
        out.update({'model': en, 'model_en': en,
                    'model_ar': ar, 'model_ko': ko,
                    'trim': trim, 'origin': 'model'})
        if m_en:
            out.update(_make_record(m_en))
        else:
            m_en = _MODEL_TO_MAKE.get(ko)
            if not m_en:
                # substring fallback: `아반떼HD 1.6` → lookup `아반떼HD`
                for key in sorted(_MODEL_TO_MAKE, key=lambda s: -len(s)):
                    if key in ko:
                        m_en = _MODEL_TO_MAKE[key]
                        break
            if m_en:
                out.update(_make_record(m_en))
                out['origin'] = 'model+lookup'
        return out

    # 3) hand-rolled model→make dict (covers models missing from tables,
    #    e.g. 카이런, 투스카니, 엑스트렉, 봉고1톤, 클릭, 아반테XD)
    for ko in sorted(_MODEL_TO_MAKE, key=lambda s: -len(s)):
        pos = _token_pos(title_, ko)
        if pos >= 0:
            trim = (title_[:pos] + ' ' + title_[pos + len(ko):]).strip()
            make_en = _MODEL_TO_MAKE[ko]
            en, ar = _EXTRA_MODEL_TR.get(ko, (ko, ko))
            out.update(_make_record(make_en))
            out.update({'model': en, 'model_en': en, 'model_ar': ar,
                        'model_ko': ko, 'trim': trim,
                        'origin': 'rule'})
            return out

    # 4) make-only substring match as a last resort
    for ko, ar, en in sorted(_MAKES_TBL, key=lambda r: -len(r[0] or '')):
        if ko and ko in title_:
            out.update(_make_record(en))
            out['origin'] = 'make_only'
            return out

    return out


# ---------- per-language label helpers ----------
def make_label(make_en: str | None, lang: str = 'en', *, fallback: str = '') -> str:
    if not make_en:
        return fallback
    if lang == 'en':
        return make_en
    if lang == 'ar':
        return _MAKE_EN_TO_AR.get(make_en, make_en)
    if lang == 'ko':
        return _MAKE_EN_TO_KO.get(make_en, make_en)
    return make_en


def pick(row: dict, field: str, lang: str) -> str:
    return (row.get(f'{field}_{lang}') or row.get(field) or '') if row else ''


def tag_label(tag: str, lang: str = 'en') -> str:
    if not tag:
        return ''
    return TAG_I18N.get(tag, {}).get(lang) or tag


def fuel_label(value: str | None, lang: str = 'en') -> str:
    if not value:
        return ''
    key = value.strip().lower()
    if lang == 'ar':
        return _FUEL_AR.get(key, value)
    if lang == 'en':
        return _FUEL_EN.get(key, value)
    return value


def trans_label(value: str | None, lang: str = 'en') -> str:
    if not value:
        return ''
    key = value.strip().lower()
    if lang == 'ar':
        return _TRANS_AR.get(key, value)
    if lang == 'en':
        return _TRANS_EN.get(key, value)
    return value


# legacy alias for earlier app.py code
MAKE_I18N = {
    m_en: {'en': m_en, 'ar': _MAKE_EN_TO_AR.get(m_en, m_en),
           'ko': _MAKE_EN_TO_KO.get(m_en, m_en)}
    for m_en in set(_MAKE_EN_TO_AR) | set(_MAKE_EN_TO_KO)
}
