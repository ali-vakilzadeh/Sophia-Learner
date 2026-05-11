"""
Metrics collection and reporting for training data processing.

This module provides the MetricsCollector class which tracks processing metrics,
token usage, timing data, and generates reports for monitoring system performance.
"""

import json
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any
from collections import defaultdict
from pathlib import Path

from sophia_learner.db.database import Database
from sophia_learner.utils.logger import get_logger
from sophia_learner.utils.time_utils import format_timestamp


logger = get_logger(__name__)


class MetricsCollector:
    """
    Collect and report training data metrics.
    
    This class manages metrics storage in the database, provides counters
    for tracking operations, and generates human-readable reports.
    
    Attributes:
        db: Database connection for storing metrics
        _counters: In-memory counter cache for frequent increments
        _timings: In-memory timing cache
    """
    
    def __init__(self, db: Database):
        """
        Initialize MetricsCollector with database connection.
        
        Args:
            db: Database instance for storing metrics
            
        Raises:
            ValueError: If db is None or invalid
        """
        if db is None:
            raise ValueError("Database connection cannot be None")
        
        self.db = db
        self._counters: Dict[str, int] = defaultdict(int)
        self._timings: Dict[str, List[int]] = defaultdict(list)
        
        # Ensure metrics table exists
        self._ensure_metrics_table()
        
        logger.info("MetricsCollector initialized")
    
    def _ensure_metrics_table(self) -> None:
        """
        Ensure the metrics table exists in the database.
        
        Creates the table if it doesn't exist with the appropriate schema.
        """
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE NOT NULL,
            metric_type TEXT NOT NULL,
            metric_name TEXT NOT NULL,
            value INTEGER NOT NULL,
            metadata TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
        
        # Create index for efficient queries
        create_index_sql = """
        CREATE INDEX IF NOT EXISTS idx_metrics_date_type 
        ON metrics(date, metric_type, metric_name)
        """
        
        try:
            self.db.execute(create_table_sql, commit=True)
            self.db.execute(create_index_sql, commit=True)
            logger.debug("Metrics table ensured")
        except Exception as e:
            logger.error(f"Failed to create metrics table: {e}")
            raise
    
    def log_sample(self, sample: Dict, processing_time_ms: int, 
                   token_count: int) -> None:
        """
        Log metrics for a processed training sample.
        
        Args:
            sample: Training sample dictionary (may contain instruction, output, etc.)
            processing_time_ms: Time taken to process this sample in milliseconds
            token_count: Number of tokens in the sample
        """
        try:
            current_date = date.today()
            
            # Extract sample type if available
            sample_type = sample.get('type', 'generic')
            
            # Log sample count
            self._insert_metric(
                current_date, 
                'sample', 
                f'count_{sample_type}', 
                1
            )
            
            # Log processing time
            self._insert_metric(
                current_date,
                'timing',
                f'processing_time_ms_{sample_type}',
                processing_time_ms
            )
            
            # Log token count
            self._insert_metric(
                current_date,
                'token',
                f'token_count_{sample_type}',
                token_count
            )
            
            # Log any specific fields from sample (e.g., quality scores)
            if 'quality_score' in sample:
                self._insert_metric(
                    current_date,
                    'quality',
                    'quality_score',
                    int(sample['quality_score'] * 100),  # Store as integer percentage
                    metadata={'sample_type': sample_type}
                )
            
            logger.debug(f"Logged metrics for sample: {processing_time_ms}ms, "
                        f"{token_count} tokens")
            
        except Exception as e:
            logger.error(f"Failed to log sample metrics: {e}")
            # Don't re-raise - metrics shouldn't break processing
    
    def _insert_metric(self, metric_date: date, metric_type: str,
                      metric_name: str, value: int, 
                      metadata: Optional[Dict] = None) -> None:
        """
        Insert a metric into the database.
        
        Args:
            metric_date: Date of the metric
            metric_type: Category of metric (sample, timing, token, counter, etc.)
            metric_name: Specific metric name
            value: Numeric value
            metadata: Optional JSON-serializable metadata
        """
        sql = """
        INSERT INTO metrics (date, metric_type, metric_name, value, metadata)
        VALUES (?, ?, ?, ?, ?)
        """
        
        metadata_json = json.dumps(metadata) if metadata else None
        
        try:
            self.db.execute(sql, (metric_date.isoformat(), metric_type, 
                                  metric_name, value, metadata_json), 
                           commit=True)
        except Exception as e:
            logger.error(f"Failed to insert metric {metric_name}: {e}")
    
    def increment_counter(self, metric_name: str, increment: int = 1) -> None:
        """
        Increment a counter metric.
        
        This method is optimized for frequent increments by batching
        and flushing periodically or on close.
        
        Args:
            metric_name: Name of the counter to increment
            increment: Amount to increment by (default 1)
        """
        self._counters[metric_name] += increment
        
        # Flush counters every 100 increments to avoid memory bloat
        if len(self._counters) > 100 or sum(self._counters.values()) > 1000:
            self.flush_counters()
    
    def record_timing(self, operation: str, duration_ms: int) -> None:
        """
        Record timing for an operation.
        
        Args:
            operation: Name of the operation being timed
            duration_ms: Duration in milliseconds
        """
        self._timings[operation].append(duration_ms)
        
        # Flush timings every 50 entries to avoid memory bloat
        if len(self._timings[operation]) > 50:
            self._flush_timings_for_operation(operation)
    
    def flush_counters(self) -> None:
        """
        Flush all accumulated counters to the database.
        """
        if not self._counters:
            return
        
        current_date = date.today()
        
        for metric_name, value in self._counters.items():
            if value > 0:
                self._insert_metric(
                    current_date,
                    'counter',
                    metric_name,
                    value
                )
        
        self._counters.clear()
        logger.debug(f"Flushed counters to database")
    
    def _flush_timings_for_operation(self, operation: str) -> None:
        """
        Flush timings for a specific operation to the database.
        
        Args:
            operation: Name of the operation
        """
        if operation not in self._timings or not self._timings[operation]:
            return
        
        timings = self._timings[operation]
        current_date = date.today()
        
        # Store aggregated statistics
        if timings:
            avg_timing = sum(timings) // len(timings)
            max_timing = max(timings)
            min_timing = min(timings)
            
            self._insert_metric(
                current_date,
                'timing_aggregate',
                f'{operation}_avg_ms',
                avg_timing
            )
            self._insert_metric(
                current_date,
                'timing_aggregate',
                f'{operation}_max_ms',
                max_timing
            )
            self._insert_metric(
                current_date,
                'timing_aggregate',
                f'{operation}_min_ms',
                min_timing
            )
            self._insert_metric(
                current_date,
                'timing_aggregate',
                f'{operation}_count',
                len(timings)
            )
        
        self._timings[operation].clear()
        logger.debug(f"Flushed timings for operation: {operation}")
    
    def flush_all_timings(self) -> None:
        """
        Flush all pending timings to the database.
        """
        for operation in list(self._timings.keys()):
            self._flush_timings_for_operation(operation)
    
    def get_daily_stats(self, target_date: Optional[date] = None) -> Dict:
        """
        Get statistics for a specific day.
        
        Args:
            target_date: Date to get stats for (defaults to today)
            
        Returns:
            Dictionary with daily statistics
        """
        if target_date is None:
            target_date = date.today()
        
        date_str = target_date.isoformat()
        
        # Query for different metric types
        queries = {
            'total_samples': """
                SELECT COALESCE(SUM(value), 0) 
                FROM metrics 
                WHERE date = ? AND metric_type = 'sample' 
                AND metric_name LIKE 'count_%'
            """,
            'total_tokens': """
                SELECT COALESCE(SUM(value), 0) 
                FROM metrics 
                WHERE date = ? AND metric_type = 'token'
            """,
            'avg_processing_time': """
                SELECT COALESCE(AVG(value), 0) 
                FROM metrics 
                WHERE date = ? AND metric_type = 'timing' 
                AND metric_name LIKE 'processing_time_ms_%'
            """,
            'sample_breakdown': """
                SELECT metric_name, value 
                FROM metrics 
                WHERE date = ? AND metric_type = 'sample'
            """,
            'counters': """
                SELECT metric_name, value 
                FROM metrics 
                WHERE date = ? AND metric_type = 'counter'
            """,
            'quality_scores': """
                SELECT value, metadata 
                FROM metrics 
                WHERE date = ? AND metric_type = 'quality'
                AND metric_name = 'quality_score'
            """
        }
        
        stats = {}
        
        try:
            # Get total samples
            result = self.db.fetchone(queries['total_samples'], (date_str,))
            stats['total_samples'] = result[0] if result else 0
            
            # Get total tokens
            result = self.db.fetchone(queries['total_tokens'], (date_str,))
            stats['total_tokens'] = result[0] if result else 0
            
            # Get average processing time
            result = self.db.fetchone(queries['avg_processing_time'], (date_str,))
            stats['avg_processing_time_ms'] = round(result[0], 2) if result else 0
            
            # Get sample breakdown by type
            stats['sample_breakdown'] = {}
            results = self.db.fetchall(queries['sample_breakdown'], (date_str,))
            for row in results:
                metric_name = row[0].replace('count_', '')
                stats['sample_breakdown'][metric_name] = row[1]
            
            # Get counters
            stats['counters'] = {}
            results = self.db.fetchall(queries['counters'], (date_str,))
            for row in results:
                stats['counters'][row[0]] = row[1]
            
            # Get quality scores
            stats['avg_quality_score'] = 0
            quality_scores = []
            results = self.db.fetchall(queries['quality_scores'], (date_str,))
            for row in results:
                quality_scores.append(row[0])
            if quality_scores:
                stats['avg_quality_score'] = round(sum(quality_scores) / len(quality_scores) / 100, 2)
            
        except Exception as e:
            logger.error(f"Failed to get daily stats for {target_date}: {e}")
            stats['error'] = str(e)
        
        return stats
    
    def get_period_stats(self, start_date: date, end_date: date) -> Dict:
        """
        Get statistics for a date range.
        
        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            
        Returns:
            Dictionary with period statistics
        """
        start_str = start_date.isoformat()
        end_str = end_date.isoformat()
        
        query = """
        SELECT 
            date,
            SUM(CASE WHEN metric_type = 'sample' THEN value ELSE 0 END) as samples,
            SUM(CASE WHEN metric_type = 'token' THEN value ELSE 0 END) as tokens,
            AVG(CASE WHEN metric_type = 'timing' AND metric_name LIKE 'processing_time_ms_%' 
                THEN value ELSE NULL END) as avg_time
        FROM metrics
        WHERE date BETWEEN ? AND ?
        GROUP BY date
        ORDER BY date
        """
        
        stats = {
            'start_date': start_date,
            'end_date': end_date,
            'daily_stats': [],
            'totals': {
                'samples': 0,
                'tokens': 0,
                'avg_processing_time_ms': 0
            }
        }
        
        try:
            results = self.db.fetchall(query, (start_str, end_str))
            
            total_samples = 0
            total_tokens = 0
            total_time_sum = 0
            time_count = 0
            
            for row in results:
                day_stats = {
                    'date': row[0],
                    'samples': row[1],
                    'tokens': row[2],
                    'avg_processing_time_ms': round(row[3] or 0, 2)
                }
                stats['daily_stats'].append(day_stats)
                
                total_samples += row[1] or 0
                total_tokens += row[2] or 0
                if row[3]:
                    total_time_sum += row[3]
                    time_count += 1
            
            stats['totals']['samples'] = total_samples
            stats['totals']['tokens'] = total_tokens
            if time_count > 0:
                stats['totals']['avg_processing_time_ms'] = round(total_time_sum / time_count, 2)
            
        except Exception as e:
            logger.error(f"Failed to get period stats: {e}")
            stats['error'] = str(e)
        
        return stats
    
    def generate_report(self, period: str = "week") -> str:
        """
        Generate a human-readable Markdown report.
        
        Args:
            period: Time period for report ('day', 'week', 'month', or 'all')
            
        Returns:
            Markdown formatted report string
        """
        today = date.today()
        
        if period == 'day':
            start_date = today
            end_date = today
            period_name = "Daily"
        elif period == 'week':
            start_date = today - timedelta(days=7)
            end_date = today
            period_name = "Weekly"
        elif period == 'month':
            start_date = today - timedelta(days=30)
            end_date = today
            period_name = "Monthly"
        else:  # 'all'
            # Get earliest date from metrics
            query = "SELECT MIN(date) FROM metrics"
            result = self.db.fetchone(query)
            start_date = datetime.strptime(result[0], '%Y-%m-%d').date() if result and result[0] else today
            end_date = today
            period_name = "Complete History"
        
        stats = self.get_period_stats(start_date, end_date)
        
        # Build Markdown report
        report_lines = [
            f"# Sophia Learner - {period_name} Training Report",
            f"**Period:** {start_date.isoformat()} to {end_date.isoformat()}",
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## Summary",
            f"- **Total Samples Processed:** {stats['totals']['samples']:,}",
            f"- **Total Tokens Processed:** {stats['totals']['tokens']:,}",
            f"- **Average Processing Time:** {stats['totals']['avg_processing_time_ms']} ms/sample",
            "",
            "## Daily Breakdown",
            "| Date | Samples | Tokens | Avg Time (ms) |",
            "|------|---------|--------|---------------|"
        ]
        
        for day_stats in stats['daily_stats']:
            report_lines.append(
                f"| {day_stats['date']} | {day_stats['samples']:,} | "
                f"{day_stats['tokens']:,} | {day_stats['avg_processing_time_ms']} |"
            )
        
        # Add today's detailed stats
        today_stats = self.get_daily_stats(today)
        if today_stats.get('total_samples', 0) > 0:
            report_lines.extend([
                "",
                "## Today's Detailed Statistics",
                f"- **Total Samples:** {today_stats['total_samples']}",
                f"- **Total Tokens:** {today_stats['total_tokens']:,}",
                f"- **Average Processing Time:** {today_stats['avg_processing_time_ms']} ms",
                f"- **Average Quality Score:** {today_stats.get('avg_quality_score', 0)}",
                "",
                "### Sample Breakdown by Type",
            ])
            
            for sample_type, count in today_stats.get('sample_breakdown', {}).items():
                report_lines.append(f"- **{sample_type}:** {count}")
            
            if today_stats.get('counters'):
                report_lines.extend([
                    "",
                    "### Operation Counters",
                ])
                for counter_name, value in today_stats['counters'].items():
                    report_lines.append(f"- **{counter_name}:** {value}")
        
        # Add performance insights
        report_lines.extend([
            "",
            "## Performance Insights",
        ])
        
        if stats['totals']['samples'] > 0:
            tokens_per_sample = stats['totals']['tokens'] / stats['totals']['samples']
            report_lines.append(f"- **Average Tokens per Sample:** {tokens_per_sample:.1f}")
            
            if stats['totals']['avg_processing_time_ms'] > 0:
                samples_per_second = 1000 / stats['totals']['avg_processing_time_ms']
                report_lines.append(f"- **Processing Rate:** {samples_per_second:.2f} samples/second")
        
        # Add footer
        report_lines.extend([
            "",
            "---",
            "*Report generated by Sophia Learner Metrics System*"
        ])
        
        return "\n".join(report_lines)
    
    def export_report_to_file(self, period: str = "week", 
                             output_path: Optional[Path] = None) -> Path:
        """
        Generate report and save to file.
        
        Args:
            period: Time period for report ('day', 'week', 'month', 'all')
            output_path: Optional custom output path
            
        Returns:
            Path to the generated report file
        """
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = Path(f"metrics_report_{period}_{timestamp}.md")
        
        report = self.generate_report(period)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(report)
        
        logger.info(f"Report exported to {output_path}")
        return output_path
    
    def cleanup_old_metrics(self, days_to_keep: int = 90) -> int:
        """
        Delete metrics older than specified days.
        
        Args:
            days_to_keep: Number of days to keep (metrics older than this are deleted)
            
        Returns:
            Number of rows deleted
        """
        cutoff_date = date.today() - timedelta(days=days_to_keep)
        cutoff_str = cutoff_date.isoformat()
        
        # Flush any pending metrics before cleanup
        self.flush_counters()
        self.flush_all_timings()
        
        sql = "DELETE FROM metrics WHERE date < ?"
        
        try:
            self.db.execute(sql, (cutoff_str,), commit=True)
            
            # Get count of deleted rows (requires separate query for SQLite)
            count_sql = "SELECT changes()"
            result = self.db.fetchone(count_sql)
            deleted_count = result[0] if result else 0
            
            logger.info(f"Cleaned up {deleted_count} old metric records "
                       f"(older than {days_to_keep} days)")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup old metrics: {e}")
            return 0
    
    def close(self) -> None:
        """
        Close the metrics collector and flush all pending data.
        """
        self.flush_counters()
        self.flush_all_timings()
        logger.info("MetricsCollector closed")


