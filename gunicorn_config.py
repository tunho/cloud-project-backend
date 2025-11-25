# gunicorn_config.py
import multiprocessing

# 🔥 [CRITICAL] Worker Configuration for Firebase Compatibility
# 'gevent' or 'eventlet' workers conflict with Firebase's gRPC (C-extension).
# We MUST use 'gthread' (threaded workers) to ensure stability.
# This means SocketIO will use Long Polling (which is fine) instead of WebSockets.
worker_class = 'gthread'
workers = 1  # For SocketIO, usually 1 worker is recommended unless using Redis/RabbitMQ
threads = 100 # Allow many concurrent connections per worker

# Timeout settings
timeout = 120
keepalive = 5

# Binding
bind = "0.0.0.0:5000"

# Logging
loglevel = "info"
accesslog = "-"
errorlog = "-"
