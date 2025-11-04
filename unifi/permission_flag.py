"""Global permission error flag for stopping all threads"""

import threading

# Global flag to stop all threads on permission error
permission_error_detected = False
permission_error_lock = threading.Lock()

def set_permission_error():
    """Set the global permission error flag"""
    global permission_error_detected
    with permission_error_lock:
        permission_error_detected = True

def is_permission_error_detected():
    """Check if permission error was detected"""
    with permission_error_lock:
        return permission_error_detected

def reset_permission_error():
    """Reset the permission error flag"""
    global permission_error_detected
    with permission_error_lock:
        permission_error_detected = False
