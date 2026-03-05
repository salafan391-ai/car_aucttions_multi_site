"""
Management command to retroactively compress existing uploaded images.

Works with S3/CloudFront storage (reads image, compresses in-memory, writes back).

Usage on Heroku:
    # Dry run first — see what would be compressed (safe, no changes):
    heroku run python manage.py compress_existing_images --schema=<tenant_schema>

    # Then apply for a specific tenant:
    heroku run python manage.py compress_existing_images --schema=<tenant_schema> --apply

    # Apply for Tenant/TenantHeroImage (public schema):
    heroku run python manage.py compress_existing_images --schema=public --apply

    # Single model only:
    heroku run python manage.py compress_existing_images --schema=<tenant_schema> --apply --model sitecar
"""
from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from django.db import connection
from PIL import Image
from io import BytesIO


# (model_label, app_label, model_name, [(field_name, max_w, max_h, quality), ...])
IMAGE_TARGETS = [
    ('SiteCar',         'site_cars', 'SiteCar',        [('image',  1200, 900, 85)]),
    ('SiteCarImage',    'site_cars', 'SiteCarImage',    [('image',  1200, 900, 85)]),
    ('PostImage',       'cars',      'PostImage',       [('image',  1200, 900, 85)]),
    ('Tenant',          'tenants',   'Tenant',          [
        ('logo',                  400,  400, 85),
        ('favicon',                64,   64, 90),
        ('hero_image',           1920, 1080, 82),
        ('contact_person_photo',  400,  400, 85),
    ]),
    ('TenantHeroImage', 'tenants',   'TenantHeroImage', [('image', 1920, 1080, 82)]),
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

    # Skip if the result is not meaningfully smaller (covers already-optimal JPEGs
    # that Pillow can't compress further, even after a resize)
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
            '--model',
            type=str,
            default=None,
            help='Only process one model: sitecar | sitecarimage | postimage | tenant | tenantheroimage',
        )
        parser.add_argument(
            '--schema',
            type=str,
            default=None,
            help='django-tenants: set DB schema before querying (e.g. "public" or a tenant schema name)',
        )

    def handle(self, *args, **options):
        apply  = options['apply']
        only   = options['model'].lower() if options['model'] else None
        schema = options['schema']

        if schema:
            connection.set_schema(schema)
            self.stdout.write(self.style.WARNING(f'Schema set to: {schema}'))

        total_saved_kb  = 0
        total_processed = 0
        total_skipped   = 0
        total_errors    = 0

        mode_label = 'APPLY' if apply else 'DRY RUN'
        self.stdout.write(self.style.WARNING(f'\n{mode_label} -- compress_existing_images\n'))

        from django.apps import apps

        for model_label, app_label, model_name, fields in IMAGE_TARGETS:
            if only and model_label.lower() != only:
                continue

            self.stdout.write(self.style.HTTP_INFO(f'>> {model_label}'))

            try:
                Model = apps.get_model(app_label, model_name)
                count = Model.objects.count()
                self.stdout.write(f'  {count} records found')
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  Skipping -- cannot query: {e}'))
                continue

            for obj in Model.objects.iterator():
                for field_name, max_w, max_h, quality in fields:
                    field_file = getattr(obj, field_name)
                    if not field_file:
                        continue

                    cf, old_kb, new_kb, skip_reason = _compress(field_file, max_w, max_h, quality)

                    if skip_reason:
                        total_skipped += 1
                        self.stdout.write(
                            f'  SKIP   {field_file.name} -- {skip_reason} ({old_kb:.0f} KB)'
                        )
                        continue

                    saved_kb = old_kb - new_kb
                    total_saved_kb += saved_kb
                    total_processed += 1

                    self.stdout.write(
                        f'  {"WRITE " if apply else "WOULD "} {field_file.name} '
                        f'{old_kb:.0f} KB -> {new_kb:.0f} KB  '
                        f'(save {saved_kb:.0f} KB, {saved_kb / old_kb * 100:.0f}%)'
                    )

                    if apply:
                        try:
                            field_file.delete(save=False)
                            setattr(obj, field_name, cf)
                            obj.save(update_fields=[field_name])
                        except Exception as e:
                            total_errors += 1
                            self.stdout.write(self.style.ERROR(f'    ERROR saving: {e}'))

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Done.  processed={total_processed}  skipped={total_skipped}  '
            f'errors={total_errors}  '
            f'{"saved" if apply else "would save"}={total_saved_kb:.0f} KB '
            f'({total_saved_kb / 1024:.1f} MB)'
        ))
        if not apply:
            self.stdout.write(self.style.WARNING(
                'Dry run complete. Re-run with --apply to rewrite the images.'
            ))
