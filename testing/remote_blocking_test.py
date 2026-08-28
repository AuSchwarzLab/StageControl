"""
@File    :   remote_blocking_test.py
@Author  :   Paul Glaeser
@Contact :   paul.glaeser@uni-tuebingen.de
@Desc    :   Offline test for the blocking remote interface.

Runs the real RemoteControlServer and MultiStageController against fake
stages, so the protocol, the framing and the "reply only once the move has
finished" behaviour can be checked without any hardware attached.

    python testing/remote_blocking_test.py
"""

import json
import os
import socket
import sys
import threading
import time

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from utils.multi_stage_controller import MultiStageController
from utils.remote_controller import RemoteControlServer


PORT = 5599
MOVE_DURATION = 0.8   # s the fake z stage takes for any move


# ----------------------------------------------------------------------
# Fake hardware
# ----------------------------------------------------------------------
class FakeJoystick:
    connected = False
    last_pressed_button = None
    knob_values = [0, 0, 0, 0]

    def set_leds(self, **kwargs):
        pass


class FakeZStage:
    """Mimics the Thorlabs stage: move() returns at once, motion takes time."""

    def __init__(self):
        self.connected = True
        self.position = 5.0
        self._move_end = 0.0
        self._target = 5.0

    def is_moving(self):
        if time.time() < self._move_end:
            return True
        self.position = self._target
        return False

    def move(self, distance_mm):
        if self.is_moving():
            return False
        self._target = self.position + distance_mm
        self._move_end = time.time() + MOVE_DURATION
        return True

    def move_to(self, target):
        return self.move(target - self.position)

    def set_velocity(self, v):
        pass

    def stop(self):
        self._move_end = 0.0
        self._target = self.position

    def get_position(self):
        if time.time() >= self._move_end:
            self.position = self._target
        return self.position

    def close(self):
        pass


class FakeStanda:
    def __init__(self):
        self.connected = True
        self.x = 1.0
        self.y = 2.0
        self._end = 0.0

    def is_moving(self, axis=None):
        return time.time() < self._end

    def move_relative(self, axis, d):
        if axis == "x":
            self.x += d
        else:
            self.y += d
        self._end = time.time() + 0.4

    def move_to(self, axis, target):
        self.move_relative(axis, 0)

    def get_position(self):
        return (self.x, self.y)

    def stop(self):
        self._end = 0.0

    def close(self):
        pass


class FakePiezo:
    connected = False

    def get_position(self):
        return 0

    def set_velocity(self, v):
        pass

    def move_relative(self, d):
        pass

    def stop(self):
        pass

    def close(self):
        pass


# ----------------------------------------------------------------------
# Test client
# ----------------------------------------------------------------------
class Client:
    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=30)
        self.buffer = ""

    def send_raw(self, text):
        self.sock.sendall(text.encode())

    def read_reply(self):
        while "\n" not in self.buffer:
            data = self.sock.recv(4096)
            if not data:
                raise RuntimeError("server closed the connection")
            self.buffer += data.decode()
        line, self.buffer = self.buffer.split("\n", 1)
        return json.loads(line)

    def command(self, **kwargs):
        # note: no trailing newline, exactly like the C++ client sends it
        self.send_raw(json.dumps(kwargs))
        return self.read_reply()

    def close(self):
        self.sock.close()


PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL  {name}  {detail}")


