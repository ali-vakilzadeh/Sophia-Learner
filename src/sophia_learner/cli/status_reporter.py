"""
Status reporting and monitoring for Sophia Learner.

This module provides functions for displaying system status, queue information,
metrics, and generating reports in various formats.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any
import json

from sophia_learner.db.database import Database
from sophia_learner.db.file_tracker import FileTracker
from sophia_learner.db.version_tracker import VersionTracker
from sophia_learner.output.metrics import MetricsCollector
from sophia_learner.utils.logger import get_logger


logger = get_logger(__name__)

# Try to import rich for enhanced display
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.layout import Layout
    from rich.live import Live
    from rich.progress import Progress, BarColumn, TextColumn
    from rich import box
    from rich.text import Text
    from rich.columns import Columns
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    Console = None

# Try to import for HTML report
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


# Global console instance
_console = Console() if HAS_RICH else None


def _get_console():
    """Get console instance (creates if needed)."""
    global _console
    if _console is None and HAS_RICH:
        _console = Console()
    return _console


def print_status(db: Database, watcher, scheduler) -> None:
    """
    Print pretty system status with tables and panels.
    
    Args:
        db: Database instance
        watcher: DirectoryWatcher instance
        scheduler: ProcessingScheduler instance
    """
    console = _get_console()
    
    if not HAS_RICH or not console:
        # Fallback to simple text output
        _print_status_simple(db, watcher, scheduler)
        return
    
    # Create layout
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main"),
        Layout(name="footer", size=3)
    )
    layout["main"].split_row(
        Layout(name="left"),
        Layout(name="right")
    )
    layout["left"].split_column(
        Layout(name="stats"),
        Layout(name="queue", ratio=2)
    )
    layout["right"].split_column(
        Layout(name="watcher"),
        Layout(name="scheduler")
    )
    
    # Gather data
    file_tracker = FileTracker(db)
    version_tracker = VersionTracker(db)
    
    # Get file statistics
    stats = file_tracker.get_statistics()
    pending_count = len(file_tracker.get_pending_files(limit=1000))
    
    # Header
    header_text = Text("📊 Sophia Learner System Status", style="bold cyan")
    layout["header"].update(
        Panel(header_text, style="cyan", box=box.HEAVY)
    )
    
    # Statistics panel
    stats_table = Table(title="📈 File Statistics", box=box.ROUNDED)
    stats_table.add_column("Status", style="cyan")
    stats_table.add_column("Count", style="green", justify="right")
    
    status_colors = {
        "pending": "yellow",
        "processing": "blue",
        "processed": "green",
        "failed": "red",
        "quarantined": "orange1",
        "conflicting": "magenta"
    }
    
    for status, color in status_colors.items():
        count = stats.get(status, 0)
        if count > 0:
            stats_table.add_row(f"[{color}]{status}[/{color}]", str(count))
    
    stats_table.add_row("[bold]Total", f"[bold]{sum(stats.values())}[/bold]")
    
    layout["stats"].update(Panel(stats_table, title="[bold]Statistics[/bold]"))
    
    # Queue panel
    if pending_count > 0:
        pending_files = file_tracker.get_pending_files(limit=10)
        queue_table = Table(title=f"⏳ Pending Files ({pending_count} total)", box=box.ROUNDED)
        queue_table.add_column("#", style="dim", width=4)
        queue_table.add_column("Filename", style="white")
        queue_table.add_column("Priority", style="cyan", justify="center")
        queue_table.add_column("Size", style="blue", justify="right")
        queue_table.add_column("Since", style="magenta")
        
        for idx, file_record in enumerate(pending_files[:10], 1):
            size_kb = file_record.size_bytes / 1024
            size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
            
            queue_table.add_row(
                str(idx),
                file_record.filename[:40],
                f"[yellow]{file_record.assigned_priority}[/yellow]",
                size_str,
                file_record.first_seen.strftime("%H:%M")
            )
        
        if pending_count > 10:
            queue_table.caption = f"… and {pending_count - 10} more files"
        
        layout["queue"].update(Panel(queue_table))
    else:
        layout["queue"].update(
            Panel("[green]✓ No pending files[/green]", title="⏳ Queue")
        )
    
    # Watcher status
    if watcher:
        watcher_table = Table(title="👁 Watched Folders", box=box.ROUNDED)
        watcher_table.add_column("Folder", style="white")
        watcher_table.add_column("Status", style="green", justify="center")
        
        # This would need actual watcher API to get watched folders
        # For now, showing placeholder
        watcher_table.add_row("/var/sophia/incoming", "✓ watching")
        
        layout["watcher"].update(Panel(watcher_table))
    
    # Scheduler status
    if scheduler:
        scheduler_table = Table(title="⏰ Scheduler", box=box.ROUNDED)
        scheduler_table.add_column("Property", style="cyan")
        scheduler_table.add_column("Value", style="white")
        
        # Get scheduler info
        can_process = scheduler.can_process_now() if hasattr(scheduler, 'can_process_now') else True
        next_window = "Unknown"
        if hasattr(scheduler, 'get_next_window_start'):
            next_start = scheduler.get_next_window_start()
            next_window = next_start.strftime("%Y-%m-%d %H:%M")
        
        scheduler_table.add_row("Processing Window", "17:00 → 07:00" if not can_process else "Now active")
        scheduler_table.add_row("Can Process Now", "✓ Yes" if can_process else "✗ No")
        scheduler_table.add_row("Next Window Start", next_window)
        
        layout["scheduler"].update(Panel(scheduler_table))
    
    # Version conflicts
    conflicts = version_tracker.get_pending_conflicts()
    if conflicts:
        conflict_text = Text(f"⚠ {len(conflicts)} version conflicts pending", style="bold yellow")
        layout["footer"].update(Panel(conflict_text))
    else:
        layout["footer"].update(Panel("[green]✓ No version conflicts[/green]"))
    
    # Render layout
    console.print(layout)


def _print_status_simple(db: Database, watcher, scheduler) -> None:
    """
    Simple text-based status output (fallback when rich not available).
    """
    print("\n" + "=" * 60)
    print("Sophia Learner System Status")
    print("=" * 60)
    
    file_tracker = FileTracker(db)
    stats = file_tracker.get_statistics()
    
    print("\n📈 File Statistics:")
    for status, count in stats.items():
        print(f"  {status}: {count}")
    print(f"  Total: {sum(stats.values())}")
    
    pending_count = len(file_tracker.get_pending_files(limit=1000))
    print(f"\n⏳ Pending files: {pending_count}")
    
    version_tracker = VersionTracker(db)
    conflicts = version_tracker.get_pending_conflicts()
    print(f"⚠ Version conflicts: {len(conflicts)}")
    
    print("\n" + "=" * 60)


def print_queue(file_tracker: FileTracker, limit: int = 20) -> None:
    """
    Show pending files in the processing queue.
    
    Args:
        file_tracker: FileTracker instance
        limit: Maximum number of files to display
    """
    console = _get_console()
    pending_files = file_tracker.get_pending_files(limit=limit)
    
    if not pending_files:
        if console:
            console.print("[green]✓ No pending files in queue[/green]")
        else:
            print("No pending files in queue")
        return
    
    if not HAS_RICH or not console:
        # Simple output
        print(f"\nPending Files ({len(pending_files)} total):")
        print("-" * 60)
        for idx, file_record in enumerate(pending_files, 1):
            size_kb = file_record.size_bytes / 1024
            size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
            print(f"{idx:3d}. {file_record.filename}")
            print(f"     Priority: {file_record.assigned_priority} | Size: {size_str} | Since: {file_record.first_seen}")
        return
    
    # Rich table output
    table = Table(title=f"📋 Pending Files Queue", box=box.ROUNDED)
    table.add_column("#", style="dim", width=4)
    table.add_column("Filename", style="white", no_wrap=False)
    table.add_column("Version", style="cyan", justify="center")
    table.add_column("Priority", style="yellow", justify="center")
    table.add_column("Size", style="blue", justify="right")
    table.add_column("First Seen", style="magenta")
    table.add_column("Last Modified", style="green")
    
    for idx, file_record in enumerate(pending_files, 1):
        size_kb = file_record.size_bytes / 1024
        size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
        
        # Priority color coding
        priority_color = {
            1: "red",
            2: "yellow",
            3: "white",
            4: "blue",
            5: "dim"
        }.get(file_record.assigned_priority, "white")
        
        table.add_row(
            str(idx),
            file_record.filename[:50],
            file_record.version or "-",
            f"[{priority_color}]{file_record.assigned_priority}[/{priority_color}]",
            size_str,
            file_record.first_seen.strftime("%Y-%m-%d %H:%M"),
            file_record.last_modified.strftime("%Y-%m-%d %H:%M")
        )
    
    console.print(table)


def print_metrics(metrics: MetricsCollector, days: int = 7) -> None:
    """
    Show training metrics and progress.
    
    Args:
        metrics: MetricsCollector instance
        days: Number of days to show
    """
    console = _get_console()
    
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days)
    
    stats = metrics.get_period_stats(start_date, end_date)
    
    if not HAS_RICH or not console:
        # Simple output
        print(f"\n📊 Training Metrics (Last {days} days)")
        print("=" * 50)
        print(f"Total Samples: {stats['totals']['samples']:,}")
        print(f"Total Tokens: {stats['totals']['tokens']:,}")
        print(f"Avg Processing Time: {stats['totals']['avg_processing_time_ms']} ms")
        print(f"\nDaily Breakdown:")
        for day_stats in stats['daily_stats']:
            print(f"  {day_stats['date']}: {day_stats['samples']} samples, {day_stats['tokens']:,} tokens")
        return
    
    # Main metrics table
    metrics_table = Table(title=f"📊 Training Metrics (Last {days} Days)", box=box.ROUNDED)
    metrics_table.add_column("Metric", style="cyan")
    metrics_table.add_column("Value", style="green", justify="right")
    
    metrics_table.add_row("Total Samples", f"{stats['totals']['samples']:,}")
    metrics_table.add_row("Total Tokens", f"{stats['totals']['tokens']:,}")
    metrics_table.add_row("Avg Processing Time", f"{stats['totals']['avg_processing_time_ms']} ms")
    
    if stats['totals']['samples'] > 0:
        tokens_per_sample = stats['totals']['tokens'] / stats['totals']['samples']
        metrics_table.add_row("Avg Tokens/Sample", f"{tokens_per_sample:.1f}")
    
    console.print(metrics_table)
    
    # Daily breakdown table
    if stats['daily_stats']:
        daily_table = Table(title="📅 Daily Breakdown", box=box.SIMPLE)
        daily_table.add_column("Date", style="magenta")
        daily_table.add_column("Samples", style="green", justify="right")
        daily_table.add_column("Tokens", style="blue", justify="right")
        daily_table.add_column("Avg Time (ms)", style="yellow", justify="right")
        
        for day_stats in stats['daily_stats']:
            daily_table.add_row(
                day_stats['date'],
                f"{day_stats['samples']:,}",
                f"{day_stats['tokens']:,}",
                f"{day_stats['avg_processing_time_ms']}"
            )
        
        console.print(daily_table)
    
    # Today's detailed stats if available
    today_stats = metrics.get_daily_stats()
    if today_stats.get('total_samples', 0) > 0:
        detail_table = Table(title="📈 Today's Details", box=box.SIMPLE)
        detail_table.add_column("Category", style="cyan")
        detail_table.add_column("Value", style="white")
        
        detail_table.add_row("Quality Score", f"{today_stats.get('avg_quality_score', 0):.2f}")
        
        for sample_type, count in today_stats.get('sample_breakdown', {}).items():
            detail_table.add_row(f"Sample Type: {sample_type}", str(count))
        
        console.print(detail_table)


def print_version_conflicts(version_tracker: VersionTracker) -> None:
    """
    Display version conflicts that need resolution.
    
    Args:
        version_tracker: VersionTracker instance
    """
    console = _get_console()
    conflicts = version_tracker.get_pending_conflicts()
    
    if not conflicts:
        if console:
            console.print("[green]✓ No version conflicts detected[/green]")
        else:
            print("No version conflicts detected")
        return
    
    if not HAS_RICH or not console:
        # Simple output
        print(f"\n⚠ Version Conflicts ({len(conflicts)}):")
        print("-" * 60)
        for conflict in conflicts:
            print(f"Conflict ID: {conflict.id}")
            print(f"  File Group: {conflict.file_group}")
            print(f"  Versions: {', '.join(conflict.versions)}")
            print(f"  Created: {conflict.created_at}")
            print()
        return
    
    # Rich table output
    table = Table(title=f"⚠ Version Conflicts ({len(conflicts)})", box=box.ROUNDED)
    table.add_column("ID", style="cyan", width=6)
    table.add_column("File Group", style="white", no_wrap=False)
    table.add_column("Versions", style="yellow")
    table.add_column("Created", style="magenta")
    table.add_column("Status", style="green")
    
    for conflict in conflicts:
        table.add_row(
            str(conflict.id),
            conflict.file_group[:50],
            ", ".join(conflict.versions),
            conflict.created_at.strftime("%Y-%m-%d %H:%M"),
            conflict.status
        )
    
    console.print(table)
    
    # Add resolution tip
    console.print("\n[dim]💡 Tip: Run 'sophia-learner conflicts' to resolve these conflicts[/dim]")


def print_watcher_status(watcher) -> None:
    """
    Show status of directory watchers.
    
    Args:
        watcher: DirectoryWatcher instance
    """
    console = _get_console()
    
    if not HAS_RICH or not console:
        print("\n👁 Watcher Status:")
        print("  (Rich library required for detailed view)")
        return
    
    # This would need actual API from DirectoryWatcher
    # For now, showing placeholder with useful information
    status_table = Table(title="👁 Directory Watcher Status", box=box.ROUNDED)
    status_table.add_column("Property", style="cyan")
    status_table.add_column("Value", style="white")
    
    status_table.add_row("Status", "[green]✓ Running[/green]")
    status_table.add_row("Watcher Type", "Watchdog (inotify)")
    status_table.add_row("Extensions", ".pdf, .docx, .xlsx, .txt")
    
    console.print(status_table)


def get_status_json(db: Database, config) -> Dict[str, Any]:
    """
    Get system status as JSON for programmatic access.
    
    Args:
        db: Database instance
        config: Settings object
        
    Returns:
        Dictionary with status information
    """
    file_tracker = FileTracker(db)
    version_tracker = VersionTracker(db)
    
    stats = file_tracker.get_statistics()
    pending_files = file_tracker.get_pending_files(limit=100)
    conflicts = version_tracker.get_pending_conflicts()
    
    return {
        "timestamp": datetime.now().isoformat(),
        "statistics": stats,
        "pending_count": len(pending_files),
        "pending_files": [
            {
                "filename": f.filename,
                "path": str(f.path),
                "priority": f.assigned_priority,
                "size_bytes": f.size_bytes,
                "first_seen": f.first_seen.isoformat()
            }
            for f in pending_files[:20]
        ],
        "conflicts": [
            {
                "id": c.id,
                "file_group": c.file_group,
                "versions": c.versions,
                "created_at": c.created_at.isoformat()
            }
            for c in conflicts
        ],
        "config": {
            "watch_folders": [str(p) for p in config.watcher.watch_folders],
            "ai_backend": config.ai.backend,
            "sandbox_mode": config.security.sandbox_mode
        }
    }


def generate_html_report(db: Database, output_path: Path) -> bool:
    """
    Generate an HTML dashboard report.
    
    Args:
        db: Database instance
        output_path: Path where HTML file should be created
        
    Returns:
        True if successful, False otherwise
    """
    file_tracker = FileTracker(db)
    version_tracker = VersionTracker(db)
    metrics = MetricsCollector(db)
    
    # Gather data
    stats = file_tracker.get_statistics()
    pending_count = len(file_tracker.get_pending_files(limit=1000))
    conflicts = version_tracker.get_pending_conflicts()
    
    # Get metrics for last 30 days
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=30)
    period_stats = metrics.get_period_stats(start_date, end_date)
    
    # Try to use pandas for better HTML tables
    if HAS_PANDAS:
        # Create DataFrames for nicer HTML
        daily_df = pd.DataFrame(period_stats['daily_stats'])
        html_tables = daily_df.to_html(index=False, classes='table table-striped')
    else:
        # Manual HTML table
        html_rows = []
        for day_stats in period_stats['daily_stats']:
            html_rows.append(f"""
                <tr>
                    <td>{day_stats['date']}</td>
                    <td>{day_stats['samples']:,}</td>
                    <td>{day_stats['tokens']:,}</td>
                    <td>{day_stats['avg_processing_time_ms']}</td>
                </tr>
            """)
        html_tables = f"""
            <table class="table">
                <thead>
                    <tr><th>Date</th><th>Samples</th><th>Tokens</th><th>Avg Time (ms)</th></tr>
                </thead>
                <tbody>
                    {''.join(html_rows)}
                </tbody>
            </table>
        """
    
    # Generate HTML
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sophia Learner Dashboard</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        .header {{
            background: white;
            border-radius: 10px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
        }}
        .header h1 {{
            color: #667eea;
            margin-bottom: 10px;
        }}
        .header p {{
            color: #666;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }}
        .stat-card {{
            background: white;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            transition: transform 0.2s;
        }}
        .stat-card:hover {{
            transform: translateY(-5px);
        }}
        .stat-card h3 {{
            color: #667eea;
            margin-bottom: 10px;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .stat-card .value {{
            font-size: 36px;
            font-weight: bold;
            color: #333;
        }}
        .stat-card .unit {{
            font-size: 14px;
            color: #999;
            margin-left: 5px;
        }}
        .section {{
            background: white;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }}
        .section h2 {{
            color: #667eea;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #f0f0f0;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #f0f0f0;
        }}
        th {{
            background-color: #f8f9fa;
            color: #667eea;
            font-weight: 600;
        }}
        .status-badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }}
        .status-pending {{ background: #fff3cd; color: #856404; }}
        .status-processed {{ background: #d4edda; color: #155724; }}
        .status-failed {{ background: #f8d7da; color: #721c24; }}
        .footer {{
            text-align: center;
            color: white;
            margin-top: 20px;
            opacity: 0.8;
        }}
        @media (max-width: 768px) {{
            .stats-grid {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 Sophia Learner Dashboard</h1>
            <p>Document to AI Training Data Pipeline - System Status Report</p>
            <p><small>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</small></p>
        </div>
        
        <div class="stats-grid">
            <div class="stat-card">
                <h3>Total Files Processed</h3>
                <div class="value">{stats.get('processed', 0):,}</div>
            </div>
            <div class="stat-card">
                <h3>Pending Files</h3>
                <div class="value">{pending_count:,}</div>
            </div>
            <div class="stat-card">
                <h3>Failed Files</h3>
                <div class="value">{stats.get('failed', 0):,}</div>
            </div>
            <div class="stat-card">
                <h3>Version Conflicts</h3>
                <div class="value">{len(conflicts)}</div>
            </div>
        </div>
        
        <div class="section">
            <h2>📊 File Statistics</h2>
            <table>
                <thead>
                    <tr><th>Status</th><th>Count</th></tr>
                </thead>
                <tbody>
                    {''.join(f'<tr><td>{status}</td><td>{count}</td></tr>' for status, count in stats.items())}
                </tbody>
            </table>
        </div>
        
        <div class="section">
            <h2>📈 Training Metrics (Last 30 Days)</h2>
            {html_tables}
            <div style="margin-top: 20px; padding: 15px; background: #f8f9fa; border-radius: 5px;">
                <strong>Summary:</strong><br>
                Total Samples: {period_stats['totals']['samples']:,}<br>
                Total Tokens: {period_stats['totals']['tokens']:,}<br>
                Average Processing Time: {period_stats['totals']['avg_processing_time_ms']} ms
            </div>
        </div>
        
        <div class="section">
            <h2>⚠ Version Conflicts</h2>
            {f'<p>No version conflicts detected.</p>' if not conflicts else f'''
            <table>
                <thead>
                    <tr><th>ID</th><th>File Group</th><th>Versions</th><th>Created</th></tr>
                </thead>
                <tbody>
                    {''.join(f'<tr><td>{c.id}</td><td>{c.file_group}</td><td>{", ".join(c.versions)}</td><td>{c.created_at.strftime("%Y-%m-%d %H:%M")}</td></tr>' for c in conflicts[:10])}
                </tbody>
            </table>
            {f'<p><small>… and {len(conflicts) - 10} more</small></p>' if len(conflicts) > 10 else ''}
            '''}
        </div>
        
        <div class="footer">
            <p>Sophia Learner - Secure Document Processing Pipeline</p>
        </div>
    </div>
</body>
</html>"""
    
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html_content, encoding='utf-8')
        logger.info(f"HTML report generated: {output_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to generate HTML report: {e}")
        return False


