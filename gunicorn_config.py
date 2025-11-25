"""Gunicorn configuration for Flask-SocketIO (Minimal)"""

# Worker class - CRITICAL for SocketIO
worker_class = 'eventlet'

# Number of worker processes
workers = 1

# Binding
bind = '0.0.0.0:5000'

# Timeout settings - INCREASED to prevent premature kills
timeout = 120  # 2 minutes
keepalive = 5

# Logging
accesslog = '-'
errorlog = '-'
loglevel = 'info'
