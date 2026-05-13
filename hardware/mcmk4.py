import pywinusb.hid as hid
import atexit

FAULTY_VALUES = {-12, -63, 12, 63}  # faulty and noisy values


class MCMK4:
    """
    Class for using the Thorlabs MCMK4 Joystick controller
    """

    def __init__(self):
        self.connected = False
        self.knob_values = [0] * 4
        self.button_values = [False] * 6
        self.last_button_code = 0
        self.last_pressed_button = None
        self.button_map = {
            1: 0,   # B0
            2: 1,   # B1
            4: 2,   # B2
            8: 3,   # B3
            16: 4,  # BA
            32: 5   # BB
        }

        self.counter = 0
        self.skip = 0

        all_hids = hid.find_all_hid_devices()
        mcmk4 = False
        try:
            if all_hids:
                for index, device in enumerate(all_hids):
                    device_name = "{0.vendor_name} {0.product_name}".format(device)
                    mcmk4 = device_name.startswith("Thorlabs MCMK4")
                    if mcmk4:
                        print("{0.vendor_name} {0.product_name}"
                            "(vID=0x{1:04x}, pID=0x{2:04x})"
                            "".format(device, device.vendor_id, device.product_id))
                        break

                if not mcmk4:
                    print("Joystick is not connected")
                    return

                self.device = all_hids[index]
                self.device.open()
                self.connected = True
                self.set_handler(self.parse_input)

                # initialize LEDs (all bright red)
                self.init_leds()

                print("Joystick initialized!")
                atexit.register(self.close)

            else:
                print("There's not any non system HID class device available")
                return
        except Exception:
            print("Error occured during initialization of the Joystick.")
            return

    def set_handler(self, func):
        self.device.set_raw_data_handler(func)

    def parse_input(self, report):
        data = bytearray(report)
        knob_bytes = data[1:-1]
        knob_values = [int.from_bytes(reversed(knob_bytes[i:i+2]))
                       for i in range(0, 8, 2)]
        knob_values_mapped = [self.map_joystick_to_output(v) for v in knob_values]
        self.knob_values = self.filter_joystick(knob_values_mapped)

        try:
            btn_index = self.button_map.get(data[9], None)
            button_code = data[9]
            # detect press edge (new press event)
            if button_code != 0 and button_code != self.last_button_code:
                btn_index = self.button_map.get(button_code, None)
                if btn_index is not None:
                    self.button_values[btn_index] = not self.button_values[btn_index]
                    buttons = ["B0","B1","B2","B3","BA","BB"]
                    self.last_pressed_button = buttons[btn_index]
            self.last_button_code = button_code

        except IndexError:
            pass

        return self.knob_values, self.button_values

    def init_leds(self):
        """
        Convert LED state to colours and send to device
        """
        red = (255, 0, 0)
        # BA / BB use (G,R)
        leda = (0, 5)
        ledb = (0, 5)
        self.set_leds(red, red, red, red, leda, ledb)


    def filter_joystick(self, values):
        deadband = 5
        self.counter += 1

        if self.counter >= self.skip:
            self.counter = 0

            # remove known faulty values
            clean_values = [0 if v in FAULTY_VALUES else v for v in values]

            # detect active knobs
            active_indices = [i for i, val in enumerate(clean_values) if abs(val) > deadband]
            if not active_indices:
                return [0] * 4

            # select knob with largest absolute value
            active_idx = max(active_indices, key=lambda i: abs(clean_values[i]))

            filtered_values = [0] * 4
            filtered_values[active_idx] = int(clean_values[active_idx])
            return filtered_values
        else:
            return [0] * 4

    def set_leds(self, led0=(0,0,0), led1=(0,0,0), led2=(0,0,0),
                 led3=(0,0,0), leda=(0,0), ledb=(0,0)):
        report = bytearray(18)
        report[0] = 0
        report[1] = led0[2]
        report[2] = led0[1]
        report[3] = led0[0]
        report[4] = led1[2]
        report[5] = led1[1]
        report[6] = led1[0]
        report[7] = led2[2]
        report[8] = led2[1]
        report[9] = led2[0]
        report[10] = led3[2]
        report[11] = led3[1]
        report[12] = led3[0]
        report[13] = leda[0]
        report[14] = leda[1]
        report[15] = ledb[0]
        report[16] = ledb[1]
        report[17] = 0

        self.device.send_output_report(report)

    def map_joystick_to_output(self, value, out_min=1, out_max=500):
        scale = (out_max - out_min) / (1022 - 512)

        if value != 511:
            return int(round((value - 511) * scale))
        else:
            return 0

    def close(self):
        # turn all LEDs off
        self.set_leds(
            led0=(0,0,0),
            led1=(0,0,0),
            led2=(0,0,0),
            led3=(0,0,0),
            leda=(0,0),
            ledb=(0,0)
        )
        self.device.close()