# Convenience function for quick status
def quick_status(db: Database) -> None:
    """
    Quick one-line status display.
    
    Args:
        db: Database instance
    """
    file_tracker = FileTracker(db)
    stats = file_tracker.get_statistics()
    pending = stats.get('pending', 0)
    processed = stats.get('processed', 0)
    failed = stats.get('failed', 0)
    
    console = _get_console()
    if console:
        console.print(f"[cyan]Sophia Learner:[/cyan] "
                     f"[green]{processed} processed[/green], "
                     f"[yellow]{pending} pending[/yellow], "
                     f"[red]{failed} failed[/red]")
    else:
        print(f"Sophia Learner: {processed} processed, {pending} pending, {failed} failed")


# Example usage
if __name__ == "__main__":
    import tempfile
    from sophia_learner.db.database import Database
    from sophia_learner.db.models import create_tables
    
    print("=== Status Reporter Examples ===\n")
    
    # Create test database
    with tempfile.NamedTemporaryFile(suffix='.db') as tmp:
        db_path = Path(tmp.name)
        db = Database(db_path)
        create_tables(db)
        
        # Test quick status
        quick_status(db)
        
        # Test status with rich output (if available)
        print("\nAttempting to display status with rich formatting...")
        try:
            print_status(db, None, None)
        except Exception as e:
            print(f"Status display: {e}")
        
        print("\nJSON status:")
        from sophia_learner.config.settings import Settings, WatcherConfig, AIConfig, SecurityConfig, OutputConfig, DatabaseConfig, LoggingConfig, ManagementConfig, SchedulerConfig
        
        # Create minimal config for testing
        config = Settings(
            watcher=WatcherConfig(watch_folders=[], file_extensions=[], hold_hours=24, backfill_on_startup=False),
            scheduler=SchedulerConfig(processing_window={}, timezone="UTC", delay_between_files_seconds=0, max_files_per_batch=0),
            security=SecurityConfig(sandbox_mode=True, max_file_size_mb=100, max_extraction_time_seconds=60, enable_virus_scan=False, virus_scan_command="", quarantine_dir=Path("/tmp"), strip_macros=True, allowed_mime_types=[]),
            ai=AIConfig(backend="ollama", prompt_template=Path("/tmp"), output_schema={}),
            output=OutputConfig(folder=Path("/tmp"), format="jsonl", max_file_size_mb=500, rotate_daily=True, compress_archive=False),
            database=DatabaseConfig(path=Path("/tmp/sophia.db"), backup_interval_hours=24, vacuum_on_startup=True),
            logging=LoggingConfig(level="INFO", log_dir=Path("/tmp"), max_log_size_mb=100, backup_count=5, json_format=False),
            management=ManagementConfig(conflict_resolution="manual", management_app_host="localhost", management_app_port=8000, notification_command=None)
        )
        status_json = get_status_json(db, config)
        print(f"  Pending: {status_json['pending_count']}")
        print(f"  Conflicts: {len(status_json['conflicts'])}")
        
        # Test HTML report
        html_path = Path("/tmp/sophia_dashboard.html")
        if generate_html_report(db, html_path):
            print(f"\n✓ HTML report generated: {html_path}")
