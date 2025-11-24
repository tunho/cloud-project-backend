"""Gunicorn configuration for Flask-SocketIO"""

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

# Timeout
timeout = 120
keepalive = 5

# For debugging
reload = False
