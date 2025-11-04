"""
Summary Manager for tracking and reporting changes made during UniFi configuration sync operations.
"""

import logging
import platform
import sys
from typing import Dict, List, Set, Any
from datetime import datetime
import threading

# Cross-platform color support
class Colors:
    """Cross-platform color codes for terminal output."""
    
    def __init__(self):
        self.enabled = self._init_colors()
        
    def _init_colors(self):
        """Initialize color support based on platform and terminal capabilities."""
        # Check if we're in a terminal that supports colors
        if not hasattr(sys.stdout, 'isatty') or not sys.stdout.isatty():
            return False
            
        # Windows-specific color initialization
        if platform.system() == 'Windows':
            try:
                import ctypes
                import os
                
                # Enable ANSI color support on Windows 10+
                kernel32 = ctypes.windll.kernel32
                # Enable virtual terminal processing
                ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
                handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
                mode = ctypes.c_ulong()
                if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                    mode.value |= ENABLE_VIRTUAL_TERMINAL_PROCESSING
                    if kernel32.SetConsoleMode(handle, mode):
                        return True
                
                # If ANSI doesn't work, try colorama
                try:
                    import colorama
                    colorama.init(autoreset=True)
                    return True
                except ImportError:
                    # colorama not available, but ANSI might work
                    return True
            except Exception:
                # Fallback: try colorama
                try:
                    import colorama
                    colorama.init(autoreset=True)
                    return True
                except ImportError:
                    return False
        else:
            # Unix-like systems usually support ANSI colors out of the box
            return True
    
    def __getattr__(self, name):
        """Return color codes or empty strings if colors are disabled."""
        if not self.enabled:
            return ''
        
        # ANSI color codes
        colors = {
            'RESET': '\033[0m',
            'BOLD': '\033[1m',
            'DIM': '\033[2m',
            'RED': '\033[91m',
            'GREEN': '\033[92m',
            'YELLOW': '\033[93m',
            'BLUE': '\033[94m',
            'MAGENTA': '\033[95m',
            'CYAN': '\033[96m',
            'WHITE': '\033[97m',
            'BRIGHT_RED': '\033[91m\033[1m',
            'BRIGHT_GREEN': '\033[92m\033[1m',
            'BRIGHT_YELLOW': '\033[93m\033[1m',
            'BRIGHT_BLUE': '\033[94m\033[1m',
            'BRIGHT_MAGENTA': '\033[95m\033[1m',
            'BRIGHT_CYAN': '\033[96m\033[1m',
            'BRIGHT_WHITE': '\033[97m\033[1m',
            'BG_RED': '\033[101m',
            'BG_GREEN': '\033[102m',
            'BG_YELLOW': '\033[103m',
            'BG_BLUE': '\033[104m',
            'BG_MAGENTA': '\033[105m',
            'BG_CYAN': '\033[106m',
            'BG_WHITE': '\033[107m',
        }
        return colors.get(name, '')

# Global color instance
colors = Colors()

logger = logging.getLogger(__name__)

class OperationSummary:
    """Tracks summary information for a single operation/site combination."""
    
    def __init__(self, site_name: str, operation: str):
        self.site_name = site_name
        self.operation = operation
        self.timestamp = datetime.now()
        
        # Track changes by category
        self.items_created: List[str] = []
        self.items_updated: List[str] = []
        self.items_skipped: List[str] = []
        self.items_failed: List[tuple] = []  # (item_name, error_message)
        
        # Track specific issues
        self.extra_vlans: Set[str] = set()
        self.missing_vlans: Set[str] = set()
        self.wlan_limit_reached: bool = False
        self.permission_errors: List[str] = []
        self.dependency_warnings: List[str] = []
        
        # Track backup operations
        self.backups_created: List[str] = []
        
    def add_created_item(self, item_type: str, item_name: str):
        """Track a successfully created item."""
        self.items_created.append(f"{item_type}:{item_name}")
        
    def add_updated_item(self, item_type: str, item_name: str):
        """Track a successfully updated item."""
        self.items_updated.append(f"{item_type}:{item_name}")
        
    def add_skipped_item(self, item_type: str, item_name: str, reason: str = ""):
        """Track a skipped item."""
        skip_info = f"{item_type}:{item_name}"
        if reason:
            skip_info += f" ({reason})"
        self.items_skipped.append(skip_info)
        
    def add_failed_item(self, item_type: str, item_name: str, error_message: str):
        """Track a failed item."""
        self.items_failed.append((f"{item_type}:{item_name}", error_message))
        
    def add_extra_vlans(self, vlans: List[str]):
        """Track extra VLANs found."""
        self.extra_vlans.update(vlans)
        
    def add_missing_vlans(self, vlans: List[str]):
        """Track missing VLANs."""
        self.missing_vlans.update(vlans)
        
    def set_wlan_limit_reached(self):
        """Mark that WLAN limit was reached."""
        self.wlan_limit_reached = True
        
    def add_permission_error(self, error_message: str):
        """Track a permission error."""
        self.permission_errors.append(error_message)
        
    def add_dependency_warning(self, warning_message: str):
        """Track a dependency warning."""
        self.dependency_warnings.append(warning_message)
        
    def add_backup_created(self, backup_id: str):
        """Track a created backup."""
        self.backups_created.append(backup_id)

