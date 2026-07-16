from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


SERVER_NAME = "SimpleScreenshot-3f802cab-0bfc-49fa-b15e-8c14a7d94453"


class SingleInstance(QObject):
    activate_requested = Signal()

    def __init__(self, server_name: str = SERVER_NAME) -> None:
        super().__init__()
        self.server_name = server_name
        self.server: QLocalServer | None = None

    def claim_or_notify(self) -> bool:
        socket = QLocalSocket(self)
        socket.connectToServer(self.server_name)
        if socket.waitForConnected(250):
            socket.write(b"activate")
            socket.flush()
            socket.waitForBytesWritten(250)
            socket.disconnectFromServer()
            return False

        QLocalServer.removeServer(self.server_name)
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._accept_connections)
        if not self.server.listen(self.server_name):
            raise RuntimeError(f"无法创建单实例通道：{self.server.errorString()}")
        return True

    def _accept_connections(self) -> None:
        if self.server is None:
            return
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.readyRead.connect(lambda current=socket: self._read_socket(current))
            if socket.bytesAvailable():
                self._read_socket(socket)

    def _read_socket(self, socket: QLocalSocket) -> None:
        payload = bytes(socket.readAll())
        if b"activate" in payload:
            self.activate_requested.emit()
        socket.disconnectFromServer()
        socket.deleteLater()
