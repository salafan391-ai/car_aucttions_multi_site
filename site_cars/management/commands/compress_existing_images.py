"""
Management command to retroactively compress existing uploaded images.

Works with S3/CloudFront storage (reads image, compresses in-memory, writes back).

Usage on Heroku:
    # Dry run for a tenant (safe, no changes):
    heroku run "python manage.py compress_existing_images --schema=<tenant_schema>"

    # Apply for a specific tenant:
    heroku run "python manage.py compress_existing_images --schema=<tenant_schema> --apply"

    # Run for ALL tenants at once:
    heroku run "python manage.py compress_existing_images --all-tenants --apply"

Schema routing (automatic):
    - Tenant / TenantHeroImage  -> always saved in public schema
    - SiteCar / SiteCarImage / PostImage -> saved in the given tenant schema
"""
from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from django.db import connection
from PIL import Image
from io import BytesIO


# Tenant-schema models (SiteCar, SiteCarImage, PostImage)
TENANT_TARGETS = [
    ('SiteCar',      'site_cars', 'SiteCar',     [('image', 1200, 900, 85)]),
    ('SiteCarImage', 'site_cars', 'SiteCarImage', [('image', 1200, 900, 85)]),
    ('PostImage',    'cars',      'PostImage',    [('image', 1200, 900, 85)]),
]

# Public-schema models (Tenant, TenantHeroImage)
PUBLIC_TARGETS = [
    ('Tenant', 'tenants', 'Tenant', [
        ('logo',                  400,  400, 85),
        ('favicon',                64,   64, 90),
        ('hero_image',           1920, 1080, 82),
        ('contact_person_photo',  400,  400, 85),
    ]),
    ('TenantHeroImage', 'tenants', 'TenantHeroImage', [('image', 1920, 1080, 82)]),
]


def _compress(field_file, max_width, max_height, quality):
    """
    Read field_file from storage, compress with Pillow.
    Returns (ContentFile, old_kb, new_kb, skip_reason).
    skip_reason is None when the file should be rewritten.
    """
    try:
        field_file.open('rb')
        raw = field_file.read()
        field_file.close()
    except Exception as e:
        return None, 0, 0, f"read error: {e}"

    old_kb = len(raw) / 1024

    try:
        img = Image.open(BytesIO(raw))
    except Exception as e:
        return None, old_kb, 0, f"PIL open error: {e}"

    # Convert palette / transparency modes to RGB
    if img.mode in ('RGBA', 'LA', 'P'):
        bg = Image.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'P':
            img = img.convert('RGBA')
        bg.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
        img = bg
    elif img.mode != 'RGB':
        img = img.convert('RGB')

    needs_resize = img.width > max_width or img.height > max_height
    if needs_resize:
        img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

    out = BytesIO()
    img.save(out, format='JPEG', quality=quality, optimize=True)
    new_kb = out.tell() / 1024

    # Skip if result is not at least 5% smaller (avoids bloating already-optimal files)
    if new_kb >= old_kb * 0.95:
        return None, old_kb, new_kb, "already optimal"

    out.seek(0)
    name = field_file.name.rsplit('.', 1)[0] + '.jpg'
    return ContentFile(out.read(), name=name), old_kb, new_kb, None


class Command(BaseCommand):
    help = 'Compress existing uploaded images in-place. Always dry-run first, then add --apply.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            default=False,
            help='Actually rewrite images. Without this flag it is a safe dry run.',
        )
        parser.add_argument(
            '--schema',
            type=str,
            default=None,
            help='Tenant schema name to process (e.g. "hassan-trading"). Also processes public-schema models.',
        )
        parser.add_argument(
            '--all-tenants',
            action='store_true',
            default=False,
            help='Process all tenant schemas automatically.',
        )
        parser.add_argument(
            '--model',
            type=str,
            default=None,
            help='Only process one model: sitecar | sitecarimage | postimage | tenant | tenantheroimage',
        )

    def handle(self, *args, **options):
        apply       = options['apply']
        schema      = options['schema']
        all_tenants = options['all_tenants']
        only        = options['model'].lower() if options['model'] else None

        mode_label = 'APPLY' if apply else 'DRY RUN'
        self.stdout.write(self.style.WARNING(f'\n{mode_label} -- compress_existing_images\n'))

        if all_tenants:
            from django.apps import apps
            Tenant = apps.get_model('tenants', 'Tenant')
            connection.set_schema_to_public()
            schemas = list(Tenant.objects.values_list('schema_name', flat=True).exclude(schema_name='public'))
        elif schema:
            schemas = [schema]
        else:
            self.stdout.write(self.style.ERROR('Provide --schema=<name> or --all-tenants'))
            return

        totals = {'processed': 0, 'skipped': 0, 'errors': 0, 'saved_kb': 0}

        # ── 1. Public-schema models (Tenant, TenantHeroImage) ──────────────────
        connection.set_schema_to_public()
        self.stdout.write(self.style.WARNING('[ public schema ]'))
        self._process_targets(PUBLIC_TARGETS, only, apply, totals)

        # ── 2. Per-tenant models (SiteCar, SiteCarImage, PostImage) ────────────
        for s in schemas:
            self.stdout.write(self.style.WARNING(f'\n[ tenant schema: {s} ]'))
            connection.set_schema(s)
            self._process_targets(TENANT_TARGETS, only, apply, totals)

        # Reset to public when done
        connection.set_schema_to_public()

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Done.  processed={totals["processed"]}  skipped={totals["skipped"]}  '
            f'errors={totals["errors"]}  '
            f'{"saved" if apply else "would save"}={totals["saved_kb"]:.0f} KB '
            f'({totals["saved_kb"] / 1024:.1f} MB)'
        ))
        if not apply:
            self.stdout.write(self.style.WARNING(
                'Dry run complete. Re-run with --apply to rewrite the images.'
            ))

    def _process_targets(self, targets, only, apply, totals):
        from django.apps import apps

        for model_label, app_label, model_name, fields in targets:
            if only and model_label.lower() != only:
                continue

            self.stdout.write(self.style.HTTP_INFO(f'  >> {model_label}'))

            try:
                Model = apps.get_model(app_label, model_name)
                count = Model.objects.count()
                self.stdout.write(f'     {count} records found')
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'     Skipping -- cannot query: {e}'))
                continue

            for obj in Model.objects.iterator():
                for field_name, max_w, max_h, quality in fields:
                    field_file = getattr(obj, field_name)
                    if not field_file:
                        continue

                    cf, old_kb, new_kb, skip_reason = _compress(field_file, max_w, max_h, quality)

                    if skip_reason:
                        totals['skipped'] += 1
                        self.stdout.write(
                            f'     SKIP   {field_file.name} -- {skip_reason} ({old_kb:.0f} KB)'
                        )
                        continue

                    saved_kb = old_kb - new_kb
                    totals['saved_kb'] += saved_kb
                    totals['processed'] += 1

                    self.stdout.write(
                        f'     {"WRITE " if apply else "WOULD "} {field_file.name} '
                        f'{old_kb:.0f} KB -> {new_kb:.0f} KB  '
                        f'(save {saved_kb:.0f} KB, {saved_kb / old_kb * 100:.0f}%)'
                    )

                    if apply:
                        try:
                            field_file.delete(save=False)
                            setattr(obj, field_name, cf)
                            obj.save(update_fields=[field_name])
                        except Exception as e:
                            totals['errors'] += 1
                            self.stdout.write(self.style.ERROR(f'     ERROR saving: {e}'))