def main():
    zstage = FakeZStage()
    standa = FakeStanda()
    controller = MultiStageController(
        FakeJoystick(), standa, zstage, FakePiezo()
    )
    server = RemoteControlServer(controller, host="127.0.0.1", port=PORT)
    time.sleep(0.3)

    client = Client(PORT)

    # Must come first: a client shutting down may send disable_remote
    # before this process has ever been in remote mode.
    print("\n0. disable_remote as the very first command")
    r = client.command(cmd="disable_remote")
    check("disable_remote on a fresh controller returns ok",
          r.get("status") == "ok", r)

    print("\n1. enable remote mode")
    r = client.command(cmd="enable_remote")
    check("enable_remote returns ok", r.get("status") == "ok", r)

    print("\n2. blocking move_z waits for the stage")
    start = time.time()
    r = client.command(cmd="move_z", dz=0.01)
    elapsed = time.time() - start
    print(f"     reply after {elapsed:.2f} s: {r}")
    check("move_z returns ok", r.get("status") == "ok", r)
    check(
        "move_z blocks for the move duration",
        elapsed >= MOVE_DURATION * 0.9,
        f"returned after {elapsed:.2f} s"
    )
    check("stage is idle when the reply arrives", not zstage.is_moving())
    check("reported target was reached", r.get("reached") is True, r)
    check(
        "final z matches the commanded step",
        abs(r.get("z", 0) - 5.01) < 1e-9,
        r
    )

    print("\n3. positions are fresh right after the move")
    r = client.command(cmd="get_pos")
    print(f"     {r}")
    check(
        "get_pos reports the post-move z",
        abs(r["positions"]["z"] - 5.01) < 1e-9,
        r
    )

    print("\n4. non-blocking variant still returns immediately")
    start = time.time()
    r = client.command(cmd="move_z", dz=0.01, wait=False)
    elapsed = time.time() - start
    check(
        "wait=false returns at once",
        elapsed < MOVE_DURATION / 2,
        f"returned after {elapsed:.2f} s"
    )
    check("is_moving sees the running move", client.command(
        cmd="is_moving")["moving"] is True)
    r = client.command(cmd="wait_move", axis="z", timeout=10)
    check("wait_move completes the move", r.get("status") == "ok", r)
    check("stage idle after wait_move", not zstage.is_moving())

    print("\n5. blocking move_x")
    start = time.time()
    r = client.command(cmd="move_x", dx=0.05)
    elapsed = time.time() - start
    check("move_x returns ok", r.get("status") == "ok", r)
    check("move_x blocks", elapsed >= 0.35, f"{elapsed:.2f} s")

    print("\n6. a stop during a move is reported as an abort")
    stopper = Client(PORT)

    def do_stop():
        time.sleep(0.2)
        stopper.command(cmd="stop")

    threading.Thread(target=do_stop, daemon=True).start()
    r = client.command(cmd="move_z", dz=0.01)
    print(f"     {r}")
    check("aborted move reports an error", r.get("status") == "error", r)
    check("abort result is 'aborted'", r.get("result") == "aborted", r)
    stopper.close()

    print("\n7. soft limit is reported instead of silently ignored")
    controller.soft_limit_z = zstage.get_position() + 0.005
    controller.soft_limit_enabled = True
    r = client.command(cmd="move_z", dz=0.5)
    print(f"     {r}")
    check("soft limit blocks the move", r.get("status") == "error", r)
    check("soft limit result is reported", r.get("result") == "soft_limit", r)
    controller.soft_limit_enabled = False

    print("\n8. framing: two commands in one packet, split packet")
    client.send_raw('{"cmd": "ping"}{"cmd": "ping"}')
    r1 = client.read_reply()
    r2 = client.read_reply()
    check("both concatenated commands answered",
          r1.get("status") == "ok" and r2.get("status") == "ok", (r1, r2))

    client.send_raw('{"cmd": "get')
    time.sleep(0.2)
    client.send_raw('_pos"}')
    r = client.read_reply()
    check("split command reassembled", r.get("status") == "ok", r)

    print("\n9. unknown command")
    r = client.command(cmd="fly_to_the_moon")
    check("unknown command errors", r.get("status") == "error", r)

    print("\n10. disable remote mode")
    r = client.command(cmd="disable_remote")
    check("disable_remote returns ok", r.get("status") == "ok", r)

    print("\n11. remote mode is idempotent")
    # A client may send disable_remote defensively on shutdown, possibly
    # without ever having enabled it.
    r = client.command(cmd="disable_remote")
    check("disable without a prior enable returns ok",
          r.get("status") == "ok", r)

    # The realistic sequence: the operator arms remote control with the GUI
    # button, then the imaging software arms it again before its stack.
    controller.axis_enabled = [True, True, True, True]

    controller.enable_remote_mode()                  # GUI button
    check("axes disabled while remote",
          controller.axis_enabled == [False] * 4, controller.axis_enabled)

    r = client.command(cmd="enable_remote")          # imaging PC
    check("second enable returns ok", r.get("status") == "ok", r)
    check("double enable keeps the saved joystick state",
          controller.prev_axis_enabled == [True] * 4,
          controller.prev_axis_enabled)

    r = client.command(cmd="disable_remote")
    check("joystick axes restored after handing control back",
          controller.axis_enabled == [True] * 4, controller.axis_enabled)
    check("remote mode is off again", controller.remote_mode is False)

    # restoring must not alias the saved list, or later joystick toggles
    # would rewrite the state that a future disable restores
    controller.axis_enabled[0] = False
    check("restored state is a copy, not an alias",
          controller.prev_axis_enabled == [True] * 4,
          controller.prev_axis_enabled)

    client.close()
    server.close()
    controller.alive = False

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for name in FAILED:
            print(f"  failed: {name}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
