import pandas as pd
import requests
import logging
import io
from datetime import datetime
from typing import List
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Detect price outliers in car data from CSV endpoint using IQR method'

    def add_arguments(self, parser):
        parser.add_argument(
            '--group-by',
            nargs='+',
            default=['mark', 'model', 'year'],
            help='Fields to group by (default: mark model year)'
        )
        parser.add_argument(
            '--output',
            type=str,
            help='Save outliers to this CSV file (optional)'
        )
        parser.add_argument(
            '--base-url',
            default='https://autobase-berger.auto-parser.ru',
            help='Base URL for the API endpoint (default: https://autobase-berger.auto-parser.ru)'
        )
        parser.add_argument(
            '--date',
            default=datetime.now().strftime('%Y-%m-%d'),
            help='Date in YYYY-MM-DD format (default: today)'
        )
        parser.add_argument(
            '--username',
            default='admin',
            help='Username for basic auth (default: admin)'
        )
        parser.add_argument(
            '--password',
            default='01wyvD2fRpctTfm17tgx',
            help='Password for basic auth'
        )
        parser.add_argument(
            '--min-group-size',
            type=int,
            default=5,
            help='Minimum group size for analysis (default: 5)'
        )
        parser.add_argument(
            '--iqr-multiplier',
            type=float,
            default=1.5,
            help='IQR multiplier for outlier detection (default: 1.5)'
        )

    def handle(self, *args, **options):
        self.verbosity = options['verbosity']
        self.group_by = options['group_by']
        self.min_group_size = options['min_group_size']
        self.iqr_multiplier = options['iqr_multiplier']
        self.output_file = options.get('output')
        self.base_url = options['base_url'].rstrip('/')
        self.date = options['date']
        self.auth = (options['username'], options['password'])
        
        # Set up logging
        if self.verbosity > 1:
            logger.setLevel(logging.DEBUG)
            
        # Process the CSV data
        self.process_csv()

    def fetch_csv(self) -> pd.DataFrame:
        """Fetch CSV data from the endpoint."""
        url = f"{self.base_url}/encar/{self.date}/active_offer.csv"
        self.stdout.write(f"Fetching data from {url}")
        
        try:
            response = requests.get(
                url,
                auth=self.auth,
                headers={'User-Agent': 'Mozilla/5.0'},
                timeout=60  # Increased timeout for large files
            )
            response.raise_for_status()
            
            # Save raw content to a temporary file for debugging
            # with open('debug_raw_content.csv', 'wb') as f:
            #     f.write(response.content)
            
            # Try different encodings
            encodings = ['utf-8', 'cp1252', 'iso-8859-1', 'cp949', 'euc-kr']
            
            for encoding in encodings:
                try:
                    # Read CSV with pipe delimiter and specified encoding
                    df = pd.read_csv(
                        io.BytesIO(response.content),  # Use raw bytes instead of text
                        sep='|',
                        encoding=encoding,
                        low_memory=False,
                        on_bad_lines='warn'
                    )
                    
                    # If we get here, the encoding worked
                    self.stdout.write(f"Successfully read CSV with {encoding} encoding")
                    
                    # Standardize column names (lowercase and strip whitespace)
                    df.columns = [str(col).strip().lower() for col in df.columns]
                    
                    # Ensure required columns exist
                    required_cols = set(self.group_by + ['price', 'inner_id'])
                    missing_cols = [col for col in required_cols if col not in df.columns]
                    
                    if not missing_cols:
                        return df
                        
                    self.stdout.write(
                        self.style.WARNING(
                            f"Encoding {encoding} worked but missing columns: {', '.join(missing_cols)}"
                        )
                    )
                    
                except UnicodeDecodeError:
                    self.stdout.write(f"Failed to decode with {encoding} encoding")
                    continue
                except Exception as e:
                    self.stdout.write(f"Error with {encoding} encoding: {str(e)}")
                    continue
            
            # If we get here, all encodings failed
            raise ValueError(
                "Failed to decode the CSV file with any of the supported encodings. "
                "The file might be corrupted or use an unsupported encoding."
            )
                
            return df
            
        except requests.exceptions.RequestException as e:
            self.stderr.write(self.style.ERROR(f"Error fetching data: {str(e)}"))
            return pd.DataFrame()
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Error processing CSV: {str(e)}"))
            return pd.DataFrame()
    
    def detect_outliers(self, df: pd.DataFrame, group_cols: List[str], value_col: str) -> pd.DataFrame:
        """Detect outliers using IQR method within groups."""
        outliers = []
        
        for name, group in df.groupby(group_cols):
            if len(group) < self.min_group_size:
                continue
                
            # Calculate IQR
            q1 = group[value_col].quantile(0.25)
            q3 = group[value_col].quantile(0.75)
            iqr = q3 - q1
            
            # Skip if no variation in the group
            if iqr == 0:
                continue
                
            # Calculate bounds
            lower_bound = q1 - (self.iqr_multiplier * iqr)
            upper_bound = q3 + (self.iqr_multiplier * iqr)
            
            # Find outliers
            group_outliers = group[
                (group[value_col] < lower_bound) | 
                (group[value_col] > upper_bound)
            ].copy()
            
            if not group_outliers.empty:
                # Add group info
                group_key = '|'.join([str(n) for n in name]) if isinstance(name, tuple) else str(name)
                group_outliers['group_key'] = group_key
                group_outliers['group_size'] = len(group)
                group_outliers['q1'] = q1
                group_outliers['q3'] = q3
                group_outliers['iqr'] = iqr
                group_outliers['lower_bound'] = lower_bound
                group_outliers['upper_bound'] = upper_bound
                group_outliers['is_high_outlier'] = group_outliers[value_col] > upper_bound
                group_outliers['is_low_outlier'] = group_outliers[value_col] < lower_bound
                
                outliers.append(group_outliers)
        
        return pd.concat(outliers) if outliers else pd.DataFrame()
    
    def display_outliers(self, outliers: pd.DataFrame) -> None:
        """Display information about detected outliers."""
        total = len(outliers)
        high = outliers['is_high_outlier'].sum()
        low = outliers['is_low_outlier'].sum()
        
        self.stdout.write(self.style.SUCCESS(
            f"\nDetected {total} outliers ({high} high, {low} low)"
        ))
        
        # Group by the group key for reporting
        groups = outliers.groupby('group_key').agg({
            'inner_id': 'count',
            'is_high_outlier': 'sum',
            'is_low_outlier': 'sum',
            'group_size': 'first',
            'q1': 'first',
            'q3': 'first',
            'lower_bound': 'first',
            'upper_bound': 'first'
        })
        
        for group_key, row in groups.iterrows():
            self.stdout.write(f"\nGroup: {group_key}")
            self.stdout.write(f"  Group size: {row['group_size']} cars")
            self.stdout.write(f"  Outliers: {row['inner_id']} ({row['is_high_outlier']} high, {row['is_low_outlier']} low)")
            self.stdout.write(f"  Price range: [{row['q1']:,.0f} - {row['q3']:,.0f}] (IQR: {row['q3']-row['q1']:,.0f})")
            self.stdout.write(f"  Bounds: [{row['lower_bound']:,.0f} - {row['upper_bound']:,.0f}]")
            
            # Show example outliers
            group_data = outliers[outliers['group_key'] == group_key].sort_values('price', ascending=False)
            for _, row in group_data.head(3).iterrows():
                self.stdout.write(
                    f"  - ID: {row['inner_id']}, "
                    f"Price: {row['price']:,.0f}, "
                    f"Mark: {row.get('mark', 'N/A')}, "
                    f"Model: {row.get('model', 'N/A')}, "
                    f"Year: {row.get('year', 'N/A')}"
                )
    
    def process_csv(self) -> None:
        """Main processing function."""
        # Fetch and process the CSV data
        df = self.fetch_csv()
        if df.empty:
            return
            
        # Detect outliers
        outliers = self.detect_outliers(df, self.group_by, 'price')
        
        if outliers.empty:
            self.stdout.write("No outliers found in the data")
            return
            
        # Display results
        self.display_outliers(outliers)
        
        # Save to file if requested
        if self.output_file:
            try:
                # Select and rename columns for output
                output_cols = ['inner_id', 'mark', 'model', 'year', 'price', 
                             'group_key', 'is_high_outlier', 'is_low_outlier']
                output_cols = [col for col in output_cols if col in outliers.columns]
                
                outliers[output_cols].to_csv(self.output_file, index=False)
                self.stdout.write(self.style.SUCCESS(
                    f"\nSaved {len(outliers)} outliers to {self.output_file}"
                ))
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Error saving output: {str(e)}"))