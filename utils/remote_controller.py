"""
@File    :   remote_controller.py
@Author  :   Paul Glaeser
@Contact :   paul.glaeser@uni-tuebingen.de
@Desc    :   TCP/JSON server that lets external software (e.g. the imaging
             PC driving a z-stack) command the stages.

Protocol
--------
One JSON object per command, one JSON object per reply, replies terminated
by a newline. Commands may be sent back-to-back or split across packets;
the reader reassembles them.

Motion commands block by default and only answer once the stage has come
to rest, which is what an external z-stack needs. Pass "wait": false to get
the old fire-and-forget behaviour back.
"""

import json
import logging
import socket
import threading


# Maps the controller's motion result codes onto a reply status and a
# message the caller can show to a user.
RESULT_MESSAGES = {
    "done": None,
    "aborted": "motion was stopped before the target was reached",
    "timeout": "stage did not stop within the timeout",
    "busy": "stage was still executing a previous move",
    "soft_limit": "target is beyond the active z soft limit",
    "not_connected": "stage is not connected",
    "no_position": "stage position could not be read",
    "error": "stage reported an error",
}

# Refuse to keep buffering a client that never sends parseable JSON.
MAX_BUFFER = 65536


class RemoteControlServer:
    """
    Threaded TCP server exposing the MultiStageController to a remote client.

    Parameters
    ---------
    controller: the MultiStageController instance to drive
    str host: interface to bind to. "0.0.0.0" listens on every adapter,
        which is what a second PC on a direct Ethernet link needs. Pass the
        IP of that adapter instead to keep the server off the house network.
    int port: TCP port to listen on
    list allowed_clients: optional whitelist of client IP addresses; any
        other peer is closed immediately. None accepts everyone.
    """

    def __init__(self, controller,
                 host="0.0.0.0",
                 port=5555,
                 allowed_clients=None):

        self.controller = controller
        self.host = host
        self.port = port
        self.allowed_clients = allowed_clients

        self.log = logging.getLogger("StageControl")

        self.alive = True
        self.server = None

        # Serialises motion commands so two clients cannot start moves on
        # top of each other. Status and stop commands deliberately do not
        # take it, so a stop still gets through while a move is blocking.
        self.motion_lock = threading.Lock()

        self.thread = threading.Thread(target=self.server_loop)
        self.thread.daemon = True
        self.thread.start()

    # ------------------------------------------------------------------
    # Socket plumbing
    # ------------------------------------------------------------------
    def server_loop(self):
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # without this a restart right after a crash fails with
            # "address already in use" until the old socket times out
            self.server.setsockopt(
                socket.SOL_SOCKET, socket.SO_REUSEADDR, 1
            )
            self.server.bind((self.host, self.port))
            self.server.listen(5)
        except OSError as e:
            self.log.error(
                f"Remote server could not bind {self.host}:{self.port}: {e}"
            )
            print(f"Remote server could not start: {e}")
            return

        self.log.info(f"Remote server listening on {self.host}:{self.port}")
        print(f"Remote server listening on {self.host}:{self.port}")

        while self.alive:
            try:
                conn, addr = self.server.accept()
            except OSError:
                break  # socket closed by close()

            if (self.allowed_clients is not None
                    and addr[0] not in self.allowed_clients):
                self.log.warning(f"Rejected remote connection from {addr[0]}")
                conn.close()
                continue

            self.log.info(f"Remote client connected from {addr[0]}")

            # One thread per client so a stale connection cannot lock the
            # imaging PC out of the server.
            worker = threading.Thread(
                target=self.handle_client,
                args=(conn, addr)
            )
            worker.daemon = True
            worker.start()

    def handle_client(self, conn, addr):
        # replies are small and latency matters more than packet count
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

        decoder = json.JSONDecoder()
        buffer = ""

        try:
            while self.alive:
                data = conn.recv(4096)
                if not data:
                    break

                buffer += data.decode("utf-8", errors="replace")

                # A single recv() may hold several commands or only part of
                # one, so pull off as many complete objects as are there.
                while True:
                    buffer = buffer.lstrip()
                    if not buffer:
                        break
                    try:
                        cmd, end = decoder.raw_decode(buffer)
                    except ValueError:
                        # incomplete - wait for the rest, unless the client
                        # is just sending noise
                        if len(buffer) > MAX_BUFFER:
                            self.send(conn, {
                                "status": "error",
                                "message": "malformed command"
                            })
                            buffer = ""
                        break

                    buffer = buffer[end:]

                    try:
                        response = self.handle_command(cmd)
                    except Exception as e:
                        self.log.error(f"Remote command failed: {e}")
                        response = {
                            "status": "error",
                            "message": str(e)
                        }

                    self.send(conn, response)

        except OSError:
            pass
        finally:
            self.log.info(f"Remote client {addr[0]} disconnected")
            try:
                conn.close()
            except OSError:
                pass

    def send(self, conn, response):
        conn.sendall((json.dumps(response) + "\n").encode())

    def close(self):
        """Stop accepting connections and release the port."""
        self.alive = False
        if self.server is not None:
            try:
                self.server.close()
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Command handling
    # ------------------------------------------------------------------
    def motion_reply(self, info, extra_keys=()):
        """
        Turn a controller motion result dict into a protocol reply.

        "status" is written first so simple clients that scan for the first
        occurrence of a key find the right one.
        """
        result = info.get("result", "error")
        ok = result == "done"

        reply = {"status": "ok" if ok else "error", "result": result}

        if not ok:
            reply["message"] = info.get(
                "message",
                RESULT_MESSAGES.get(result, "motion failed")
            )

        for key in extra_keys:
            if key in info:
                reply[key] = info[key]

        return reply

    def warn_if_not_remote(self, command):
        """
        The joystick loop keeps driving the stages unless remote mode is on,
        which can fight a remote move. Worth a log line, not a refusal.
        """
        if not self.controller.remote_mode:
            self.log.warning(
                f"Remote '{command}' received while remote mode is off - "
                "the joystick loop may interfere with this move"
            )

    def handle_command(self, cmd):
        command = cmd.get("cmd")

        # --- mode ------------------------------------------------------
        if command == "enable_remote":
            self.controller.enable_remote_mode()
            return {"status": "ok"}

        if command == "disable_remote":
            self.controller.disable_remote_mode()
            return {"status": "ok"}

        # --- motion ----------------------------------------------------
        if command == "move_z":
            dz = float(cmd["dz"])
            timeout = float(cmd.get("timeout", 60.0))
            self.warn_if_not_remote(command)

            if not cmd.get("wait", True):
                with self.motion_lock:
                    self.controller.move_z_step(dz)
                return {"status": "ok", "result": "started"}

            with self.motion_lock:
                info = self.controller.move_z_step_blocking(dz, timeout)
            return self.motion_reply(
                info, ("z", "target", "reached")
            )

        if command in ("move_x", "move_y"):
            axis = command[-1]
            delta = float(cmd["d" + axis])
            timeout = float(cmd.get("timeout", 60.0))
            dx = delta if axis == "x" else 0
            dy = delta if axis == "y" else 0
            self.warn_if_not_remote(command)

            if not cmd.get("wait", True):
                with self.motion_lock:
                    self.controller.move_xy_step(dx=dx, dy=dy)
                return {"status": "ok", "result": "started"}

            with self.motion_lock:
                info = self.controller.move_xy_step_blocking(dx, dy, timeout)
            return self.motion_reply(info, ("x", "y"))

        if command == "move_to":
            self.warn_if_not_remote(command)
            with self.motion_lock:
                ok = self.controller.move_to(
                    cmd["x"],
                    cmd["y"],
                    cmd["z"]
                )
            if ok:
                return {"status": "ok", "result": "done"}
            return {
                "status": "error",
                "result": "not_reached",
                "message": "target was not reached within tolerance"
            }

        # --- status ----------------------------------------------------
        if command == "get_pos":
            return {
                "status": "ok",
                "positions": self.controller.get_positions()
            }

        if command == "is_moving":
            moving = self.controller.is_moving()
            return {
                "status": "ok",
                "moving": any(moving.values()),
                "axes": moving
            }

        if command == "wait_move":
            # for clients that would rather poll than hold a socket open
            axis = cmd.get("axis", "z")
            timeout = float(cmd.get("timeout", 60.0))
            if axis == "z":
                result = self.controller.wait_z_stopped(timeout)
            elif axis in ("x", "y", "xy"):
                result = self.controller.wait_xy_stopped(timeout)
            else:
                return {
                    "status": "error",
                    "message": f"unknown axis '{axis}'"
                }
            return self.motion_reply({"result": result})

        if command == "ping":
            return {"status": "ok"}

        # --- stop ------------------------------------------------------
        # deliberately outside motion_lock: a stop must get through while a
        # blocking move is still holding the lock
        if command == "stop":
            self.controller.stop_axes()
            return {"status": "ok"}

        return {
            "status": "error",
            "message": f"unknown command '{command}'"
        }
