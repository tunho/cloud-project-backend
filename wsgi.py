"""WSGI entry point for production deployment"""

from main import app, socketio

if __name__ == "__main__":
    # This is used only for local testing with gunicorn
    socketio.run(app, host="0.0.0.0", port=5000)
