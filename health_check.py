"""Health check endpoint for monitoring worker status"""

from flask import Blueprint, jsonify
import psutil
import os
from state import rooms
from extensions import socketio

health_bp = Blueprint('health', __name__)

@health_bp.route('/health', methods=['GET'])
def health_check():
    """
    Health check endpoint that returns server status, memory usage, and active connections.
    Useful for monitoring and load balancer health checks.
    """
    try:
        # Get process info
        process = psutil.Process(os.getpid())
        
        # Memory info
        memory_info = process.memory_info()
        memory_mb = memory_info.rss / 1024 / 1024  # Convert to MB
        
        # CPU info
        cpu_percent = process.cpu_percent(interval=0.1)
        
        # Room/connection info
        active_rooms = len(rooms)
        total_players = sum(len(gs.players) for gs in rooms.values())
        
        # Active games
        active_games = sum(1 for gs in rooms.values() if gs.game_started)
        
        return jsonify({
            "status": "healthy",
            "pid": os.getpid(),
            "memory_mb": round(memory_mb, 2),
            "cpu_percent": round(cpu_percent, 2),
            "active_rooms": active_rooms,
            "total_players": total_players,
            "active_games": active_games,
            "num_threads": process.num_threads()
        }), 200
        
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e)
        }), 500

@health_bp.route('/metrics', methods=['GET'])
def metrics():
    """
    Detailed metrics endpoint for debugging
    """
    try:
        process = psutil.Process(os.getpid())
        
        # Detailed memory breakdown
        memory_info = process.memory_info()
        memory_full = process.memory_full_info() if hasattr(process, 'memory_full_info') else None
        
        # Room details
        room_details = []
        for room_id, gs in rooms.items():
            room_details.append({
                "room_id": room_id,
                "players": len(gs.players),
                "game_started": gs.game_started,
                "turn_phase": gs.turn_phase if hasattr(gs, 'turn_phase') else None,
                "current_turn": gs.current_turn if hasattr(gs, 'current_turn') else None
            })
        
        return jsonify({
            "process": {
                "pid": os.getpid(),
                "cpu_percent": process.cpu_percent(interval=0.1),
                "num_threads": process.num_threads(),
                "num_fds": process.num_fds() if hasattr(process, 'num_fds') else None
            },
            "memory": {
                "rss_mb": round(memory_info.rss / 1024 / 1024, 2),
                "vms_mb": round(memory_info.vms / 1024 / 1024, 2),
                "uss_mb": round(memory_full.uss / 1024 / 1024, 2) if memory_full else None,
                "percent": process.memory_percent()
            },
            "rooms": {
                "total": len(rooms),
                "details": room_details
            }
        }), 200
        
    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500
