import threading
import time
import numpy as np


class MultiStageController:
    def __init__(self, joystick, standa, zstage, piezo):
        self.joystick = joystick
        self.standa = standa
        self.zstage = zstage
        self.piezo = piezo

        self.lock_piezo = threading.Lock()
        self.lock_z = threading.Lock()

        # x, y, z, piezo
        self.axis_enabled = [True, True, True, True]

        self.alive = True
        self.running = True
        self.gui_move_active = False
        self.dt = 0.02 # time interval for processing joystick inputs 

        self.button_pressed_state = {
            "BA": False,
            "BB": False
        }

        # stage state for logging purposes
        self._last_motion_state = [False, False, False, False]  # x, y, z, piezo
        self._last_direction = [0, 0, 0, 0]

        # position readout offset
        self.zero_offset = {"x": 0.0, "y": 0.0, "z": 0.0, "piezo": 0} 
        self.last_z_read_time = 0
        self.z_read_interval = 0.5  # seconds, 2 Hz
        self.z_position_cache = 0

        # soft limit for z-stage
        self.soft_limit_z = None
        self.pending_soft_limit = None
        self.soft_limit_enabled = False
        self.soft_limit_file = "./positions/soft_limit.txt"
        self.load_soft_limit()

        # reference / default velocities
        self.ref_max_xy = 20.0      # mm/s
        self.ref_max_z = 50.0       # mm/s
        self.ref_max_piezo = 10000  # steps/s

        # max velocities start at ref values
        self.max_xy = self.ref_max_xy
        self.max_z = self.ref_max_z
        self.max_piezo = self.ref_max_piezo

        self.vel = [0, 0, 0, 0]
        self.target = [0, 0, 0, 0]

        self.acceleration = 0.2

        self.thread = threading.Thread(target=self.loop)
        self.thread.daemon = True
        self.thread.start()

        # callback for UI
        self.event_callback = None


    # Helpers for GUI implementation
    def set_max_velocity_xy(self, slider_val):
        self.max_xy = self.ref_max_xy * (0.5 + slider_val / 100)
        return self.max_xy  # return actual mm/s

    def set_max_velocity_z(self, slider_val):
        self.max_z = self.ref_max_z * (0.5 + slider_val / 100)
        return self.max_z

    def set_max_velocity_piezo(self, slider_val):
        self.max_piezo = self.ref_max_piezo * (0.5 + slider_val / 100)
        return self.max_piezo

    def move_xy_step(self, dx, dy):
        """Manual step move for GUI buttons"""
        # dx, dy must be in mm!
        if self.standa.connected:
            if dx != 0:
                self.standa.move_relative("x", dx)
            if dy != 0:
                self.standa.move_relative("y", dy)

    def move_z_step(self, dz):
        """Manual step move for GUI buttons"""
        if not self.zstage.connected:
            return
        pos = self.get_positions_raw()
        if pos["z"] is None:
            return
        target = pos["z"] + dz
        if not self.check_z_limit(target):
            if self.event_callback:
                self.event_callback({
                    "type": "soft_limit_hit",
                    "axis": "z",
                    "limit": self.soft_limit_z,
                    "position": pos["z"]
                })
            return

        with self.lock_z:
            self.zstage.move(dz)

    def move_piezo_step(self, dp):
        """Manual step move for GUI buttons"""
        dp = int(dp)
        if self.piezo.connected:
            with self.lock_piezo: 
                self.piezo.move_relative(dp)

    def move_to(self, x_target, y_target, z_target,
            tol_xy=0.5e-3, tol_z=0.5e-3,
            max_iter=100):
        """
        Move X, Y, Z stages to absolute positions (mm) using staged approach:
        1. Absolute move for each axis using stage move_to / move_to_calb.
        2. Closed-loop fine adjustment for residual offsets.
        Blocks until final position reached within tolerances.
        Piezo stage is not included!
        """

        self.running = False  # suspend joystick / loop control

        # minimum step sizes for fine adjustment (mm)
        min_step_xy = 0.0002
        alpha_xy = 0.2  # damping factor for XY fine correction

        # check if z target is outside the soft limit
        if not self.check_z_limit(z_target):
            pos = self.get_positions_raw()
            if self.event_callback:
                self.event_callback({
                    "type": "soft_limit_hit",
                    "axis": "z",
                    "limit": self.soft_limit_z,
                    "position": pos["z"]
                })
            return False

        # 1. Absolute coarse moves
        if self.standa.connected:
            self.standa.move_to("x", x_target)
            self.standa.move_to("y", y_target)

        if self.zstage.connected:
            with self.lock_z:
                self.zstage.move_to(z_target)

        time.sleep(0.05)  # allow positions to settle

        # 2. Fine closed-loop iteration
        for i in range(max_iter):
            pos = self.get_positions_raw()
            dx = x_target - pos["x"] if pos["x"] is not None else 0
            dy = y_target - pos["y"] if pos["y"] is not None else 0
            dz = z_target - pos["z"] if pos["z"] is not None else 0

            done_x = abs(dx) < tol_xy
            done_y = abs(dy) < tol_xy
            done_z = abs(dz) < tol_z

            print(f"Iteration {i}: dx={dx:.6f}, dy={dy:.6f}, dz={dz:.6f}")

            if done_x and done_y and done_z:
                self.running = True
                return True

            # XY fine adjustment with damping
            if self.standa.connected:
                step_x = dx * alpha_xy if not done_x else 0
                step_y = dy * alpha_xy if not done_y else 0

                # enforce minimum step to prevent stall
                if step_x != 0 and abs(step_x) < min_step_xy:
                    step_x = min_step_xy if dx > 0 else -min_step_xy
                if step_y != 0 and abs(step_y) < min_step_xy:
                    step_y = min_step_xy if dy > 0 else -min_step_xy

                if step_x != 0:
                    self.standa.move_relative("x", step_x)
                if step_y != 0:
                    self.standa.move_relative("y", step_y)

            # Z fine adjustment using absolute move
            if self.zstage.connected and not done_z:
                with self.lock_z:
                    self.zstage.move_to(z_target)

            time.sleep(0.1)

        self.running = True
        return False
    
    def set_soft_limit(self, value):
        self.soft_limit_z = value
        self.soft_limit_enabled = True
        with open(self.soft_limit_file, "w") as f:
            f.write(str(self.soft_limit_z))
        self.button_pressed_state["BB"] = True
        self.update_leds()
        if self.event_callback:
            self.event_callback({
                "type": "soft_limit_toggle",
                "enabled": True,
                "value": self.soft_limit_z
            })

    def disable_soft_limit(self):
        self.soft_limit_enabled = False
        self.button_pressed_state["BB"] = False
        self.update_leds()
        if self.event_callback:
            self.event_callback({
                "type": "soft_limit_toggle",
                "enabled": False,
                "value": self.soft_limit_z
            })

    def load_soft_limit(self):
        try:
            with open(self.soft_limit_file, "r") as f:
                self.soft_limit_z = float(f.read().strip())
        except:
            self.soft_limit_z = None

    def check_z_limit(self, target_z):
        """Return True if movement is allowed."""
        if not self.soft_limit_enabled:
            return True
        return target_z <= self.soft_limit_z

    def get_positions(self):
        """Return current positions relative to the zero reference"""
        pos = self.get_positions_raw()  # get actual positions
        if pos["x"] is not None:
            pos["x"] -= self.zero_offset["x"]
        if pos["y"] is not None:
            pos["y"] -= self.zero_offset["y"]
        if pos["z"] is not None:
            pos["z"] -= self.zero_offset["z"]
        if pos["piezo"] is not None:
            pos["piezo"] -= self.zero_offset["piezo"] 
        return pos
    
    def clear_zero(self):
        self.zero_offset = {"x": 0.0, "y": 0.0, "z": 0.0, "piezo": 0}
    
    def get_positions_raw(self):
        """Return the actual stage positions without any zero offset"""
        pos = {}
        try:
            x, y = self.standa.get_position()
            pos["x"] = x
            pos["y"] = y
        except:
            pos["x"] = None
            pos["y"] = None
        try:
            now = time.time()
            if now - self.last_z_read_time > self.z_read_interval:
                with self.lock_z:
                    self.z_position_cache = self.zstage.get_position()
                self.last_z_read_time = now
            pos["z"] = self.z_position_cache
        except:
            pos["z"] = None
        try:
            with self.lock_piezo:
                pos["piezo"] = self.piezo.get_position()
        except:
            pos["piezo"] = None
        return pos
    
    def set_max_velocity_xy(self, slider_val):
        self.max_xy = self.ref_max_xy * (0.5 + slider_val / 100)
        return self.max_xy # return actual mm/s 
    
    def set_max_velocity_z(self, slider_val):
        self.max_z = self.ref_max_z * (0.5 + slider_val / 100)
        return self.max_z 
    
    def set_max_velocity_piezo(self, slider_val):
        self.max_piezo = self.ref_max_piezo * (0.5 + slider_val / 100)
        return self.max_piezo
    
    #--- callback for GUI for joystick -> stage command ---
    def emit_motion_event(self, axis, moving, velocity):
        if self.event_callback:
            self.event_callback({
                "type": "axis_motion",
                "axis": axis,
                "moving": moving,
                "velocity": velocity
            })

    #------- Button handling -------
    def update(self):
        button = self.joystick.last_pressed_button
        self.joystick.last_pressed_button = None
        if button is None:
            return
        axis = {"B0":0, "B1":1, "B2":2, "B3":3}.get(button)
        if axis is not None:
            self.axis_enabled[axis] = not self.axis_enabled[axis]
            if self.event_callback:
                self.event_callback({
                    "type": "axis_button_press",
                    "stage": axis,
                    "enabled": self.axis_enabled[axis],
                })
        if button == "BA":
            new_state_a = not self.button_pressed_state["BA"]
            self.button_pressed_state["BA"] = new_state_a
            if new_state_a:
                self.zero_positions()      # create new zero
            else:
                self.clear_zero()         # delete zero reference
            if self.event_callback:
                self.event_callback({
                    "type": "zero_toggle",
                    "enabled": new_state_a,
                    "position": self.zero_offset
                })        
        if button == "BB":
            new_state_b = not self.button_pressed_state["BB"]
            if new_state_b:
                if self.pending_soft_limit is not None:
                    self.set_soft_limit(self.pending_soft_limit)
                    self.pending_soft_limit = None
                else:
                    pos = self.get_positions_raw()
                    if pos["z"] is not None:
                        self.set_soft_limit(pos["z"])
            else:
                self.disable_soft_limit()
        self.update_leds()

    def update_leds(self):
        def col(enabled):
            return (200, 0, 0) if enabled else (20, 0, 0)

        # A and B buttons
        leda_val = (0, 180) if self.button_pressed_state["BA"] else (0, 5)
        ledb_val = (0, 180) if self.button_pressed_state["BB"] else (0, 5)

        if self.joystick.connected:
            self.joystick.set_leds(
                led0=col(self.axis_enabled[0]),
                led1=col(self.axis_enabled[1]),
                led2=col(self.axis_enabled[2]),
                led3=col(self.axis_enabled[3]),
                leda=leda_val,
                ledb=ledb_val
            )

    def zero_positions(self):
        """Set current positions as zero reference"""
        pos = self.get_positions_raw()  # get actual positions without offsets
        if pos["x"] is not None:
            self.zero_offset["x"] = pos["x"]
        if pos["y"] is not None:
            self.zero_offset["y"] = pos["y"]
        if pos["z"] is not None:
            self.zero_offset["z"] = pos["z"]
        if pos["piezo"] is not None:
            self.zero_offset["piezo"] = pos["piezo"]
        
    
    def knob_to_velocity(self, value, max_velocity):
        """
        Convert knob range (-500..500) to stage velocity
        """

        deadzone = 20
        if abs(value) < deadzone:
            return 0
        velocity = np.sign(value) * (abs(value)/500)**2 * max_velocity
        return velocity

    # loop for fetching joystick changes -> sending to hardware / GUI
    def loop(self):
        last_vz = None
        while self.alive:
            if not self.running:
                time.sleep(0.01)
                continue
            self.update() # process button events
            knobs = self.joystick.knob_values # process knob events
            
            # convert knobs to velocities
            vx = self.knob_to_velocity(knobs[0], self.max_xy) if self.axis_enabled[0] else 0
            vy = self.knob_to_velocity(knobs[1], self.max_xy) if self.axis_enabled[1] else 0
            vz = self.knob_to_velocity(knobs[2], self.max_z)  if self.axis_enabled[2] else 0
            vp = self.knob_to_velocity(knobs[3], self.max_piezo) if self.axis_enabled[3] else 0
        
            # integrate for position-based stages
            dx = vx * self.dt
            dy = vy * self.dt

            # send commands if axis is active
            if self.standa.connected and not self.gui_move_active:
                # standa x-axis
                if self.axis_enabled[0] and dx != 0:
                    self.standa.move_relative("x", dx)
                # standa y-axis
                if self.axis_enabled[1] and dy != 0:
                    self.standa.move_relative("y", dy)
            # piezo stage
            if self.piezo.connected and self.axis_enabled[3]:
                with self.lock_piezo:
                    self.piezo.set_velocity(vp)
            # labjack
            if self.zstage.connected and not self.gui_move_active:
                if self.axis_enabled[2] and vz != 0:
                    pos = self.get_positions_raw()
                    if pos["z"] is not None and self.soft_limit_z is not None:
                        # upward motion (towards the soft limit)
                        if vz > 0 and self.soft_limit_enabled and self.soft_limit_z-pos["z"] < 0.1:
                            predicted = pos["z"] + vz * self.dt
                            # block if we are already above the limit OR would cross it
                            if pos["z"] >= self.soft_limit_z or predicted >= self.soft_limit_z:
                                with self.lock_z:
                                    self.zstage.stop()
                                vz = 0
                                self.running = False
                                if self.event_callback:
                                    self.event_callback({
                                        "type": "soft_limit_hit",
                                        "axis": "z",
                                        "limit": self.soft_limit_z,
                                        "position": pos["z"]
                                    })
                                    
                    # send velocity command
                    if last_vz is None or abs(vz - last_vz) > 1e-3:
                        with self.lock_z:
                            self.zstage.set_velocity(vz)
                        last_vz = vz

                else:
                    # ensure the stage stops when axis disabled
                    if last_vz is None or abs(last_vz) > 1e-6:
                        with self.lock_z:
                            self.zstage.set_velocity(0)
                        last_vz = 0

            # log joystick -> stage command when joystick 
            # changes sign and not zero
            for i, v in enumerate([vx, vy, vz, vp]):
                moving = abs(v) > 1e-6
                direction = 0 if not moving else (1 if v > 0 else -1)
                # detect state change
                if moving != self._last_motion_state[i]:
                    self.emit_motion_event(i, moving, v)
                # optional: detect direction change while moving
                elif moving and direction != self._last_direction[i]:
                    self.emit_motion_event(i, moving, v)
                self._last_motion_state[i] = moving
                self._last_direction[i] = direction

            time.sleep(self.dt)


    def stop_axes(self):
        """Stop movement of all axes immediately"""
        self.running = False
        if self.standa.connected:
            self.standa.stop()
        if self.zstage.connected:
            with self.lock_z:
                self.zstage.stop()
        if self.piezo.connected:
            with self.lock_piezo:
                self.piezo.stop()

        self.running = True


    def stop(self):
        """Shutdown procedure"""
        self.alive = False
        self.running = False
        self.thread.join()
        if self.standa.connected:
            self.standa.stop()
            self.standa.close()
        if self.zstage.connected:
            self.zstage.stop()
            self.zstage.close()
        if self.piezo.connected:
            self.piezo.stop()
            self.piezo.close()
