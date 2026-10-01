"""
Network Transport: UDP broadcast / multicast gossip and HTTP peer synchronization.
"""
import json
import socket
import threading
import time
from typing import Callable, List, Optional
from .models import RobotManifest


class GossipNode:
    """
    Lightweight UDP gossip broadcaster and listener for ad-hoc robot communication.
    """
    def __init__(self, port: int = 9999, broadcast_ip: str = "255.255.255.255"):
        self.port = port
        self.broadcast_ip = broadcast_ip
        self.running = False
        self._sock: Optional[socket.socket] = None
        self._listener_thread: Optional[threading.Thread] = None
        self.on_manifest_received: Optional[Callable[[RobotManifest], None]] = None

    def start(self) -> None:
        self.running = True
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except Exception:
                pass
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        try:
            self._sock.bind(("", self.port))
        except Exception:
            pass

        self._listener_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._listener_thread.start()

    def stop(self) -> None:
        self.running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass

    def broadcast_manifest(self, manifest: RobotManifest) -> None:
        if not self._sock or not self.running:
            return
        try:
            payload = json.dumps(manifest.to_dict()).encode("utf-8")
            self._sock.sendto(payload, (self.broadcast_ip, self.port))
        except Exception:
            pass

    def _listen_loop(self) -> None:
        while self.running and self._sock:
            try:
                data, addr = self._sock.recvfrom(65535)
                if not data:
                    continue
                parsed = json.loads(data.decode("utf-8"))
                manifest = RobotManifest.from_dict(parsed)
                if self.on_manifest_received:
                    self.on_manifest_received(manifest)
            except Exception:
                if not self.running:
                    break
                time.sleep(0.05)
