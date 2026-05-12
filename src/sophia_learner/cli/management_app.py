"""
Interactive conflict management for version resolution.

This module provides the ConflictManagementApp class which offers a
terminal-based interface for resolving version conflicts in document files.
"""

import csv
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Tuple

from sophia_learner.db.version_tracker import VersionTracker
from sophia_learner.db.models import ConflictRecord, FileRecord
from sophia_learner.utils.logger import get_logger
from sophia_learner.utils.file_utils import get_file_size_safe


logger = get_logger(__name__)

# Try to import rich for enhanced display
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.syntax import Syntax
    from rich.layout import Layout
    from rich.live import Live
    from rich.text import Text
    from rich import box
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    # Fallback to basic print
    Console = None


class ConflictManagementApp:
    """
    Terminal-based conflict resolution interface.
    
    This class provides an interactive TUI for users to review and resolve
    version conflicts detected during document processing.
    
    Attributes:
        version_tracker: VersionTracker for database operations
        console: Rich Console instance (if available)
    """
    
    def __init__(self, version_tracker: VersionTracker):
        """
        Initialize ConflictManagementApp with version tracker.
        
        Args:
            version_tracker: VersionTracker instance for DB operations
            
        Raises:
            ValueError: If version_tracker is None
        """
        if version_tracker is None:
            raise ValueError("version_tracker cannot be None")
        
        self.version_tracker = version_tracker
        self.console = Console() if HAS_RICH else None
        
        if not HAS_RICH:
            logger.warning("Rich library not available. Using basic display mode.")
        
        logger.info("ConflictManagementApp initialized")
    
    def show_conflicts(self) -> bool:
        """
        Display pending conflicts and prompt user for resolution.
        
        Returns:
            True if any conflicts were resolved, False otherwise
        """
        pending = self.version_tracker.get_pending_conflicts()
        
        if not pending:
            if self.console:
                self.console.print("[green]✓ No pending conflicts to resolve[/green]")
            else:
                print("No pending conflicts to resolve")
            return False
        
        if self.console:
            self.console.print(f"\n[bold yellow]Found {len(pending)} pending conflict(s)[/bold yellow]\n")
        else:
            print(f"\nFound {len(pending)} pending conflict(s)\n")
        
        resolved_count = 0
        
        for idx, conflict in enumerate(pending, 1):
            if self.console:
                self.console.print(f"[bold]Conflict {idx} of {len(pending)}[/bold]")
                self.console.print(f"File group: [cyan]{conflict.file_group}[/cyan]")
                self.console.print(f"Created: {conflict.created_at}\n")
            else:
                print(f"Conflict {idx} of {len(pending)}")
                print(f"File group: {conflict.file_group}")
                print(f"Created: {conflict.created_at}\n")
            
            # Get file records for this conflict
            file_records = self._get_file_records_for_conflict(conflict)
            
            # Display conflict details and get user choice
            chosen_version = self._display_conflict(conflict, file_records)
            
            if chosen_version:
                # Resolve the conflict
                success = self.version_tracker.resolve_conflict(
                    conflict.id, 
                    chosen_version, 
                    resolved_by="user"
                )
                
                if success:
                    resolved_count += 1
                    if self.console:
                        self.console.print(f"[green]✓ Conflict resolved (chose version {chosen_version})[/green]\n")
                    else:
                        print(f"✓ Conflict resolved (chose version {chosen_version})\n")
                else:
                    if self.console:
                        self.console.print(f"[red]✗ Failed to resolve conflict[/red]\n")
                    else:
                        print(f"✗ Failed to resolve conflict\n")
            else:
                if self.console:
                    self.console.print("[yellow]⚠ Skipped conflict (will retry later)[/yellow]\n")
                else:
                    print("⚠ Skipped conflict (will retry later)\n")
        
        if self.console:
            self.console.print(f"\n[bold]Resolved {resolved_count} of {len(pending)} conflicts[/bold]")
        else:
            print(f"\nResolved {resolved_count} of {len(pending)} conflicts")
        
        return resolved_count > 0
    
    def _get_file_records_for_conflict(self, conflict: ConflictRecord) -> List[FileRecord]:
        """
        Get FileRecord objects for all versions in a conflict.
        
        Args:
            conflict: ConflictRecord instance
            
        Returns:
            List of FileRecord objects
        """
        file_records = []
        
        for version in conflict.versions:
            # Query file records by version and file group
            # This is a simplified implementation - actual would need proper query
            file_record = self.version_tracker._get_file_by_version(
                conflict.file_group, version
            )
            if file_record:
                file_records.append(file_record)
        
        return file_records
    
    def _display_conflict(self, conflict: ConflictRecord, 
                         versions: List[FileRecord]) -> Optional[str]:
        """
        Display a single conflict and prompt for resolution.
        
        Args:
            conflict: ConflictRecord instance
            versions: List of FileRecord objects for available versions
            
        Returns:
            Chosen version string, or None if skipped
        """
        if not versions:
            if self.console:
                self.console.print("[red]No file records found for this conflict[/red]")
            else:
                print("No file records found for this conflict")
            return None
        
        if self.console and HAS_RICH:
            return self._display_conflict_rich(conflict, versions)
        else:
            return self._display_conflict_basic(conflict, versions)
    
    def _display_conflict_rich(self, conflict: ConflictRecord,
                               versions: List[FileRecord]) -> Optional[str]:
        """
        Display conflict using rich library for enhanced UI.
        
        Args:
            conflict: ConflictRecord instance
            versions: List of FileRecord objects
            
        Returns:
            Chosen version string, or None if skipped
        """
        # Create versions table
        table = Table(title="Available Versions", box=box.ROUNDED)
        table.add_column("#", style="cyan", no_wrap=True)
        table.add_column("Version", style="green", no_wrap=True)
        table.add_column("Filename", style="white")
        table.add_column("Size", style="blue")
        table.add_column("Date Modified", style="magenta")
        table.add_column("Status", style="yellow")
        
        for idx, record in enumerate(versions, 1):
            size_kb = record.size_bytes / 1024
            size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
            
            table.add_row(
                str(idx),
                record.version or "unknown",
                record.filename,
                size_str,
                record.last_modified.strftime("%Y-%m-%d %H:%M"),
                record.status
            )
        
        self.console.print(table)
        
        # Show preview option
        self.console.print("\n[dim]You can preview a file by entering its number[/dim]")
        self.console.print("[dim]Enter version number to choose, 'p' to preview, or 's' to skip[/dim]\n")
        
        while True:
            choice = Prompt.ask(
                "Select version to keep",
                choices=[str(i) for i in range(1, len(versions) + 1)] + ['p', 'P', 's', 'S', '?'],
                default="s"
            )
            
            if choice.lower() == 'p':
                # Preview a file
                preview_num = Prompt.ask(
                    "Enter file number to preview",
                    choices=[str(i) for i in range(1, len(versions) + 1)]
                )
                idx = int(preview_num) - 1
                self._preview_file(versions[idx].path, max_lines=15)
                continue
            
            elif choice.lower() == 's':
                return None
            
            elif choice == '?':
                self._show_help()
                continue
            
            else:
                idx = int(choice) - 1
                return versions[idx].version
        
        return None
    
    def _display_conflict_basic(self, conflict: ConflictRecord,
                                versions: List[FileRecord]) -> Optional[str]:
        """
        Display conflict using basic console output.
        
        Args:
            conflict: ConflictRecord instance
            versions: List of FileRecord objects
            
        Returns:
            Chosen version string, or None if skipped
        """
        print("\n" + "=" * 60)
        print(f"FILE GROUP: {conflict.file_group}")
        print("=" * 60)
        
        for idx, record in enumerate(versions, 1):
            size_kb = record.size_bytes / 1024
            size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
            
            print(f"\n[{idx}] Version: {record.version or 'unknown'}")
            print(f"    File: {record.filename}")
            print(f"    Size: {size_str}")
            print(f"    Modified: {record.last_modified.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"    Status: {record.status}")
        
        print("\nOptions:")
        print("  <number> - Choose this version")
        print("  p<number> - Preview file (e.g., p1)")
        print("  s - Skip this conflict")
        print("  ? - Show help")
        
        while True:
            choice = input("\nSelect version to keep: ").strip().lower()
            
            if choice == 's':
                return None
            
            elif choice == '?':
                self._show_help()
                continue
            
            elif choice.startswith('p'):
                try:
                    idx = int(choice[1:]) - 1
                    if 0 <= idx < len(versions):
                        self._preview_file(versions[idx].path)
                    else:
                        print(f"Invalid file number: {choice[1:]}")
                except ValueError:
                    print("Invalid preview command. Use p<number> (e.g., p1)")
                continue
            
            else:
                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(versions):
                        return versions[idx].version
                    else:
                        print(f"Invalid selection. Choose 1-{len(versions)}")
                except ValueError:
                    print(f"Invalid input. Choose a number between 1 and {len(versions)}")
    
    def _preview_file(self, file_path: Path, max_lines: int = 10) -> None:
        """
        Preview the first few lines of a file to help with resolution.
        
        Args:
            file_path: Path to file to preview
            max_lines: Maximum number of lines to show
        """
        if not file_path.exists():
            if self.console:
                self.console.print(f"[red]File not found: {file_path}[/red]")
            else:
                print(f"File not found: {file_path}")
            return
        
        if self.console and HAS_RICH:
            self.console.print(f"\n[bold cyan]Preview: {file_path.name}[/bold cyan]")
            self.console.print(f"[dim]Path: {file_path}[/dim]\n")
            
            try:
                # Try to read as text
                content = file_path.read_text(encoding='utf-8', errors='ignore')
                lines = content.split('\n')[:max_lines]
                
                # Use syntax highlighting based on extension
                ext = file_path.suffix.lower()
                lexer = self._get_lexer_for_extension(ext)
                
                preview_text = '\n'.join(lines)
                if len(lines) < len(content.split('\n')):
                    preview_text += f"\n... (truncated, {len(content.split('\n'))} total lines)"
                
                syntax = Syntax(preview_text, lexer, theme="monokai", line_numbers=True)
                self.console.print(syntax)
                
            except Exception as e:
                self.console.print(f"[red]Cannot preview file: {e}[/red]")
            
            self.console.print("")
        else:
            # Basic preview
            print(f"\n--- Preview: {file_path.name} ---")
            try:
                content = file_path.read_text(encoding='utf-8', errors='ignore')
                lines = content.split('\n')[:max_lines]
                for i, line in enumerate(lines, 1):
                    print(f"{i:3d}: {line[:100]}")
                if len(lines) < len(content.split('\n')):
                    print("... (truncated)")
                print("--- End Preview ---\n")
            except Exception as e:
                print(f"Cannot preview file: {e}\n")
    
    def _get_lexer_for_extension(self, ext: str) -> str:
        """
        Get appropriate lexer name for file extension.
        
        Args:
            ext: File extension (e.g., '.py', '.json')
            
        Returns:
            Lexer name for syntax highlighting
        """
        lexers = {
            '.py': 'python',
            '.json': 'json',
            '.yaml': 'yaml',
            '.yml': 'yaml',
            '.md': 'markdown',
            '.txt': 'text',
            '.csv': 'csv',
            '.xml': 'xml',
            '.html': 'html',
            '.js': 'javascript',
            '.java': 'java',
            '.cpp': 'cpp',
            '.c': 'c',
            '.go': 'go',
            '.rs': 'rust',
        }
        return lexers.get(ext, 'text')
    
    def _show_help(self) -> None:
        """Display help information for conflict resolution."""
        help_text = """
╔══════════════════════════════════════════════════════════════╗
║                    Conflict Resolution Help                   ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  When multiple versions of the same document are found,     ║
║  you need to choose which version to process.               ║
║                                                              ║
║  Commands:                                                   ║
║    <number>  - Keep the version with that number            ║
║    p<number> - Preview the file (e.g., p1)                  ║
║    s         - Skip this conflict (resolve later)           ║
║    ?         - Show this help                               ║
║                                                              ║
║  Tips:                                                       ║
║    - Preview files to compare content if needed             ║
║    - Usually keep the highest version number                ║
║    - Consider file size and modification date               ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
        """
        if self.console:
            self.console.print(help_text)
        else:
            print(help_text)
    
    def resolve_all_auto(self) -> int:
        """
        Automatically resolve all pending conflicts (keep latest version).
        
        Returns:
            Number of conflicts resolved
        """
        pending = self.version_tracker.get_pending_conflicts()
        
        if not pending:
            if self.console:
                self.console.print("[yellow]No pending conflicts to resolve[/yellow]")
            else:
                print("No pending conflicts to resolve")
            return 0
        
        if self.console:
            self.console.print(f"\n[bold]Auto-resolving {len(pending)} conflict(s)...[/bold]")
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                transient=True,
            ) as progress:
                task = progress.add_task("Resolving conflicts...", total=len(pending))
                
                resolved = 0
                for conflict in pending:
                    # Choose highest version
                    chosen = self._get_latest_version(conflict.versions)
                    if chosen and self.version_tracker.resolve_conflict(
                        conflict.id, chosen, resolved_by="auto"
                    ):
                        resolved += 1
                    progress.update(task, advance=1)
        else:
            resolved = 0
            for conflict in pending:
                chosen = self._get_latest_version(conflict.versions)
                if chosen and self.version_tracker.resolve_conflict(
                    conflict.id, chosen, resolved_by="auto"
                ):
                    resolved += 1
                print(f"Resolved {resolved}/{len(pending)}...")
        
        if self.console:
            self.console.print(f"\n[green]✓ Auto-resolved {resolved} conflicts[/green]")
        else:
            print(f"\n✓ Auto-resolved {resolved} conflicts")
        
        return resolved
    
    def _get_latest_version(self, versions: List[str]) -> Optional[str]:
        """
        Get the latest version from a list of version strings.
        
        Args:
            versions: List of version strings
            
        Returns:
            Latest version string, or None if empty list
        """
        if not versions:
            return None
        
        # Parse versions and get the highest
        from sophia_learner.processor.version_detector import compare_versions
        
        latest = versions[0]
        for version in versions[1:]:
            if compare_versions(version, latest) > 0:
                latest = version
        
        return latest
    
    def export_conflict_list(self, output_path: Path) -> bool:
        """
        Export pending conflicts to CSV file for external processing.
        
        Args:
            output_path: Path where CSV file should be created
            
        Returns:
            True if export successful, False otherwise
        """
        pending = self.version_tracker.get_pending_conflicts()
        
        if not pending:
            if self.console:
                self.console.print("[yellow]No pending conflicts to export[/yellow]")
            else:
                print("No pending conflicts to export")
            return False
        
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['conflict_id', 'file_group', 'versions', 'created_at', 'status']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                
                for conflict in pending:
                    writer.writerow({
                        'conflict_id': conflict.id,
                        'file_group': conflict.file_group,
                        'versions': '|'.join(conflict.versions),
                        'created_at': conflict.created_at.isoformat(),
                        'status': conflict.status
                    })
            
            if self.console:
                self.console.print(f"[green]✓ Exported {len(pending)} conflicts to {output_path}[/green]")
            else:
                print(f"✓ Exported {len(pending)} conflicts to {output_path}")
            
            return True
            
        except Exception as e:
            if self.console:
                self.console.print(f"[red]✗ Failed to export conflicts: {e}[/red]")
            else:
                print(f"✗ Failed to export conflicts: {e}")
            return False
    
    def get_conflict_summary(self) -> Dict:
        """
        Get summary statistics about current conflicts.
        
        Returns:
            Dictionary with conflict statistics
        """
        pending = self.version_tracker.get_pending_conflicts()
        
        total_files = 0
        file_groups = {}
        
        for conflict in pending:
            file_groups[conflict.file_group] = conflict.versions
            total_files += len(conflict.versions)
        
        return {
            'total_conflicts': len(pending),
            'total_versions': total_files,
            'file_groups': file_groups,
            'oldest_conflict': min((c.created_at for c in pending), default=None),
            'newest_conflict': max((c.created_at for c in pending), default=None)
        }
    
    def interactive_dashboard(self) -> None:
        """
        Launch an interactive dashboard for managing all conflicts.
        """
        if not self.console or not HAS_RICH:
            print("Interactive dashboard requires 'rich' library. Falling back to basic mode.")
            self.show_conflicts()
            return
        
        while True:
            self.console.clear()
            
            # Header
            self.console.print(Panel.fit(
                "[bold cyan]Sophia Learner - Conflict Resolution Dashboard[/bold cyan]",
                border_style="cyan"
            ))
            
            # Summary
            summary = self.get_conflict_summary()
            if summary['total_conflicts'] == 0:
                self.console.print("[green]✓ No pending conflicts![/green]\n")
                break
            
            self.console.print(f"[yellow]⚠ {summary['total_conflicts']} conflicts pending[/yellow]")
            self.console.print(f"Total versions involved: {summary['total_versions']}\n")
            
            # Options menu
            self.console.print("[bold]Options:[/bold]")
            self.console.print("  1. Review and resolve conflicts interactively")
            self.console.print("  2. Auto-resolve all conflicts (keep latest version)")
            self.console.print("  3. Export conflicts to CSV")
            self.console.print("  4. Show conflict details")
            self.console.print("  5. Exit")
            
            choice = Prompt.ask("\nSelect option", choices=["1", "2", "3", "4", "5"])
            
            if choice == "1":
                self.show_conflicts()
                Confirm.ask("\nPress Enter to continue", default=True)
            elif choice == "2":
                if Confirm.ask("Auto-resolve all conflicts?", default=False):
                    self.resolve_all_auto()
                Confirm.ask("\nPress Enter to continue", default=True)
            elif choice == "3":
                output_path = Prompt.ask("Output CSV path", default="conflicts_export.csv")
                self.export_conflict_list(Path(output_path))
                Confirm.ask("\nPress Enter to continue", default=True)
            elif choice == "4":
                self._show_detailed_conflicts(summary)
                Confirm.ask("\nPress Enter to continue", default=True)
            elif choice == "5":
                break
        
        self.console.print("\n[green]Thank you for resolving conflicts![/green]")
    
    def _show_detailed_conflicts(self, summary: Dict) -> None:
        """
        Show detailed information about all conflicts.
        
        Args:
            summary: Conflict summary dictionary
        """
        table = Table(title="Detailed Conflict List", box=box.ROUNDED)
        table.add_column("ID", style="cyan")
        table.add_column("File Group", style="white")
        table.add_column("Versions", style="green")
        table.add_column("Created", style="magenta")
        
        pending = self.version_tracker.get_pending_conflicts()
        for conflict in pending:
            table.add_row(
                str(conflict.id),
                conflict.file_group,
                ", ".join(conflict.versions),
                conflict.created_at.strftime("%Y-%m-%d %H:%M")
            )
        
        self.console.print(table)


