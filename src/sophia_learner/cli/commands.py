"""
Command-line interface for Sophia Learner.

This module provides the CLI entry point with subcommands for managing
the Sophia Learner system including starting/stopping the daemon,
checking status, resolving conflicts, and managing configuration.
"""

import sys
import os
import json
from pathlib import Path
from typing import Optional
import click

from sophia_learner import __version__
from sophia_learner.utils.logger import get_logger
from sophia_learner.utils.file_utils import ensure_directory


logger = get_logger(__name__)

# Default paths
DEFAULT_CONFIG_PATH = Path("/etc/sophia_learner/config.yaml")
DEFAULT_PID_FILE = Path("/var/run/sophia_learner.pid")
DEFAULT_LOG_DIR = Path("/var/log/sophia_learner")


class SophiaCLI:
    """Main CLI application context."""
    
    def __init__(self):
        self.config_path = DEFAULT_CONFIG_PATH
        self.verbose = False
        self.quiet = False
    
    def setup_logging(self):
        """Setup logging based on verbosity settings."""
        if self.quiet:
            level = "ERROR"
        elif self.verbose:
            level = "DEBUG"
        else:
            level = "INFO"
        
        # Configure basic logging for CLI
        import logging
        logging.basicConfig(
            level=getattr(logging, level),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )


# Create main CLI group
@click.group()
@click.option('--config', '-c', type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help='Path to configuration file')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
@click.option('--quiet', '-q', is_flag=True, help='Suppress non-error output')
@click.version_option(version=__version__, prog_name='sophia-learner')
@click.pass_context
def cli(ctx, config: Optional[Path], verbose: bool, quiet: bool):
    """
    Sophia Learner - Document to AI Training Data Pipeline
    
    Transform documents into AI training data through a secure, multi-stage pipeline.
    """
    # Initialize CLI context
    ctx.ensure_object(SophiaCLI)
    ctx.obj.config_path = config or DEFAULT_CONFIG_PATH
    ctx.obj.verbose = verbose
    ctx.obj.quiet = quiet
    ctx.obj.setup_logging()


# ============================================================================
# START COMMAND
# ============================================================================

@cli.command()
@click.option('--daemon', '-d', is_flag=True, help='Run as daemon (background process)')
@click.option('--pid-file', type=click.Path(path_type=Path), 
              help='PID file path (default: /var/run/sophia_learner.pid)')
@click.pass_context
def start(ctx, daemon: bool, pid_file: Optional[Path]):
    """Start the Sophia Learner daemon."""
    click.echo("Starting Sophia Learner...")
    
    # Import here to avoid circular imports
    from sophia_learner.main import run_daemon, run_interactive
    
    try:
        if daemon:
            click.echo("Running in daemon mode (background)")
            run_daemon(
                config_path=ctx.obj.config_path,
                pid_file=pid_file or DEFAULT_PID_FILE
            )
        else:
            click.echo("Running in interactive mode (foreground)")
            run_interactive(config_path=ctx.obj.config_path)
            
        click.echo("✓ Sophia Learner started successfully")
        
    except Exception as e:
        click.echo(f"✗ Failed to start Sophia Learner: {e}", err=True)
        sys.exit(1)


# ============================================================================
# STOP COMMAND
# ============================================================================

@cli.command()
@click.option('--pid-file', type=click.Path(path_type=Path),
              help='PID file path (default: /var/run/sophia_learner.pid)')
@click.option('--force', '-f', is_flag=True, help='Force stop (kill -9)')
@click.pass_context
def stop(ctx, pid_file: Optional[Path], force: bool):
    """Stop the Sophia Learner daemon."""
    click.echo("Stopping Sophia Learner...")
    
    from sophia_learner.main import stop_daemon
    
    try:
        stop_daemon(
            pid_file=pid_file or DEFAULT_PID_FILE,
            force=force
        )
        click.echo("✓ Sophia Learner stopped successfully")
        
    except Exception as e:
        click.echo(f"✗ Failed to stop Sophia Learner: {e}", err=True)
        sys.exit(1)


# ============================================================================
# STATUS COMMAND
# ============================================================================

