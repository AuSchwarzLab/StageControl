import socket
import threading
import json


class RemoteControlServer:
    def __init__(self, controller,
                 host="127.0.0.1",
                 port=5555):

        self.controller = controller
        self.host = host
        self.port = port

        self.alive = True

        self.thread = threading.Thread(target=self.server_loop)
        self.thread.daemon = True
        self.thread.start()

    def server_loop(self):
        server = socket.socket(socket.AF_INET,
                            socket.SOCK_STREAM)

        server.bind((self.host, self.port))
        server.listen(1)

        while self.alive:
            conn, _ = server.accept()
            with conn:
                while self.alive:
                    data = conn.recv(4096)
                    if not data:
                        break
                    try:
                        cmd = json.loads(data.decode())
                        response = self.handle_command(cmd)
                    except Exception as e:
                        response = {
                            "status": "error",
                            "message": str(e)
                        }
                    conn.sendall(
                        (json.dumps(response) + "\n").encode()
                    )

    def handle_command(self, cmd):
        command = cmd.get("cmd")
        if command == "enable_remote":
            self.controller.enable_remote_mode()
            return {"status": "ok"}
        elif command == "disable_remote":
            self.controller.disable_remote_mode()
            return {"status": "ok"}
        elif command == "move_z":
            dz = cmd["dz"]
            self.controller.move_z_step(dz)
            return {"status": "ok"}
        elif command == "move_x":
            dx = cmd["dx"]
            self.controller.move_xy_step(dx=dx, dy=0)
            return {"status": "ok"}
        elif command == "move_y":
            dy = cmd["dy"]
            self.controller.move_xy_step(dx=0, dy=dy)
            return {"status": "ok"}
        elif command == "move_to":
            ok = self.controller.move_to(
                cmd["x"],
                cmd["y"],
                cmd["z"]
            )
            return {
                "status": "ok" if ok else "failed"
            }
        elif command == "get_pos":
            return {
                "status": "ok",
                "positions":
                    self.controller.get_positions()
            }

        elif command == "stop":
            self.controller.stop_axes()
            return {"status": "ok"}

        return {
            "status": "error",
            "message": "unknown command"
        }