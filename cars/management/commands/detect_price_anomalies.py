"""
Management command to detect and report price anomalies in car data
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from core.utils.price_anomaly_detector import PriceAnomalyDetector
from core.models import ApiCar
import json


class Command(BaseCommand):
    help = 'Detect cars with unrealistic prices using various statistical methods'

    def add_arguments(self, parser):
        parser.add_argument(
            '--method',
            type=str,
            default='make_model_year_groups',
            choices=['iqr', 'zscore', 'manufacturer_baseline', 'year_depreciation', 
                    'mileage_correlation', 'model_comparison', 'make_model_year_groups', 'summary'],
            help='Detection method to use (default: make_model_year_groups)'
        )
        parser.add_argument(
            '--threshold',
            type=float,
            help='Custom threshold for detection (method-specific)'
        )
        parser.add_argument(
            '--output-format',
            type=str,
            default='table',
            choices=['table', 'json', 'csv'],
            help='Output format (default: table)'
        )
        parser.add_argument(
            '--severity-filter',
            type=float,
            default=1.0,
            help='Minimum severity level to include (1.0-5.0, default: 1.0)'
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Maximum number of anomalies to display'
        )
        parser.add_argument(
            '--save-to-file',
            type=str,
            help='Save results to a file'
        )
        parser.add_argument(
            '--save-to-db',
            action='store_true',
            help='Save anomalies to the database'
        )
        parser.add_argument(
            '--overwrite',
            action='store_true',
            help='Overwrite existing anomalies in the database'
        )

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS(f'🔍 Starting price anomaly detection...')
        )
        
        # Check if we have any cars in the database
        car_count = ApiCar.objects.count()
        if car_count == 0:
            raise CommandError('No cars found in database')
        
        self.stdout.write(f'📊 Analyzing {car_count} cars in database')
        
        detector = PriceAnomalyDetector()
        
        try:
            if options['method'] == 'summary':
                results = detector.get_summary_report()
                self._display_summary_report(results, options)
            else:
                results = detector.detect_all_anomalies(
                    method=options['method'],
                    threshold=options['threshold']
                )
                self._display_results(results, options)
                
                # Save to database if requested
                if options['save_to_db']:
                    saved_count = detector.save_anomalies_to_db(
                        results, 
                        method=options['method'],
                        overwrite=options['overwrite']
                    )
                    self.stdout.write(
                        self.style.SUCCESS(f'💾 Saved {saved_count} anomalies to database')
                    )
        
        except Exception as e:
            raise CommandError(f'Error during detection: {str(e)}')

    def _display_summary_report(self, results, options):
        """Display comprehensive summary report"""
        self.stdout.write('\n' + '='*80)
        self.stdout.write(self.style.SUCCESS('📋 COMPREHENSIVE PRICE ANOMALY REPORT'))
        self.stdout.write('='*80)
        
        summary = results['summary']
        self.stdout.write(f"🎯 Total unique anomalies found: {summary['total_unique_anomalies']}")
        self.stdout.write(f"🔥 High confidence (multiple methods): {summary['high_confidence']}")
        self.stdout.write(f"🧪 Methods used: {', '.join(summary['methods_used'])}")
        
        # Display individual method results
        for method, result in results['individual_results'].items():
            if 'error' in result:
                self.stdout.write(f"\n❌ {method.upper()}: Error - {result['error']}")
                continue
                
            stats = result.get('stats', {})
            anomaly_count = stats.get('anomaly_count', 0)
            anomaly_pct = stats.get('anomaly_percentage', 0)
            
            self.stdout.write(f"\n📊 {method.upper()}: {anomaly_count} anomalies ({anomaly_pct:.1f}%)")
        
        # Display top flagged cars
        flagged_cars = results['flagged_cars']
        if flagged_cars:
            self.stdout.write('\n🚨 TOP FLAGGED CARS (multiple methods):')
            self.stdout.write('-' * 80)
            
            for i, car_data in enumerate(flagged_cars[:options.get('limit', 20)]):
                car = car_data['car']
                methods = car_data['methods']
                severity_sum = car_data['severity_sum']
                
                if severity_sum < options['severity_filter']:
                    continue
                
                method_names = [m['method'] for m in methods]
                avg_severity = severity_sum / len(methods)
                
                self.stdout.write(
                    f"{i+1:2d}. {car.manufacturer.name} {car.model.name} ({car.year}) "
                    f"- ${car.price:,} | "
                    f"Methods: {', '.join(method_names)} | "
                    f"Severity: {avg_severity:.1f}"
                )
        
        # Save to file if requested
        if options['save_to_file']:
            self._save_to_file(results, options['save_to_file'], 'json')

    def _display_results(self, results, options):
        """Display results for a single detection method"""
        if 'error' in results:
            raise CommandError(f"Detection failed: {results['error']}")
        
        anomalies = results['anomalies']
        stats = results['stats']
        
        # Filter by severity
        filtered_anomalies = [
            a for a in anomalies 
            if a.get('severity', 1.0) >= options['severity_filter']
        ]
        
        # Apply limit
        if options['limit']:
            filtered_anomalies = filtered_anomalies[:options['limit']]
        
        # Display based on format
        if options['output_format'] == 'json':
            self._display_json(filtered_anomalies, stats)
        elif options['output_format'] == 'csv':
            self._display_csv(filtered_anomalies)
        else:
            self._display_table(filtered_anomalies, stats, options['method'])
        
        # Save to file if requested
        if options['save_to_file']:
            self._save_to_file(results, options['save_to_file'], options['output_format'])

    def _display_table(self, anomalies, stats, method):
        """Display results in table format"""
        self.stdout.write('\n' + '='*100)
        self.stdout.write(self.style.SUCCESS(f'🎯 PRICE ANOMALY DETECTION RESULTS ({method.upper()})'))
        self.stdout.write('='*100)
        
        # Display statistics
        self.stdout.write(f"📊 Total cars analyzed: {stats.get('total_cars', 0)}")
        self.stdout.write(f"🚨 Anomalies found: {stats.get('anomaly_count', 0)}")
        self.stdout.write(f"📈 Anomaly rate: {stats.get('anomaly_percentage', 0):.2f}%")
        
        if method == 'iqr':
            self.stdout.write(f"📏 Price range (Q1-Q3): ${stats.get('q1', 0):,.0f} - ${stats.get('q3', 0):,.0f}")
            self.stdout.write(f"🎯 Expected range: ${stats.get('lower_bound', 0):,.0f} - ${stats.get('upper_bound', 0):,.0f}")
        elif method in ['zscore', 'manufacturer_baseline', 'model_comparison']:
            if 'mean_price' in stats:
                self.stdout.write(f"📊 Average price: ${stats['mean_price']:,.0f}")
        
        # Display anomalies
        if anomalies:
            self.stdout.write('\n🚨 DETECTED ANOMALIES:')
            self.stdout.write('-' * 100)
            self.stdout.write(f"{'#':<3} {'Manufacturer':<15} {'Model':<15} {'Year':<6} {'Price':<12} {'Type':<8} {'Severity':<8} {'Expected Range':<20}")
            self.stdout.write('-' * 100)
            
            for i, anomaly in enumerate(anomalies, 1):
                car = anomaly['car']
                severity_stars = '⭐' * min(int(anomaly.get('severity', 1)), 5)
                type_icon = '📉' if anomaly['type'] == 'too_low' else '📈'
                
                self.stdout.write(
                    f"{i:<3} "
                    f"{car.manufacturer.name[:14]:<15} "
                    f"{car.model.name[:14]:<15} "
                    f"{car.year:<6} "
                    f"${car.price:<11,} "
                    f"{type_icon}{anomaly['type'][:6]:<7} "
                    f"{severity_stars:<8} "
                    f"{anomaly.get('expected_range', 'N/A'):<20}"
                )
                
                # Additional details for some methods
                if 'z_score' in anomaly:
                    self.stdout.write(f"    Z-score: {anomaly['z_score']:.2f}")
                if 'deviation' in anomaly:
                    self.stdout.write(f"    Deviation: {anomaly['deviation']:.1%}")
        else:
            self.stdout.write('\n✅ No significant price anomalies detected!')

    def _display_json(self, anomalies, stats):
        """Display results in JSON format"""
        result = {
            'stats': stats,
            'anomalies': []
        }
        
        for anomaly in anomalies:
            car = anomaly['car']
            anomaly_data = {
                'car_id': car.id,
                'manufacturer': car.manufacturer.name,
                'model': car.model.name,
                'year': car.year,
                'price': car.price,
                'vin': car.vin,
                'type': anomaly['type'],
                'severity': anomaly.get('severity', 1.0),
                'method': anomaly.get('method', ''),
                'expected_range': anomaly.get('expected_range', '')
            }
            
            # Add method-specific data
            for key in ['z_score', 'deviation', 'manufacturer_avg', 'model_avg']:
                if key in anomaly:
                    anomaly_data[key] = anomaly[key]
            
            result['anomalies'].append(anomaly_data)
        
        self.stdout.write(json.dumps(result, indent=2))

    def _display_csv(self, anomalies):
        """Display results in CSV format"""
        import csv
        import sys
        
        if not anomalies:
            return
        
        writer = csv.writer(sys.stdout)
        
        # Header
        writer.writerow([
            'ID', 'Manufacturer', 'Model', 'Year', 'Price', 'VIN', 
            'Anomaly Type', 'Severity', 'Method', 'Expected Range'
        ])
        
        # Data rows
        for anomaly in anomalies:
            car = anomaly['car']
            writer.writerow([
                car.id,
                car.manufacturer.name,
                car.model.name,
                car.year,
                car.price,
                car.vin,
                anomaly['type'],
                round(anomaly.get('severity', 1.0), 2),
                anomaly.get('method', ''),
                anomaly.get('expected_range', '')
            ])

    def _save_to_file(self, results, filename, format_type):
        """Save results to a file"""
        try:
            with open(filename, 'w') as f:
                if format_type == 'json':
                    json.dump(results, f, indent=2, default=str)
                elif format_type == 'csv':
                    # Implement CSV saving if needed
                    pass
            
            self.stdout.write(
                self.style.SUCCESS(f'💾 Results saved to {filename}')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'❌ Failed to save to {filename}: {str(e)}')
            )