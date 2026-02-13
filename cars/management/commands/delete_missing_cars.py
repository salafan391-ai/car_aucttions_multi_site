import csv
import os
import sys
from datetime import datetime, timezone
from typing import Set, Optional

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import ApiCar

class Command(BaseCommand):
    help = 'Deletes cars from the database that are not in the current file'

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            help="Date in YYYY-MM-DD for the export folder (UTC). Defaults to today's UTC date.",
        )
        parser.add_argument(
            "--host",
            type=str,
            default=(
                os.getenv("ENCAR_HOST")
                or os.getenv("ENCAR_AUTObASE_HOST")
                or "https://autobase-berger.auto-parser.ru"
            ),
            help="Base host for autobase (env: ENCAR_HOST; fallback: ENCAR_AUTObASE_HOST, default: https://autobase-berger.auto-parser.ru)",
        )
        parser.add_argument(
            "--username",
            type=str,
            default=(
                os.getenv("ENCAR_USER")
                or os.getenv("ENCAR_AUTObASE_USER")
            ),
            help="Basic auth username (env: ENCAR_USER; fallback: ENCAR_AUTObASE_USER)",
        )
        parser.add_argument(
            "--password",
            type=str,
            default=(
                os.getenv("ENCAR_PASS")
                or os.getenv("ENCAR_AUTObASE_PASS")
            ),
            help="Basic auth password (env: ENCAR_PASS; fallback: ENCAR_AUTObASE_PASS)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without making changes",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=300,
            help="Request timeout in seconds (default: 300, 0 = no timeout)",
        )

    def _utc_today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _build_urls(self, host: str, date_str: str) -> tuple[str, str]:
        base = host.rstrip("/") + f"/encar/{date_str}"
        return (
            f"{base}/active_offer.csv",
            f"{base}/removed_offer.csv",
        )

    def _download_csv_stream(self, url: str, username: str, password: str, timeout: int) -> Optional[requests.Response]:
        try:
            self.stdout.write(f"Fetching active: {url}")
            
            # Create a session with retry logic
            session = requests.Session()
            retry_strategy = requests.adapters.Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[500, 502, 503, 504],
            )
            adapter = requests.adapters.HTTPAdapter(max_retries=retry_strategy)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            
            # Make the request
            resp = session.get(
                url,
                auth=(username, password),
                timeout=(10, timeout or None),  # (connect, read) timeouts in seconds
                stream=True,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()
            
            if not resp.encoding:
                resp.encoding = "utf-8"
                
            return resp
            
        except requests.exceptions.RequestException as e:
            self.stderr.write(self.style.ERROR(f"Error downloading {url}: {e}"))
            return None

    def _get_active_car_identifiers(self, url: str, username: str, password: str, timeout: int) -> Set[str]:
        """Extract unique car identifiers from the remote CSV file with progress updates."""
        response = self._download_csv_stream(url, username, password, timeout)
        if not response:
            raise CommandError("Failed to download CSV file")

        try:
            identifiers = set()
            total_size = int(response.headers.get('content-length', 0))
            processed_size = 0
            last_progress = 0
            error_count = 0
            max_errors = 10  # Maximum number of errors to show
            
            self.stdout.write('Processing CSV file...')
            
            # Read the header row first to get the column names
            header_line = b''
            while True:
                chunk = response.iter_content(chunk_size=1)
                char = next(chunk, b'')
                if not char or char == b'\n':
                    break
                header_line += char
            
            if not header_line:
                raise CommandError("Empty CSV file or invalid header")
            
            # Get the field names from the header
            try:
                header = header_line.decode('utf-8', errors='replace').strip().split('|')
                if 'inner_id' not in header:
                    raise CommandError("CSV file does not contain 'inner_id' column")
            except Exception as e:
                raise CommandError(f"Error parsing CSV header: {e}")
            
            # Process the rest of the file
            line_buffer = b''
            
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                
                line_buffer += chunk
                lines = line_buffer.split(b'\n')
                line_buffer = lines.pop()  # Save incomplete line for next chunk
                
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                        
                    try:
                        # Split the line by pipe and create a dict
                        values = line.decode('utf-8', errors='replace').split('|')
                        if len(header) != len(values):
                            # Skip malformed lines
                            if error_count < max_errors:
                                self.stderr.write(f'Warning: Skipping malformed line (expected {len(header)} columns, got {len(values)})')
                                error_count += 1
                            continue
                            
                        row = dict(zip(header, values))
                        if 'inner_id' in row and row['inner_id']:
                            identifiers.add(row['inner_id'])
                            
                    except Exception as e:
                        if error_count < max_errors:
                            self.stderr.write(f'Warning: Error processing line: {e}')
                            error_count += 1
                        continue
                
                # Update progress
                processed_size += len(chunk)
                if total_size > 0:
                    progress = (processed_size / total_size) * 100
                    if progress - last_progress >= 5:  # Update every 5%
                        self.stdout.write(f'Progress: {progress:.1f}% ({processed_size:,} bytes) - {len(identifiers):,} cars found')
                        last_progress = progress
            
            # Process any remaining data in the buffer
            if line_buffer.strip():
                try:
                    values = line_buffer.decode('utf-8', errors='replace').strip().split('|')
                    if len(header) == len(values):
                        row = dict(zip(header, values))
                        if 'inner_id' in row and row['inner_id']:
                            identifiers.add(row['inner_id'])
                except Exception:
                    pass  # Ignore errors in the last line
            
            if error_count >= max_errors:
                self.stderr.write(f'Warning: Suppressed {error_count - max_errors} additional errors')
                
            self.stdout.write(self.style.SUCCESS(f'Successfully processed {len(identifiers):,} car identifiers'))
            return identifiers
            
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'Error processing CSV: {e}'))
            return set()
            
        finally:
            response.close()

    def handle(self, *args, **options):
        # Get and validate parameters
        host = options["host"]
        date_str = options["date"] or self._utc_today()
        username = options["username"]
        password = options["password"]
        timeout = options["timeout"]
        dry_run = options["dry_run"]

        if not username or not password:
            raise CommandError(
                "Missing required parameters: --username/ENCAR_USER and --password/ENCAR_PASS\n"
                "Example: python manage.py delete_missing_cars --host https://autobase-berger.auto-parser.ru --username admin --password <pass> --date 2025-10-26"
            )

        # Build the URLs for the CSV files
        active_url, _ = self._build_urls(host, date_str)
        
        # Get active car identifiers from the server
        try:
            current_car_identifiers = self._get_active_car_identifiers(active_url, username, password, timeout)
            if not current_car_identifiers:
                raise CommandError("No valid car identifiers found in the CSV file")
                
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Error: {e}"))
            return

        # Get all car identifiers from the database
        self.stdout.write('Fetching existing car identifiers from database...')
        db_car_identifiers = set(ApiCar.objects.values_list('lot_number', flat=True))
        self.stdout.write(f'Found {len(db_car_identifiers):,} cars in database')

        # Find cars in DB but not in the file
        self.stdout.write('Comparing with database...')
        cars_to_delete = db_car_identifiers - current_car_identifiers
        self.stdout.write(f'Found {len(cars_to_delete):,} cars to delete')

        if not cars_to_delete:
            self.stdout.write(self.style.SUCCESS('No cars to delete. All database entries match the file.'))
            return

        self.stdout.write(self.style.WARNING(f'Found {len(cars_to_delete)} cars to delete:'))
        for car_id in sorted(cars_to_delete):
            self.stdout.write(f'  - {car_id}')

        if dry_run:
            self.stdout.write(self.style.SUCCESS('Dry run complete. No changes were made.'))
            return

        # Confirm before deleting
        confirm = input('Are you sure you want to delete these cars? (yes/no): ')
        if confirm.lower() != 'yes':
            self.stdout.write(self.style.WARNING('Operation cancelled.'))
            return

        # Perform the deletion
        try:
            with transaction.atomic():
                deleted_count, _ = ApiCar.objects.filter(lot_number__in=cars_to_delete).delete()
                self.stdout.write(self.style.SUCCESS(f'Successfully deleted {deleted_count} cars from the database.'))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'Error deleting cars: {e}'))
            return