@cli.command()
@click.option('--json', 'output_json', is_flag=True, help='Output in JSON format')
@click.option('--watch', is_flag=True, help='Watch mode (refresh every 2 seconds)')
@click.pass_context
def status(ctx, output_json: bool, watch: bool):
    """Display system status including watchers, queue, and metrics."""
    from sophia_learner.cli.status_reporter import print_status, get_status_json
    from sophia_learner.config.settings import load_config
    from sophia_learner.db.database import Database
    
    try:
        config = load_config(ctx.obj.config_path)
        
        if watch:
            import time
            try:
                while True:
                    click.clear()
                    _print_status_output(config, output_json)
                    time.sleep(2)
            except KeyboardInterrupt:
                click.echo("\nStatus monitoring stopped")
                return
        
        _print_status_output(config, output_json)
        
    except Exception as e:
        click.echo(f"✗ Failed to get status: {e}", err=True)
        sys.exit(1)


def _print_status_output(config, output_json: bool):
    """Helper to print status in appropriate format."""
    from sophia_learner.db.database import Database
    from sophia_learner.cli.status_reporter import get_status_json, print_status
    
    db = Database(config.database.path)
    
    if output_json:
        status_data = get_status_json(db, config)
        click.echo(json.dumps(status_data, indent=2, default=str))
    else:
        # This would call the actual status reporter
        click.echo("System Status:")
        click.echo("  Status reporter would display here")
        # print_status(db, watcher, scheduler)  # Would need watcher/scheduler instances


# ============================================================================
# CONFLICTS COMMAND
# ============================================================================

@cli.command()
@click.option('--list', 'list_only', is_flag=True, help='List conflicts without resolving')
@click.option('--auto', is_flag=True, help='Auto-resolve all conflicts (keep latest)')
@click.option('--resolve', type=str, help='Resolve specific conflict by ID')
@click.option('--choose', type=str, help='Version to choose when resolving')
@click.option('--export', type=click.Path(path_type=Path), help='Export conflicts to CSV')
@click.pass_context
def conflicts(ctx, list_only: bool, auto: bool, resolve: str, choose: str, export: Optional[Path]):
    """Manage version conflicts."""
    from sophia_learner.config.settings import load_config
    from sophia_learner.db.database import Database
    from sophia_learner.db.version_tracker import VersionTracker
    from sophia_learner.processor.conflict_resolver import ConflictResolver
    
    click.echo("Managing version conflicts...")
    
    try:
        config = load_config(ctx.obj.config_path)
        db = Database(config.database.path)
        version_tracker = VersionTracker(db)
        
        conflict_resolver = ConflictResolver(
            version_tracker=version_tracker,
            mode="manual" if not auto else "auto_keep_latest"
        )
        
        if export:
            from sophia_learner.cli.management_app import ConflictManagementApp
            app = ConflictManagementApp(version_tracker)
            app.export_conflict_list(export)
            click.echo(f"✓ Conflicts exported to {export}")
            return
        
        if list_only:
            pending = conflict_resolver.get_pending_conflicts()
            if not pending:
                click.echo("No pending conflicts")
                return
            
            click.echo(f"\nFound {len(pending)} pending conflicts:\n")
            for conflict in pending:
                click.echo(f"  Conflict ID: {conflict.id}")
                click.echo(f"    File Group: {conflict.file_group}")
                click.echo(f"    Versions: {', '.join(conflict.versions)}")
                click.echo(f"    Created: {conflict.created_at}")
                click.echo()
            return
        
        if resolve:
            if not choose:
                click.echo("✗ --choose VERSION required when using --resolve", err=True)
                sys.exit(1)
            
            success = conflict_resolver.resolve(int(resolve), choose)
            if success:
                click.echo(f"✓ Conflict {resolve} resolved (chose version {choose})")
            else:
                click.echo(f"✗ Failed to resolve conflict {resolve}", err=True)
                sys.exit(1)
            return
        
        if auto:
            pending = conflict_resolver.get_pending_conflicts()
            resolved = 0
            for conflict in pending:
                chosen = conflict_resolver._auto_resolve(conflict.versions)
                if conflict_resolver.resolve(conflict.id, chosen):
                    resolved += 1
            
            click.echo(f"✓ Auto-resolved {resolved} conflicts")
            return
        
        # Interactive mode
        from sophia_learner.cli.management_app import ConflictManagementApp
        app = ConflictManagementApp(version_tracker)
        resolved = app.show_conflicts()
        click.echo(f"✓ Resolved {resolved} conflicts")
        
    except Exception as e:
        click.echo(f"✗ Failed to manage conflicts: {e}", err=True)
        sys.exit(1)