class SummaryManager:
    """Manages operation summaries across all sites and operations."""
    
    def __init__(self):
        self.summaries: Dict[str, OperationSummary] = {}
        self.lock = threading.Lock()
        self.global_start_time = datetime.now()
        
    def get_or_create_summary(self, site_name: str, operation: str) -> OperationSummary:
        """Get or create a summary for a specific site and operation."""
        key = f"{site_name}:{operation}"
        with self.lock:
            if key not in self.summaries:
                self.summaries[key] = OperationSummary(site_name, operation)
            return self.summaries[key]
    
    def generate_summary_report(self) -> str:
        """Generate a comprehensive summary report with colors."""
        if not self.summaries:
            return f"{colors.DIM}No operations performed.{colors.RESET}"
        
        report_lines = []
        report_lines.append(f"\n{colors.BRIGHT_CYAN}{'=' * 80}{colors.RESET}")
        report_lines.append(f"{colors.BRIGHT_WHITE}OPERATION SUMMARY REPORT{colors.RESET}")
        report_lines.append(f"{colors.BRIGHT_CYAN}{'=' * 80}{colors.RESET}")
        report_lines.append(f"{colors.DIM}Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{colors.RESET}")
        report_lines.append(f"{colors.DIM}Total Operations: {len(self.summaries)}{colors.RESET}")
        report_lines.append("")
        
        # Group summaries by operation type
        operations_by_type = {}
        for summary in self.summaries.values():
            if summary.operation not in operations_by_type:
                operations_by_type[summary.operation] = []
            operations_by_type[summary.operation].append(summary)
        
        for operation_type, summaries in operations_by_type.items():
            # Color code operation types
            op_color = colors.BRIGHT_BLUE
            if operation_type.upper() == 'ADD':
                op_color = colors.BRIGHT_GREEN
            elif operation_type.upper() == 'REPLACE':
                op_color = colors.BRIGHT_YELLOW
            elif operation_type.upper() == 'DELETE':
                op_color = colors.BRIGHT_RED
            
            report_lines.append(f"{op_color}OPERATION: {operation_type.upper()}{colors.RESET}")
            report_lines.append(f"{colors.CYAN}{'-' * 40}{colors.RESET}")
            
            for summary in summaries:
                report_lines.append(f"{colors.WHITE}Site: {summary.site_name}{colors.RESET}")
                report_lines.append(f"{colors.DIM}  Time: {summary.timestamp.strftime('%H:%M:%S')}{colors.RESET}")
                
                # Items created
                if summary.items_created:
                    report_lines.append(f"  {colors.BRIGHT_GREEN}✅ Created ({len(summary.items_created)}):{colors.RESET}")
                    for item in sorted(summary.items_created):
                        report_lines.append(f"    {colors.GREEN}  - {item}{colors.RESET}")
                
                # Items updated
                if summary.items_updated:
                    report_lines.append(f"  {colors.BRIGHT_YELLOW}🔄 Updated ({len(summary.items_updated)}):{colors.RESET}")
                    for item in sorted(summary.items_updated):
                        report_lines.append(f"    {colors.YELLOW}  - {item}{colors.RESET}")
                
                # Items skipped
                if summary.items_skipped:
                    report_lines.append(f"  {colors.BRIGHT_CYAN}⏭️  Skipped ({len(summary.items_skipped)}):{colors.RESET}")
                    for item in sorted(summary.items_skipped):
                        report_lines.append(f"    {colors.CYAN}  - {item}{colors.RESET}")
                
                # Items failed
                if summary.items_failed:
                    report_lines.append(f"  {colors.BRIGHT_RED}❌ Failed ({len(summary.items_failed)}):{colors.RESET}")
                    for item, error in summary.items_failed:
                        report_lines.append(f"    {colors.RED}  - {item}: {error}{colors.RESET}")
                
                # VLAN issues
                if summary.extra_vlans:
                    report_lines.append(f"  {colors.YELLOW}⚠️  Extra VLANs: {', '.join(sorted(summary.extra_vlans))}{colors.RESET}")
                
                if summary.missing_vlans:
                    report_lines.append(f"  {colors.BRIGHT_RED}🚨 Missing VLANs: {', '.join(sorted(summary.missing_vlans))}{colors.RESET}")
                
                # WLAN limit
                if summary.wlan_limit_reached:
                    report_lines.append(f"  {colors.BRIGHT_RED}🚫 WLAN Limit Reached: Some WLANs could not be created{colors.RESET}")
                
                # Dependency warnings
                if summary.dependency_warnings:
                    report_lines.append(f"  {colors.YELLOW}⚠️  Dependency Warnings:{colors.RESET}")
                    for warning in summary.dependency_warnings:
                        report_lines.append(f"    {colors.YELLOW}  - {warning}{colors.RESET}")
                
                # Backups created
                if summary.backups_created:
                    report_lines.append(f"  {colors.BRIGHT_MAGENTA}💾 Backups Created ({len(summary.backups_created)}):{colors.RESET}")
                    for backup_id in summary.backups_created:
                        report_lines.append(f"    {colors.MAGENTA}  - {backup_id}{colors.RESET}")
                
                report_lines.append("")
        
        # Global summary with color coding
        total_created = sum(len(s.items_created) for s in self.summaries.values())
        total_updated = sum(len(s.items_updated) for s in self.summaries.values())
        total_skipped = sum(len(s.items_skipped) for s in self.summaries.values())
        total_failed = sum(len(s.items_failed) for s in self.summaries.values())
        total_backups = sum(len(s.backups_created) for s in self.summaries.values())
        
        report_lines.append(f"{colors.BRIGHT_WHITE}GLOBAL TOTALS{colors.RESET}")
        report_lines.append(f"{colors.CYAN}{'-' * 40}{colors.RESET}")
        report_lines.append(f"  {colors.BRIGHT_GREEN}Items Created: {total_created}{colors.RESET}")
        report_lines.append(f"  {colors.BRIGHT_YELLOW}Items Updated: {total_updated}{colors.RESET}")
        report_lines.append(f"  {colors.BRIGHT_CYAN}Items Skipped: {total_skipped}{colors.RESET}")
        report_lines.append(f"  {colors.BRIGHT_RED}Items Failed: {total_failed}{colors.RESET}")
        report_lines.append(f"  {colors.BRIGHT_MAGENTA}Backups Created: {total_backups}{colors.RESET}")
        
        if total_failed > 0:
            report_lines.append("")
            report_lines.append(f"{colors.BRIGHT_RED}⚠️  SOME OPERATIONS FAILED - Review logs for details{colors.RESET}")
        
        report_lines.append(f"{colors.BRIGHT_CYAN}{'=' * 80}{colors.RESET}")
        
        return "\n".join(report_lines)