# Example usage and testing
if __name__ == "__main__":
    import tempfile
    from sophia_learner.db.database import Database
    from sophia_learner.db.version_tracker import VersionTracker
    from sophia_learner.db.models import create_tables
    
    print("=== Conflict Management App Example ===\n")
    
    # Create test database
    with tempfile.NamedTemporaryFile(suffix='.db') as tmp:
        db_path = Path(tmp.name)
        db = Database(db_path)
        create_tables(db)
        
        # Initialize tracker
        version_tracker = VersionTracker(db)
        
        # Create test conflicts (this would normally happen automatically)
        # For demo, we'll create a mock conflict
        print("(Creating demo conflicts - would normally be detected automatically)")
        
        # Initialize app
        app = ConflictManagementApp(version_tracker)
        
        # Show summary
        summary = app.get_conflict_summary()
        print(f"\nCurrent conflicts: {summary['total_conflicts']}")
        
        # Export empty list (demo)
        app.export_conflict_list(Path("conflicts_demo.csv"))
        
        print("\nTo test with real conflicts, you would need to:")
        print("1. Have version conflicts detected by the system")
        print("2. Call app.show_conflicts() to interactively resolve them")
        print("3. Or use app.resolve_all_auto() for automatic resolution")
        
        print("\nExample usage in production:")
        print("""
        from sophia_learner.cli.management_app import ConflictManagementApp
        from sophia_learner.db.database import Database
        from sophia_learner.db.version_tracker import VersionTracker
        
        # Initialize
        db = Database('/opt/sophia_learner/data/sophia.db')
        version_tracker = VersionTracker(db)
        
        # Launch interactive dashboard
        app = ConflictManagementApp(version_tracker)
        app.interactive_dashboard()
        
        # Or just auto-resolve
        app.resolve_all_auto()
        """)