# ============================================================================
# BACKFILL COMMAND
# ============================================================================

@cli.command()
@click.option('--max-files', type=int, default=1000, help='Maximum files to backfill')
@click.option('--dry-run', is_flag=True, help='Show what would be processed without actually queuing')
@click.option('--priority', type=int, default=3, help='Priority for backfilled files (1-5)')
@click.pass_context
def backfill(ctx, max_files: int, dry_run: bool, priority: int):
    """Process existing files not yet in the system."""
    from sophia_learner.config.settings import load_config
    from sophia_learner.db.database import Database
    from sophia_learner.db.file_tracker import FileTracker
    from sophia_learner.processor.version_detector import VersionDetector
    from sophia_learner.scheduler.backfill import BackfillProcessor
    
    click.echo("Running backfill...")
    
    try:
        config = load_config(ctx.obj.config_path)
        db = Database(config.database.path)
        file_tracker = FileTracker(db)
        version_detector = VersionDetector()
        backfill_processor = BackfillProcessor(file_tracker, version_detector)
        
        if dry_run:
            click.echo("DRY RUN MODE - No files will be queued\n")
            
            stats = backfill_processor.get_backfill_statistics(
                config.watcher.watch_folders,
                config.watcher.file_extensions
            )
            
            click.echo("Backfill Statistics:")
            click.echo(f"  Total files found: {stats['total_files_found']}")
            click.echo(f"  New files ready: {stats['new_files_ready']}")
            click.echo(f"  Already processed: {stats.get('processed_files', 0)}")
            click.echo(f"  Already pending: {stats.get('pending_files', 0)}")
            click.echo(f"  Failed: {stats.get('failed_files', 0)}")
            click.echo(f"  Total size: {stats.get('total_size_bytes', 0) / (1024*1024):.2f} MB")
            
            if stats.get('by_extension'):
                click.echo("\n  By extension:")
                for ext, count in stats['by_extension'].items():
                    click.echo(f"    {ext}: {count}")
        else:
            queued = backfill_processor.run_backfill(
                config.watcher.watch_folders,
                config.watcher.file_extensions,
                max_files=max_files
            )
            
            click.echo(f"✓ Backfill complete: {queued} files queued for processing")
            
    except Exception as e:
        click.echo(f"✗ Backfill failed: {e}", err=True)
        sys.exit(1)


# ============================================================================
# CONFIG COMMAND
# ============================================================================

@cli.command()
@click.option('--show', is_flag=True, help='Show current configuration')
@click.option('--validate', is_flag=True, help='Validate configuration file')
@click.option('--edit', is_flag=True, help='Edit configuration file (opens editor)')
@click.option('--get', type=str, help='Get specific configuration value (dot notation)')
@click.option('--set', type=str, help='Set configuration value (key=value format)')
@click.pass_context
def config(ctx, show: bool, validate: bool, edit: bool, get: Optional[str], set: Optional[str]):
    """View and manage configuration."""
    from sophia_learner.config.settings import load_config, reload_config
    from sophia_learner.config.schema import validate_config
    
    try:
        if edit:
            editor = os.environ.get('EDITOR', 'vi')
            click.echo(f"Opening {ctx.obj.config_path} with {editor}...")
            os.system(f"{editor} {ctx.obj.config_path}")
            return
        
        if set:
            key, value = set.split('=', 1)
            # Load config, modify, save
            # This would require YAML editing capability
            click.echo(f"Setting {key} = {value}")
            click.echo("Note: Manual config editing required for now")
            return
        
        if get:
            config = load_config(ctx.obj.config_path)
            # Parse dot notation (e.g., "watcher.hold_hours")
            parts = get.split('.')
            current = config
            for part in parts:
                if hasattr(current, part):
                    current = getattr(current, part)
                elif isinstance(current, dict):
                    current = current.get(part)
                else:
                    click.echo(f"Key not found: {get}", err=True)
                    sys.exit(1)
            
            click.echo(json.dumps(current, indent=2, default=str))
            return
        
        if validate:
            import yaml
            with open(ctx.obj.config_path, 'r') as f:
                config_dict = yaml.safe_load(f)
            
            try:
                validate_config(config_dict)
                click.echo("✓ Configuration is valid")
                
                # Also try loading with settings
                config = load_config(ctx.obj.config_path)
                click.echo("✓ Configuration loads successfully")
                
            except Exception as e:
                click.echo(f"✗ Configuration invalid: {e}", err=True)
                sys.exit(1)
            return
        
        if show:
            config = load_config(ctx.obj.config_path)
            # Pretty print config (mask sensitive values)
            config_dict = {}
            for key, value in config.__dict__.items():
                if 'password' in key.lower() or 'secret' in key.lower():
                    config_dict[key] = "******"
                else:
                    config_dict[key] = str(value)
            
            click.echo("Current Configuration:")
            click.echo(json.dumps(config_dict, indent=2, default=str))
            return
        
        # Default: show help
        click.echo(ctx.command.get_help(ctx))
        
    except Exception as e:
        click.echo(f"✗ Config operation failed: {e}", err=True)
        sys.exit(1)


