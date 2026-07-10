# Convert every tenant's legacy flat calculator fields into the fully dynamic
# import_calc_config structure. Hidden rows (import_calc_show_* = False) are
# dropped; custom fee lines are appended. Reversible by simply clearing config.
from django.db import migrations


def _fee_lines(fees):
    out = []
    for f in fees or []:
        label = (f.get('label') or '').strip()
        try:
            amount = float(f.get('amount') or 0)
        except (TypeError, ValueError):
            amount = 0
        if label and amount > 0:
            out.append({
                'label': label,
                'type': 'pct_car' if f.get('type') == 'pct' else 'fixed',
                'amount': amount,
            })
    return out


def _num(v, default=0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def build_config(apps, schema_editor):
    Tenant = apps.get_model('tenants', 'Tenant')
    for t in Tenant.objects.all():
        cfg = []
        if getattr(t, 'import_calc_show_sa', True):
            lines = []
            if t.import_calc_show_shipping:
                lines.append({'label': 'الشحن (كوريا ← الوجهة)', 'type': 'tiered', 'amount': 0,
                              'amount_s': t.import_calc_shipping_small or 0,
                              'amount_m': t.import_calc_shipping or 0,
                              'amount_l': t.import_calc_shipping_large or 0})
            if t.import_calc_show_duty and _num(t.import_calc_duty_pct):
                lines.append({'label': 'الرسوم الجمركية', 'type': 'pct_sub', 'amount': _num(t.import_calc_duty_pct)})
            if t.import_calc_show_extra and t.import_calc_preyear and t.import_calc_preyear_extra:
                lines.append({'label': 'رسوم جمركية إضافية (موديل أقدم)', 'type': 'fixed',
                              'amount': t.import_calc_preyear_extra, 'cond_max_year': t.import_calc_preyear})
            if t.import_calc_show_vat and _num(t.import_calc_vat_pct):
                lines.append({'label': 'ضريبة القيمة المضافة', 'type': 'pct_sub', 'amount': _num(t.import_calc_vat_pct)})
            for attr, show, lbl in (
                ('import_calc_clearance', t.import_calc_show_clearance, 'التخليص الجمركي'),
                ('import_calc_inspection', t.import_calc_show_inspection, 'الفحص'),
                ('import_calc_registration', t.import_calc_show_registration, 'اللوحات والاستمارة'),
                ('import_calc_agent', t.import_calc_show_agent, 'عمولة الوكيل'),
            ):
                val = getattr(t, attr) or 0
                if show and val:
                    lines.append({'label': lbl, 'type': 'fixed', 'amount': val})
            lines += _fee_lines(getattr(t, 'import_calc_sa_fees', None))
            cfg.append({'name_ar': 'السعودية', 'name_en': 'Saudi Arabia', 'flag': '🇸🇦',
                        'currency': 'SAR', 'lines': lines})
        for co in (t.import_calc_countries or []):
            lines = []
            tiers = [_num(co.get('shipping_small')), _num(co.get('shipping_medium') or co.get('shipping')), _num(co.get('shipping_large'))]
            if any(tiers):
                lines.append({'label': 'الشحن (كوريا ← الوجهة)', 'type': 'tiered', 'amount': 0,
                              'amount_s': tiers[0], 'amount_m': tiers[1], 'amount_l': tiers[2]})
            if _num(co.get('duty_pct')):
                lines.append({'label': 'الرسوم الجمركية', 'type': 'pct_sub', 'amount': _num(co.get('duty_pct'))})
            if _num(co.get('preyear')) and _num(co.get('preyear_extra')):
                lines.append({'label': 'رسوم جمركية إضافية (موديل أقدم)', 'type': 'fixed',
                              'amount': _num(co.get('preyear_extra')), 'cond_max_year': int(_num(co.get('preyear')))})
            if _num(co.get('vat_pct')):
                lines.append({'label': 'ضريبة القيمة المضافة', 'type': 'pct_sub', 'amount': _num(co.get('vat_pct'))})
            for key, lbl in (('clearance', 'التخليص الجمركي'), ('inspection', 'الفحص'),
                             ('registration', 'اللوحات والاستمارة'), ('agent', 'عمولة الوكيل')):
                if _num(co.get(key)):
                    lines.append({'label': lbl, 'type': 'fixed', 'amount': _num(co.get(key))})
            lines += _fee_lines(co.get('fees'))
            cfg.append({'name_ar': co.get('name_ar') or '', 'name_en': co.get('name_en') or '',
                        'flag': co.get('flag') or '', 'currency': co.get('currency') or 'SAR',
                        'lines': lines})
        t.import_calc_config = cfg
        t.save(update_fields=['import_calc_config'])


def clear_config(apps, schema_editor):
    Tenant = apps.get_model('tenants', 'Tenant')
    Tenant.objects.update(import_calc_config=[])


class Migration(migrations.Migration):
    dependencies = [('tenants', '0073_tenant_import_calc_config')]
    operations = [migrations.RunPython(build_config, clear_config)]
