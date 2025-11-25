"""Gunicorn configuration for Flask-SocketIO"""

import multiprocessing

# Worker class - CRITICAL for SocketIO
# Must use eventlet or gevent worker class
worker_class = 'eventlet'

# Number of worker processes
workers = 1  # SocketIO requires single worker for in-memory state

# Binding
bind = '0.0.0.0:5000'

# Logging
accesslog = '-'
errorlog = '-'
loglevel = 'info'

# Timeout settings - INCREASED for long-running Firebase operations
timeout = 300  # 5 minutes instead of 2 (Firebase can be slow)
graceful_timeout = 30  # Grace period for workers to finish
keepalive = 5

# Worker lifecycle - restart workers periodically to prevent memory leaks
max_requests = 1000  # Restart worker after 1000 requests
max_requests_jitter = 50  # Add randomness to prevent all workers restarting at once

# Memory management
worker_tmp_dir = '/dev/shm'  # Use shared memory for better performance

# For debugging
reload = False

# preload_app - DISABLED for eventlet compatibility
# With eventlet worker, preload_app=True causes "blocking functions from mainloop" error
preload_app = False

# Worker lifecycle hooks for cleanup
def on_starting(server):
    """Called just before the master process is initialized."""
    print("🚀 Gunicorn master process starting...")

def when_ready(server):
    """Called just after the server is started."""
    print("✅ Gunicorn server ready to accept connections")

def worker_int(worker):
    """Called when a worker receives the SIGINT or SIGQUIT signal."""
    print(f"⚠️ Worker {worker.pid} received interrupt signal")

def worker_abort(worker):
    """Called when a worker receives the SIGABRT signal (timeout)."""
    print(f"❌ WORKER TIMEOUT: Worker {worker.pid} aborted!")
    # Log additional debugging info
    import traceback
    import sys
    traceback.print_stack(file=sys.stderr)

def on_exit(server):
    """Called just before the master process exits."""
    print("🛑 Gunicorn master process shutting down...")