# Global instance
summary_manager = SummaryManager()

# Convenience functions for easy access
def get_summary(site_name: str, operation: str) -> OperationSummary:
    """Get or create a summary for the given site and operation."""
    return summary_manager.get_or_create_summary(site_name, operation)

def log_and_track_created(item_type: str, item_name: str, site_name: str, operation: str):
    """Log and track a created item."""
    logger.info(f"Successfully created {item_type} '{item_name}' at site '{site_name}'")
    get_summary(site_name, operation).add_created_item(item_type, item_name)

def log_and_track_updated(item_type: str, item_name: str, site_name: str, operation: str):
    """Log and track an updated item."""
    logger.info(f"Successfully updated {item_type} '{item_name}' at site '{site_name}'")
    get_summary(site_name, operation).add_updated_item(item_type, item_name)

def log_and_track_skipped(item_type: str, item_name: str, site_name: str, operation: str, reason: str = ""):
    """Log and track a skipped item."""
    msg = f"Skipped {item_type} '{item_name}' at site '{site_name}'"
    if reason:
        msg += f" - {reason}"
    logger.info(msg)
    get_summary(site_name, operation).add_skipped_item(item_type, item_name, reason)

def log_and_track_failed(item_type: str, item_name: str, site_name: str, operation: str, error_message: str):
    """Log and track a failed item."""
    logger.error(f"Failed to process {item_type} '{item_name}' at site '{site_name}': {error_message}")
    get_summary(site_name, operation).add_failed_item(item_type, item_name, error_message)

def generate_summary():
    """Generate and log the summary report."""
    report = summary_manager.generate_summary_report()
    logger.info(report)
    return report
