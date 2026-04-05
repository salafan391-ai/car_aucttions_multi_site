import os
import boto3
from django.core.management.base import BaseCommand
from django.core.management import call_command


class Command(BaseCommand):
    help = "Generate a presigned R2 URL for the Encar CSV and run import_encar_fast"

    def handle(self, *args, **options):
        s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            region_name="auto",
        )

        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": "encar-csv", "Key": "encar/encar_cars.csv"},
            ExpiresIn=3600,
        )

        self.stdout.write("Presigned URL generated. Starting import...")
        call_command("import_encar_fast", url=url, delete_stale=True, progress=True, progress_every=5000)