# ============================================================================
# METRICS COMMAND
# ============================================================================

@cli.command()
@click.option('--period', '-p', type=click.Choice(['day', 'week', 'month', 'all']), 
              default='week', help='Time period for report')
@click.option('--output', '-o', type=click.Path(path_type=Path), 
              help='Output file for report (Markdown or JSON)')
@click.option('--json', 'output_json', is_flag=True, help='Output in JSON format')
@click.option('--live', is_flag=True, help='Live metrics monitoring')
@click.pass_context
def metrics(ctx, period: str, output: Optional[Path], output_json: bool, live: bool):
    """Display training metrics and statistics."""
    from sophia_learner.config.settings import load_config
    from sophia_learner.db.database import Database
    from sophia_learner.output.metrics import MetricsCollector
    
    click.echo(f"Generating {period}ly metrics report...")
    
    try:
        config = load_config(ctx.obj.config_path)
        db = Database(config.database.path)
        metrics_collector = MetricsCollector(db)
        
        if live:
            import time
            try:
                while True:
                    click.clear()
                    click.echo("=== Live Metrics (press Ctrl+C to stop) ===\n")
                    stats = metrics_collector.get_daily_stats()
                    click.echo(f"Today's Stats:")
                    click.echo(f"  Samples: {stats.get('total_samples', 0)}")
                    click.echo(f"  Tokens: {stats.get('total_tokens', 0):,}")
                    click.echo(f"  Avg Processing Time: {stats.get('avg_processing_time_ms', 0)} ms")
                    time.sleep(5)
            except KeyboardInterrupt:
                click.echo("\nLive monitoring stopped")
                return
        
        if output_json or (output and output.suffix == '.json'):
            stats = metrics_collector.get_period_stats(
                # Calculate appropriately for period
                None, None  # Would need proper date calculation
            )
            json_output = json.dumps(stats, indent=2, default=str)
            
            if output:
                output.write_text(json_output)
                click.echo(f"✓ Metrics saved to {output}")
            else:
                click.echo(json_output)
        else:
            report = metrics_collector.generate_report(period)
            
            if output:
                output.write_text(report)
                click.echo(f"✓ Report saved to {output}")
            else:
                click.echo("\n" + report)
        
    except Exception as e:
        click.echo(f"✗ Failed to get metrics: {e}", err=True)
        sys.exit(1)


# ============================================================================
# QUARANTINE COMMAND
# ============================================================================

