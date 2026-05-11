"""
Conflict Resolver - Manage version conflicts for files

This module provides functionality to detect, manage, and resolve version
conflicts when multiple versions of the same logical file are detected.
"""

import logging
import subprocess
from typing import List, Optional, Dict, Any
from datetime import datetime

from ..db.version_tracker import VersionTracker
from ..db.models import ConflictRecord, FileRecord
from ..utils.logger import get_logger

logger = get_logger(__name__)


class ConflictResolver:
    """
    Resolves version conflicts between multiple versions of the same logical file.
    
    This class manages the conflict resolution process, supporting both automatic
    resolution (keeping the highest version) and manual resolution via user input
    through a management application or CLI.
    
    Attributes:
        _version_tracker: Database interface for version operations
        _mode: Resolution mode ("manual" or "auto_keep_latest")
        _notification_command: Optional command for user notifications
    """
    
    def __init__(self, version_tracker: VersionTracker, mode: str = "manual", 
                 notification_command: Optional[str] = None):
        """
        Initialize the conflict resolver.
        
        Args:
            version_tracker: VersionTracker instance for database operations
            mode: Resolution mode ("manual" or "auto_keep_latest")
            notification_command: Optional command to run for notifications
        """
        self._version_tracker = version_tracker
        self._mode = mode
        self._notification_command = notification_command
        
        logger.info(f"ConflictResolver initialized with mode: {mode}")
    
    def resolve(self, conflict_id: int, chosen_version: Optional[str] = None) -> bool:
        """
        Resolve a conflict either automatically or with user choice.
        
        Args:
            conflict_id: ID of the conflict to resolve
            chosen_version: If provided, use this version; otherwise auto-resolve
            
        Returns:
            True if resolution was successful, False otherwise
        """
        try:
            # Get conflict details
            conflict = self._get_conflict(conflict_id)
            if not conflict:
                logger.error(f"Conflict {conflict_id} not found")
                return False
            
            # Get versions involved
            versions = conflict.versions
            
            if not versions:
                logger.error(f"Conflict {conflict_id} has no versions")
                return False
            
            # Determine which version to keep
            version_to_keep = chosen_version
            if version_to_keep is None:
                if self._mode == "auto_keep_latest":
                    version_to_keep = self._auto_resolve(versions)
                    logger.info(f"Auto-resolving conflict {conflict_id}: keeping {version_to_keep}")
                else:
                    # Request user input
                    version_to_keep = self._request_user_input(conflict_id, versions)
                    if version_to_keep is None:
                        logger.warning(f"User cancelled resolution for conflict {conflict_id}")
                        return False
            
            # Validate chosen version is in the list
            if version_to_keep not in versions:
                logger.error(f"Chosen version {version_to_keep} not in conflict versions {versions}")
                return False
            
            # Resolve the conflict in the database
            self._version_tracker.resolve_conflict(
                conflict_id, 
                version_to_keep, 
                resolved_by="user" if chosen_version or self._mode == "manual" else "auto"
            )
            
            logger.info(f"Conflict {conflict_id} resolved: keeping {version_to_keep}")
            return True
            
        except Exception as e:
            logger.exception(f"Failed to resolve conflict {conflict_id}: {e}")
            return False
    
    def _auto_resolve(self, versions: List[str]) -> str:
        """
        Automatically resolve conflict by selecting the highest version.
        
        Args:
            versions: List of version strings to compare
            
        Returns:
            The highest version string
        """
        from .version_detector import compare_versions
        
        if not versions:
            raise ValueError("No versions provided for auto-resolution")
        
        # Find the highest version
        highest = versions[0]
        for version in versions[1:]:
            if compare_versions(version, highest) > 0:
                highest = version
        
        logger.debug(f"Auto-resolved: highest version is {highest} among {versions}")
        return highest
    
    def _request_user_input(self, conflict_id: int, versions: List[str]) -> Optional[str]:
        """
        Request user input to resolve a conflict.
        
        This method attempts to use the management app if available,
        falling back to command-line input.
        
        Args:
            conflict_id: ID of the conflict
            versions: List of version strings to choose from
            
        Returns:
            Chosen version string, or None if cancelled
        """
        # First, queue for management
        self.queue_for_management(conflict_id)
        
        # Try to use the management app if available
        try:
            from ..cli.management_app import ConflictManagementApp
            app = ConflictManagementApp(self._version_tracker)
            
            # This would be a blocking call to the management app
            # For now, simulate with CLI prompt
            logger.info(f"Conflict {conflict_id} requires manual resolution")
            logger.info(f"Available versions: {', '.join(versions)}")
            
            # Simple CLI prompt (fallback)
            print(f"\nConflict {conflict_id} detected!")
            print(f"Versions available: {', '.join(versions)}")
            
            while True:
                choice = input(f"Which version to keep? [{', '.join(versions)}]: ").strip()
                if choice in versions:
                    return choice
                elif choice.lower() in ['q', 'quit', 'cancel']:
                    return None
                else:
                    print(f"Invalid choice. Please choose from: {', '.join(versions)}")
                    
        except ImportError:
            # Management app not available, use simple input
            logger.warning("Management app not available, using CLI input")
            
            print(f"\nConflict {conflict_id} requires manual resolution")
            print(f"Available versions: {', '.join(versions)}")
            
            while True:
                choice = input(f"Which version to keep? ").strip()
                if choice in versions:
                    return choice
                elif choice.lower() in ['q', 'quit', 'cancel']:
                    return None
                else:
                    print(f"Invalid choice. Please choose from: {', '.join(versions)}")
    
    def queue_for_management(self, conflict_id: int):
        """
        Mark a conflict as pending and queue for management app.
        
        Args:
            conflict_id: ID of the conflict to queue
        """
        try:
            # Update conflict status to pending in database
            # This would be handled by version_tracker
            conflict = self._get_conflict(conflict_id)
            if conflict and conflict.status != "pending":
                logger.info(f"Queued conflict {conflict_id} for management")
                
                # Notify user if configured
                self.notify_user(f"Conflict {conflict_id} requires resolution. Versions: {conflict.versions}")
        except Exception as e:
            logger.error(f"Failed to queue conflict {conflict_id}: {e}")
    
    def get_pending_conflicts(self) -> List[ConflictRecord]:
        """
        Get all pending conflicts awaiting resolution.
        
        Returns:
            List of ConflictRecord objects with status 'pending'
        """
        try:
            return self._version_tracker.get_pending_conflicts()
        except Exception as e:
            logger.error(f"Failed to get pending conflicts: {e}")
            return []
    
    def notify_user(self, message: str):
        """
        Send a notification to the user about pending conflicts.
        
        Uses the configured notification command if available.
        
        Args:
            message: Notification message to send
        """
        if not self._notification_command:
            logger.debug(f"No notification command configured. Message: {message}")
            return
        
        try:
            # Execute notification command with message as argument
            # The command should accept a message string
            result = subprocess.run(
                [self._notification_command, message],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                logger.debug(f"User notified: {message}")
            else:
                logger.warning(f"Notification command failed: {result.stderr}")
                
        except subprocess.TimeoutExpired:
            logger.warning("Notification command timed out")
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")
    
    def _get_conflict(self, conflict_id: int) -> Optional[ConflictRecord]:
        """
        Retrieve a conflict record by ID.
        
        Args:
            conflict_id: Conflict ID to retrieve
            
        Returns:
            ConflictRecord or None if not found
        """
        # Direct database query (simplified)
        # In production, this would use version_tracker.get_conflict()
        try:
            # This is a placeholder - actual implementation would use version_tracker
            conflicts = self._version_tracker.get_pending_conflicts()
            for conflict in conflicts:
                if conflict.id == conflict_id:
                    return conflict
            return None
        except Exception as e:
            logger.error(f"Failed to get conflict {conflict_id}: {e}")
            return None
    
    def get_conflict_details(self, conflict_id: int) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a conflict.
        
        Args:
            conflict_id: ID of the conflict
            
        Returns:
            Dictionary with conflict details including file paths and versions
        """
        try:
            conflict = self._get_conflict(conflict_id)
            if not conflict:
                return None
            
            # Get file records for each version
            file_records = []
            for version in conflict.versions:
                # This would need a method to get file by version
                # Simplified for now
                file_records.append({
                    "version": version,
                    "file_path": f"unknown_path_{version}"
                })
            
            return {
                "conflict_id": conflict.id,
                "file_group": conflict.file_group,
                "versions": conflict.versions,
                "status": conflict.status,
                "created_at": conflict.created_at,
                "files": file_records
            }
            
        except Exception as e:
            logger.error(f"Failed to get conflict details for {conflict_id}: {e}")
            return None
    
    def resolve_all_auto(self) -> int:
        """
        Automatically resolve all pending conflicts.
        
        Returns:
            Number of conflicts successfully resolved
        """
        pending = self.get_pending_conflicts()
        resolved_count = 0
        
        for conflict in pending:
            if self.resolve(conflict.id):
                resolved_count += 1
        
        logger.info(f"Auto-resolved {resolved_count} of {len(pending)} conflicts")
        return resolved_count
    
    def set_mode(self, mode: str):
        """
        Change the resolution mode.
        
        Args:
            mode: New resolution mode ("manual" or "auto_keep_latest")
        """
        if mode in ["manual", "auto_keep_latest"]:
            self._mode = mode
            logger.info(f"Conflict resolution mode changed to: {mode}")
        else:
            raise ValueError(f"Invalid mode: {mode}. Must be 'manual' or 'auto_keep_latest'")
