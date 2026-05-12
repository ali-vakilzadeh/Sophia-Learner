"""
System cron integration for external scheduling.

This module provides the CronManager class which interfaces with the system
crontab to schedule, manage, and remove cron jobs for the Sophia Learner system.
"""

import subprocess
import re
import tempfile
import os
from pathlib import Path
from typing import List, Optional, Dict, Tuple
from datetime import datetime

from sophia_learner.utils.logger import get_logger


logger = get_logger(__name__)

# Try to import python-crontab for better functionality
try:
    from crontab import CronTab
    HAS_CRONTAB_LIB = True
except ImportError:
    HAS_CRONTAB_LIB = False
    logger.debug("python-crontab not available, using subprocess fallback")


class CronManager:
    """
    Manage system cron jobs for Sophia Learner scheduling.
    
    This class provides an interface to the system crontab for adding,
    removing, and listing cron jobs. It can use either the python-crontab
    library (if available) or fall back to direct subprocess calls.
    
    Attributes:
        user: Username for crontab operations (None for current user)
        use_crontab_lib: Whether to use python-crontab library
    """
    
    # Pattern for identifying Sophia Learner cron jobs
    SOPHIA_COMMENT = "# Sophia Learner Scheduled Job"
    JOB_IDENTIFIER = "sophia-learner"
    
    # Common schedule format patterns
    SCHEDULE_PATTERNS = {
        'minute': r'^(\*|[0-5]?\d)(/\d+)?$',
        'hour': r'^(\*|[01]?\d|2[0-3])(/\d+)?$',
        'day': r'^(\*|[1-9]|[12]\d|3[01])(/\d+)?$',
        'month': r'^(\*|[1-9]|1[0-2])(/\d+)?$',
        'weekday': r'^(\*|[0-6])(/\d+)?$'
    }
    
    def __init__(self, user: Optional[str] = None):
        """
        Initialize CronManager.
        
        Args:
            user: Username for crontab (None for current user)
        """
        self.user = user
        self.use_crontab_lib = HAS_CRONTAB_LIB
        
        if self.use_crontab_lib:
            logger.debug("Using python-crontab library for cron management")
        else:
            logger.debug("Using subprocess fallback for cron management")
    
    def is_cron_available(self) -> bool:
        """
        Check if cron/crontab is available on the system.
        
        Returns:
            True if crontab command exists and is executable, False otherwise
        """
        try:
            # Check if crontab command exists
            result = subprocess.run(
                ['which', 'crontab'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                logger.warning("crontab command not found in PATH")
                return False
            
            # Try to list crontab (this also checks permissions)
            cmd = ['crontab', '-l']
            if self.user:
                cmd = ['sudo', 'crontab', '-u', self.user, '-l']
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5
            )
            
            # crontab -l returns 0 even if no crontab exists (with empty output)
            # It returns non-zero only if command fails or user has no crontab
            # For new users, we consider cron available
            available = result.returncode == 0 or "no crontab for" in result.stderr
            
            if available:
                logger.debug("Cron is available on this system")
            else:
                logger.warning(f"Cron may not be available: {result.stderr}")
            
            return available
            
        except subprocess.TimeoutExpired:
            logger.error("Timeout checking cron availability")
            return False
        except Exception as e:
            logger.error(f"Error checking cron availability: {e}")
            return False
    
    def validate_schedule(self, schedule: str) -> bool:
        """
        Validate a cron schedule string.
        
        Args:
            schedule: Cron schedule string (e.g., "0 17 * * *")
            
        Returns:
            True if schedule format is valid, False otherwise
        """
        # Split schedule into 5 fields
        parts = schedule.strip().split()
        
        if len(parts) != 5:
            logger.warning(f"Invalid schedule format: expected 5 fields, got {len(parts)}")
            return False
        
        # Validate each field
        fields = ['minute', 'hour', 'day', 'month', 'weekday']
        for field_name, field_value in zip(fields, parts):
            pattern = self.SCHEDULE_PATTERNS.get(field_name)
            if pattern and not re.match(pattern, field_value):
                # Special case: @daily, @hourly shorthand
                if schedule.startswith('@'):
                    shorthands = ['@yearly', '@annually', '@monthly', '@weekly', 
                                 '@daily', '@midnight', '@hourly', '@reboot']
                    if schedule in shorthands:
                        return True
                
                logger.warning(f"Invalid {field_name} value: {field_value}")
                return False
        
        return True
    
    def _format_cron_line(self, command: str, schedule: str) -> str:
        """
        Format a cron job line with comment and identifier.
        
        Args:
            command: Command to execute
            schedule: Cron schedule string
            
        Returns:
            Formatted cron line
        """
        return f"{schedule} {command} {self.SOPHIA_COMMENT} #{self.JOB_IDENTIFIER}"
    
    def _parse_cron_line(self, line: str) -> Optional[Dict]:
        """
        Parse a cron line to extract schedule and command.
        
        Args:
            line: Cron line to parse
            
        Returns:
            Dictionary with 'schedule' and 'command' keys, or None if not a Sophia job
        """
        line = line.strip()
        
        # Check if this is a Sophia Learner job
        if self.SOPHIA_COMMENT not in line and self.JOB_IDENTIFIER not in line:
            return None
        
        # Remove the comment and identifier
        line = line.replace(self.SOPHIA_COMMENT, '').replace(f'#{self.JOB_IDENTIFIER}', '')
        line = line.strip()
        
        # Split into schedule and command (schedule is first 5 fields)
        parts = line.split()
        if len(parts) < 6:
            return None
        
        schedule = ' '.join(parts[:5])
        command = ' '.join(parts[5:])
        
        return {
            'schedule': schedule,
            'command': command,
            'full_line': line
        }
    
    def sync_with_cron(self, command: str, schedule: str) -> bool:
        """
        Add or update a cron job for Sophia Learner.
        
        Args:
            command: Full command to execute (e.g., "sophia-learner start")
            schedule: Cron schedule string (e.g., "0 17 * * *" or "@daily")
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_cron_available():
            logger.error("Cron not available, cannot sync job")
            return False
        
        if not self.validate_schedule(schedule):
            logger.error(f"Invalid schedule format: {schedule}")
            return False
        
        logger.info(f"Syncing cron job: {schedule} {command}")
        
        if self.use_crontab_lib:
            return self._sync_with_crontab_lib(command, schedule)
        else:
            return self._sync_with_subprocess(command, schedule)
    
    def _sync_with_crontab_lib(self, command: str, schedule: str) -> bool:
        """
        Sync cron job using python-crontab library.
        
        Args:
            command: Command to execute
            schedule: Cron schedule string
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Create CronTab instance
            cron = CronTab(user=self.user) if self.user else CronTab()
            
            # Remove existing Sophia Learner jobs
            cron.remove_all(comment=self.SOPHIA_COMMENT)
            
            # Create new job
            job = cron.new(command=command, comment=self.SOPHIA_COMMENT)
            
            # Set schedule
            if schedule.startswith('@'):
                # Handle shorthand schedules
                if schedule == '@reboot':
                    job.every_reboot()
                elif schedule == '@hourly':
                    job.hourly()
                elif schedule == '@daily' or schedule == '@midnight':
                    job.daily()
                elif schedule == '@weekly':
                    job.weekly()
                elif schedule == '@monthly':
                    job.monthly()
                elif schedule == '@yearly' or schedule == '@annually':
                    job.yearly()
                else:
                    logger.error(f"Unsupported shorthand schedule: {schedule}")
                    return False
            else:
                # Parse standard cron schedule
                parts = schedule.split()
                if len(parts) == 5:
                    minute, hour, day, month, weekday = parts
                    job.setall(minute, hour, day, month, weekday)
            
            # Write to crontab
            cron.write()
            
            logger.info(f"Cron job synced successfully: {schedule} {command}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to sync cron job with python-crontab: {e}")
            return False
    
    def _sync_with_subprocess(self, command: str, schedule: str) -> bool:
        """
        Sync cron job using subprocess calls to crontab.
        
        Args:
            command: Command to execute
            schedule: Cron schedule string
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Get current crontab
            current_jobs = self._get_crontab_content()
            
            # Remove existing Sophia Learner jobs
            filtered_jobs = [
                line for line in current_jobs 
                if self.SOPHIA_COMMENT not in line and self.JOB_IDENTIFIER not in line
            ]
            
            # Add new job
            new_line = self._format_cron_line(command, schedule)
            filtered_jobs.append(new_line)
            
            # Write back to crontab
            success = self._set_crontab_content(filtered_jobs)
            
            if success:
                logger.info(f"Cron job synced successfully: {schedule} {command}")
            else:
                logger.error("Failed to write crontab")
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to sync cron job: {e}")
            return False
    
    def _get_crontab_content(self) -> List[str]:
        """
        Get current crontab content.
        
        Returns:
            List of crontab lines
        """
        try:
            cmd = ['crontab', '-l']
            if self.user:
                cmd = ['sudo', 'crontab', '-u', self.user, '-l']
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                return [line for line in result.stdout.split('\n') if line.strip()]
            elif "no crontab for" in result.stderr:
                return []
            else:
                logger.error(f"Failed to get crontab: {result.stderr}")
                return []
                
        except subprocess.TimeoutExpired:
            logger.error("Timeout getting crontab")
            return []
        except Exception as e:
            logger.error(f"Error getting crontab: {e}")
            return []
    
    def _set_crontab_content(self, lines: List[str]) -> bool:
        """
        Set crontab content.
        
        Args:
            lines: List of crontab lines
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Create temporary file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.cron', delete=False) as f:
                f.write('\n'.join(lines))
                f.write('\n')
                temp_path = f.name
            
            # Install crontab from temp file
            cmd = ['crontab', temp_path]
            if self.user:
                cmd = ['sudo', 'crontab', '-u', self.user, temp_path]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            # Clean up temp file
            os.unlink(temp_path)
            
            if result.returncode == 0:
                return True
            else:
                logger.error(f"Failed to set crontab: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Error setting crontab: {e}")
            return False
    
    def remove_cron_job(self, command: str) -> bool:
        """
        Remove Sophia Learner cron job.
        
        Args:
            command: Command to remove (can be partial match)
            
        Returns:
            True if job was removed, False otherwise
        """
        if not self.is_cron_available():
            logger.error("Cron not available, cannot remove job")
            return False
        
        logger.info(f"Removing cron job for command: {command}")
        
        if self.use_crontab_lib:
            return self._remove_with_crontab_lib(command)
        else:
            return self._remove_with_subprocess(command)
    
    def _remove_with_crontab_lib(self, command: str) -> bool:
        """
        Remove cron job using python-crontab library.
        
        Args:
            command: Command to remove
            
        Returns:
            True if successful, False otherwise
        """
        try:
            cron = CronTab(user=self.user) if self.user else CronTab()
            
            # Find and remove jobs
            removed = False
            for job in cron.find_command(command):
                if job.comment == self.SOPHIA_COMMENT or self.JOB_IDENTIFIER in str(job):
                    cron.remove(job)
                    removed = True
            
            if removed:
                cron.write()
                logger.info(f"Removed cron job for command: {command}")
            else:
                logger.debug(f"No cron job found for command: {command}")
            
            return removed
            
        except Exception as e:
            logger.error(f"Failed to remove cron job: {e}")
            return False
    
    def _remove_with_subprocess(self, command: str) -> bool:
        """
        Remove cron job using subprocess.
        
        Args:
            command: Command to remove
            
        Returns:
            True if successful, False otherwise
        """
        try:
            current_jobs = self._get_crontab_content()
            
            # Filter out matching jobs
            filtered_jobs = []
            removed = False
            
            for line in current_jobs:
                if command in line and (self.SOPHIA_COMMENT in line or self.JOB_IDENTIFIER in line):
                    removed = True
                    logger.debug(f"Removing cron line: {line}")
                else:
                    filtered_jobs.append(line)
            
            if removed:
                success = self._set_crontab_content(filtered_jobs)
                if success:
                    logger.info(f"Removed cron job for command: {command}")
                return success
            else:
                logger.debug(f"No cron job found for command: {command}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to remove cron job: {e}")
            return False
    
    def get_current_cron_jobs(self) -> List[str]:
        """
        Get list of all Sophia Learner cron jobs.
        
        Returns:
            List of command strings for Sophia Learner cron jobs
        """
        if not self.is_cron_available():
            logger.error("Cron not available, cannot get jobs")
            return []
        
        jobs = []
        
        if self.use_crontab_lib:
            try:
                cron = CronTab(user=self.user) if self.user else CronTab()
                
                for job in cron:
                    if job.comment == self.SOPHIA_COMMENT or self.JOB_IDENTIFIER in str(job):
                        # Format: "schedule command"
                        schedule = f"{job.minute} {job.hour} {job.day} {job.month} {job.dow}"
                        jobs.append(f"{schedule} {job.command}")
                        
            except Exception as e:
                logger.error(f"Failed to get cron jobs with python-crontab: {e}")
        else:
            try:
                crontab_lines = self._get_crontab_content()
                
                for line in crontab_lines:
                    if self.SOPHIA_COMMENT in line or self.JOB_IDENTIFIER in line:
                        parsed = self._parse_cron_line(line)
                        if parsed:
                            jobs.append(f"{parsed['schedule']} {parsed['command']}")
                            
            except Exception as e:
                logger.error(f"Failed to get cron jobs: {e}")
        
        logger.debug(f"Found {len(jobs)} Sophia Learner cron jobs")
        return jobs
    
    def get_all_cron_jobs(self) -> List[str]:
        """
        Get all cron jobs (not just Sophia Learner ones).
        
        Returns:
            List of all cron job command strings
        """
        if not self.is_cron_available():
            return []
        
        jobs = []
        
        if self.use_crontab_lib:
            try:
                cron = CronTab(user=self.user) if self.user else CronTab()
                for job in cron:
                    schedule = f"{job.minute} {job.hour} {job.day} {job.month} {job.dow}"
                    jobs.append(f"{schedule} {job.command}")
            except Exception as e:
                logger.error(f"Failed to get all cron jobs: {e}")
        else:
            lines = self._get_crontab_content()
            for line in lines:
                if line and not line.startswith('#'):
                    jobs.append(line)
        
        return jobs
    
    def clear_all_sophia_jobs(self) -> int:
        """
        Remove all Sophia Learner cron jobs.
        
        Returns:
            Number of jobs removed
        """
        jobs = self.get_current_cron_jobs()
        
        if not jobs:
            logger.debug("No Sophia Learner cron jobs to remove")
            return 0
        
        removed_count = 0
        for job in jobs:
            # Extract command from the job string (after schedule)
            parts = job.split()
            if len(parts) >= 6:
                command = ' '.join(parts[5:])
                if self.remove_cron_job(command):
                    removed_count += 1
        
        logger.info(f"Removed {removed_count} Sophia Learner cron jobs")
        return removed_count


# Convenience functions
def setup_scheduled_processing(command: str, hour: int = 17, minute: int = 0) -> bool:
    """
    Setup a daily scheduled processing job.
    
    Args:
        command: Command to execute
        hour: Hour of day (0-23)
        minute: Minute of hour (0-59)
        
    Returns:
        True if successful, False otherwise
    """
    manager = CronManager()
    schedule = f"{minute} {hour} * * *"
    return manager.sync_with_cron(command, schedule)


def setup_overnight_processing(command: str) -> bool:
    """
    Setup overnight processing job (2 AM daily).
    
    Args:
        command: Command to execute
        
    Returns:
        True if successful, False otherwise
    """
    return setup_scheduled_processing(command, hour=2, minute=0)


def disable_scheduled_processing(command: str) -> bool:
    """
    Disable scheduled processing job.
    
    Args:
        command: Command to remove
        
    Returns:
        True if successful, False otherwise
    """
    manager = CronManager()
    return manager.remove_cron_job(command)


# Example usage and testing
if __name__ == "__main__":
    print("=== CronManager Example ===")
    
    manager = CronManager()
    
    # Check if cron is available
    print(f"Cron available: {manager.is_cron_available()}")
    
    if manager.is_cron_available():
        # Test schedule validation
        print("\n=== Schedule Validation ===")
        test_schedules = [
            "0 17 * * *",      # Daily at 5 PM
            "*/15 * * * *",    # Every 15 minutes
            "0 2 * * *",       # Daily at 2 AM
            "0 9-17 * * 1-5",  # Hourly during business hours
            "@daily",          # Daily shorthand
            "@reboot",         # At reboot
            "invalid",         # Invalid
        ]
        
        for schedule in test_schedules:
            valid = manager.validate_schedule(schedule)
            print(f"  {schedule:20} -> {'✓' if valid else '✗'}")
        
        # Test cron job management
        test_command = "sophia-learner backfill"
        test_schedule = "0 2 * * *"  # 2 AM daily
        
        print(f"\n=== Adding Cron Job ===")
        print(f"Command: {test_command}")
        print(f"Schedule: {test_schedule}")
        
        if manager.sync_with_cron(test_command, test_schedule):
            print("✓ Cron job added successfully")
        else:
            print("✗ Failed to add cron job")
        
        # List current jobs
        print(f"\n=== Current Sophia Learner Jobs ===")
        jobs = manager.get_current_cron_jobs()
        for job in jobs:
            print(f"  {job}")
        
        # Remove the test job
        print(f"\n=== Removing Cron Job ===")
        if manager.remove_cron_job(test_command):
            print("✓ Cron job removed successfully")
        else:
            print("✗ Failed to remove cron job")
        
        # Test convenience functions
        print(f"\n=== Convenience Functions ===")
        daily_command = "sophia-learner start"
        if setup_overnight_processing(daily_command):
            print(f"✓ Setup overnight processing: {daily_command}")
            
            # Clean up
            disable_scheduled_processing(daily_command)
            print(f"✓ Disabled scheduled processing")
    
    else:
        print("Cron not available on this system - skipping cron tests")
    
    print("\n=== Usage Examples ===")
    print("""
    # In your Sophia Learner configuration or startup script:
    
    from sophia_learner.scheduler.cron_manager import CronManager
    
    # Initialize manager
    cron = CronManager()
    
    # Check if cron is available
    if cron.is_cron_available():
        # Schedule daily backfill at 2 AM
        cron.sync_with_cron(
            command="/usr/local/bin/sophia-learner backfill",
            schedule="0 2 * * *"
        )
        
        # Schedule processing window start at 5 PM
        cron.sync_with_cron(
            command="/usr/local/bin/sophia-learner start",
            schedule="0 17 * * *"
        )
        
        # List all scheduled Sophia Learner jobs
        jobs = cron.get_current_cron_jobs()
        for job in jobs:
            print(f"Scheduled: {job}")
        
        # Remove a specific job
        cron.remove_cron_job("/usr/local/bin/sophia-learner backfill")
        
        # Remove all Sophia Learner jobs
        cron.clear_all_sophia_jobs()
    """)