@cli.command()
@click.option('--list', 'list_items', is_flag=True, help='List quarantined files')
@click.option('--cleanup', type=int, help='Clean up files older than N days')
@click.option('--restore', type=str, help='Restore file from quarantine by ID or path')
@click.option('--delete', type=str, help='Delete file from quarantine by ID or path')
@click.option('--stats', is_flag=True, help='Show quarantine statistics')
@click.pass_context
def quarantine(ctx, list_items: bool, cleanup: Optional[int], 
               restore: Optional[str], delete: Optional[str], stats: bool):
    """Manage quarantined files."""
    from sophia_learner.config.settings import load_config
    from sophia_learner.processor.quarantine import Quarantine
    
    click.echo("Managing quarantine...")
    
    try:
        config = load_config(ctx.obj.config_path)
        quarantine_mgr = Quarantine(config.security.quarantine_dir)
        
        if stats:
            stats_data = quarantine_mgr.get_quarantine_statistics()
            click.echo("\nQuarantine Statistics:")
            click.echo(f"  Incoming: {stats_data.get('incoming', 0)}")
            click.echo(f"  Processing: {stats_data.get('processing', 0)}")
            click.echo(f"  Processed: {stats_data.get('processed', 0)}")
            click.echo(f"  Rejected: {stats_data.get('rejected', 0)}")
            click.echo(f"  Conflicts: {stats_data.get('conflicts', 0)}")
            return
        
        if cleanup:
            deleted = quarantine_mgr.cleanup_old_files(days=cleanup)
            click.echo(f"✓ Cleaned up {deleted} files older than {cleanup} days")
            return
        
        if list_items:
            # List files in quarantine
            for stage in ['incoming', 'processing', 'processed', 'rejected', 'conflicts']:
                stage_dir = quarantine_mgr.quarantine_root / stage
                if stage_dir.exists():
                    files = list(stage_dir.glob('*'))
                    if files:
                        click.echo(f"\n{stage.upper()}:")
                        for f in files[:10]:  # Limit to 10
                            if f.is_file():
                                size = f.stat().st_size / 1024
                                click.echo(f"  {f.name} ({size:.1f} KB)")
                        if len(files) > 10:
                            click.echo(f"  ... and {len(files) - 10} more")
            return
        
        if restore:
            # Restore functionality would need to map from ID/path
            click.echo(f"Restoring: {restore}")
            click.echo("Note: Manual restoration required through management app")
            return
        
        if delete:
            # Delete functionality
            click.echo(f"Deleting: {delete}")
            click.echo("Note: Manual deletion required through management app")
            return
        
        # Default: show help
        click.echo(ctx.command.get_help(ctx))
        
    except Exception as e:
        click.echo(f"✗ Quarantine operation failed: {e}", err=True)
        sys.exit(1)


# ============================================================================
# Additional utility commands
# ============================================================================

@cli.command()
@click.pass_context
def validate(ctx):
    """Validate the entire system configuration and dependencies."""
    click.echo("Validating Sophia Learner system...")
    
    errors = []
    warnings = []
    
    # Check configuration
    try:
        from sophia_learner.config.settings import load_config
        config = load_config(ctx.obj.config_path)
        click.echo("✓ Configuration file loaded")
    except Exception as e:
        errors.append(f"Configuration error: {e}")
    
    # Check database
    try:
        from sophia_learner.db.database import Database
        from sophia_learner.config.settings import load_config
        config = load_config(ctx.obj.config_path)
        db = Database(config.database.path)
        db.connect()
        click.echo("✓ Database connection successful")
        db.close()
    except Exception as e:
        errors.append(f"Database error: {e}")
    
    # Check watched folders
    try:
        from sophia_learner.config.settings import load_config
        config = load_config(ctx.obj.config_path)
        for folder in config.watcher.watch_folders:
            if folder.exists():
                click.echo(f"✓ Watched folder exists: {folder}")
            else:
                warnings.append(f"Watched folder does not exist: {folder}")
    except Exception as e:
        errors.append(f"Folder check error: {e}")
    
    # Check AI backend
    try:
        from sophia_learner.config.settings import load_config
        config = load_config(ctx.obj.config_path)
        if config.ai.backend == 'ollama':
            # Check Ollama availability
            import httpx
            try:
                response = httpx.get('http://localhost:11434/api/tags', timeout=5)
                if response.status_code == 200:
                    click.echo("✓ Ollama backend available")
                else:
                    warnings.append("Ollama backend not responding")
            except:
                warnings.append("Ollama backend not reachable")
        elif config.ai.backend == 'transformers':
            try:
                import transformers
                click.echo("✓ Transformers library available")
            except ImportError:
                warnings.append("Transformers library not installed")
    except Exception as e:
        warnings.append(f"AI backend check failed: {e}")
    
    # Summary
    click.echo("\n" + "=" * 50)
    if errors:
        click.echo(f"✗ Found {len(errors)} errors:")
        for error in errors:
            click.echo(f"  - {error}")
    
    if warnings:
        click.echo(f"⚠ Found {len(warnings)} warnings:")
        for warning in warnings:
            click.echo(f"  - {warning}")
    
    if not errors and not warnings:
        click.echo("✓ System validation passed - all checks successful!")
    elif not errors:
        click.echo("⚠ System validation passed with warnings")
    else:
        click.echo("✗ System validation failed")
        sys.exit(1)


def main():
    """Main entry point for the CLI."""
    try:
        cli(obj=None)
    except KeyboardInterrupt:
        click.echo("\n\nInterrupted by user", err=True)
        sys.exit(130)
    except Exception as e:
        click.echo(f"\nUnexpected error: {e}", err=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