# Example usage
if __name__ == "__main__":
    from sophia_learner.db.database import Database
    from pathlib import Path
    
    # Initialize database
    db_path = Path("/tmp/sophia_metrics_test.db")
    db = Database(db_path)
    
    # Create metrics collector
    collector = MetricsCollector(db)
    
    # Log some sample metrics
    sample = {
        "instruction": "What is AI?",
        "output": "AI is artificial intelligence.",
        "type": "qa",
        "quality_score": 0.95
    }
    collector.log_sample(sample, processing_time_ms=150, token_count=50)
    
    # Increment counters
    collector.increment_counter("files_processed")
    collector.increment_counter("files_processed")
    collector.increment_counter("ai_calls", 3)
    
    # Record timings
    collector.record_timing("ollama_api_call", 1200)
    collector.record_timing("ollama_api_call", 1100)
    collector.record_timing("pdf_parsing", 500)
    
    # Flush counters
    collector.flush_counters()
    collector.flush_all_timings()
    
    # Get daily stats
    daily_stats = collector.get_daily_stats()
    print(f"Daily stats: {daily_stats}")
    
    # Generate report
    report = collector.generate_report("day")
    print(report)
    
    # Export report
    collector.export_report_to_file("day")
    
    # Cleanup
    collector.close()
    db.close()
