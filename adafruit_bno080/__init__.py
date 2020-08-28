# SPDX-FileCopyrightText: Copyright (c) 2020 Bryan Siepert for Adafruit Industries
#
# SPDX-License-Identifier: MIT
"""
`adafruit_bno080`
================================================================================

Helper library for the Hillcrest Laboratories BNO080 IMU


* Author(s): Bryan Siepert

Implementation Notes
--------------------

**Hardware:**

* `Adafruit BNO080 Breakout <https:www.adafruit.com/products/47XX>`_

**Software and Dependencies:**

* Adafruit CircuitPython firmware for the supported boards:
  https:# github.com/adafruit/circuitpython/releases

* `Adafruit's Bus Device library <https:# github.com/adafruit/Adafruit_CircuitPython_BusDevice>`_
"""
__version__ = "0.0.0-auto.0"
__repo__ = "https:# github.com/adafruit/Adafruit_CircuitPython_BNO080.git"

from struct import unpack_from, pack_into
from collections import namedtuple
from time import sleep, monotonic, monotonic_ns
from micropython import const

# TODO: shorten names
# Channel 0: the SHTP command channel
_BNO_CHANNEL_SHTP_COMMAND = const(0)
BNO_CHANNEL_EXE = const(1)
_BNO_CHANNEL_CONTROL = const(2)
_BNO_CHANNEL_INPUT_SENSOR_REPORTS = const(3)
_BNO_CHANNEL_WAKE_INPUT_SENSOR_REPORTS = const(4)
_BNO_CHANNEL_GYRO_ROTATION_VECTOR = const(5)

_BNO_CMD_GET_FEATURE_REQUEST = const(0xFE)
_BNO_CMD_SET_FEATURE_COMMAND = const(0xFD)
_BNO_CMD_GET_FEATURE_RESPONSE = const(0xFC)
_BNO_CMD_BASE_TIMESTAMP = const(0xFB)

_BNO_CMD_TIMESTAMP_REBASE = const(0xFA)

_SHTP_REPORT_PRODUCT_ID_RESPONSE = const(0xF8)
_SHTP_REPORT_PRODUCT_ID_REQUEST = const(0xF9)

_BNO_CMD_FRS_WRITE_REQUEST = const(0xF7)
_BNO_CMD_FRS_WRITE_DATA = const(0xF6)
_BNO_CMD_FRS_WRITE_RESPONSE = const(0xF5)

_BNO_CMD_FRS_READ_REQUEST = const(0xF4)
_BNO_CMD_FRS_READ_RESPONSE = const(0xF3)

_BNO_CMD_COMMAND_REQUEST = const(0xF2)
_BNO_CMD_COMMAND_RESPONSE = const(0xF1)


# Calibrated Acceleration (m/s2)
_BNO_REPORT_ACCELEROMETER = const(0x01)
# Calibrated gyroscope (rad/s).
_BNO_REPORT_GYROSCOPE = const(0x02)
# Magnetic field calibrated (in µTesla). The fully calibrated magnetic field measurement.
_BNO_REPORT_MAGNETIC_FIELD = const(0x03)
# Linear acceleration (m/s2). Acceleration of the device with gravity removed
_BNO_REPORT_LINEAR_ACCELERATION = const(0x04)
# Rotation Vector
_BNO_REPORT_ROTATION_VECTOR = const(0x05)

_DEFAULT_REPORT_INTERVAL = const(50000)  # in microseconds = 50ms
_QUAT_READ_TIMEOUT = 0.500  # timeout in seconds
_PACKET_READ_TIMEOUT = 15.000  # timeout in seconds
_BNO080_CMD_RESET = const(0x01)
_QUAT_Q_POINT = const(14)
_BNO_HEADER_LEN = const(4)

_Q_POINT_14_SCALAR = 2 ** (14 * -1)
# _Q_POINT_12_SCALAR = 2 ** (12 * -1)
# _Q_POINT_10_SCALAR = 2 ** (10 * -1)
_Q_POINT_9_SCALAR = 2 ** (9 * -1)
_Q_POINT_8_SCALAR = 2 ** (8 * -1)
_Q_POINT_4_SCALAR = 2 ** (4 * -1)

_GYRO_SCALAR = _Q_POINT_9_SCALAR
_ACCEL_SCALAR = _Q_POINT_8_SCALAR
_QUAT_SCALAR = _Q_POINT_14_SCALAR
_MAG_SCALAR = _Q_POINT_4_SCALAR
# _QUAT_RADIAN_ACCURACY_SCALAR = _Q_POINT_12_SCALAR
# _ANGULAR_VELOCITY_SCALAR = _Q_POINT_10_SCALAR

_ENABLED_SENSOR_REPORTS = {
    _BNO_REPORT_ACCELEROMETER : (_ACCEL_SCALAR, 3),
    # _BNO_REPORT_GYROSCOPE : (_GYRO_SCALAR, 3),
    # _BNO_REPORT_MAGNETIC_FIELD : (_MAG_SCALAR, 3),
    # _BNO_REPORT_LINEAR_ACCELERATION : (_ACCEL_SCALAR, 3),
    # _BNO_REPORT_ROTATION_VECTOR : (_QUAT_SCALAR, 4),
}

DATA_BUFFER_SIZE = const(512)  # data buffer size. obviously eats ram
PacketHeader = namedtuple(
    "PacketHeader",
    ["channel_number", "sequence_number", "data_length", "packet_byte_count",],
)

REPORT_STATUS = ["Unreliable", "Accuracy low", "Accuracy medium", "Accuracy high"]


def _elapsed(start_time):
    return monotonic() - start_time


def debug_print(func):
    """Print the runtime of the decorated function"""

    def wrapper_debug(*args, **kwargs):
        debug_state = args[0]._debug
        args[0]._debug = True
        value = func(*args, **kwargs)
        args[0]._debug = debug_state
        print("debugged", func.__name__)
        return value

    return wrapper_debug

def elapsed_time(func):
    """Print the runtime of the decorated function"""

    def wrapper_timer(*args, **kwargs):
        start_time = monotonic_ns()  # 1
        value = func(*args, **kwargs)
        end_time = monotonic_ns()  # 2
        run_time = end_time - start_time  # 3
        print("Finished", func.__name__, "in", (run_time / 1000000.0), "ms")
        return value

    return wrapper_timer

def _parse_report_data(packet, debug=False):
    # TODO: Parse and store time offset
    # Timestamp offset
    # 0 Report ID=0xFB
    # 1 Base Delta LSB: relative to transport-defined reference point. Signed. Units are 100 microsecond ticks.
    # 2 Base Delta
    # 3 Base Delta
    # 4 Base Delta MSB
    report_id = packet.report_id
    if report_id == _BNO_CMD_BASE_TIMESTAMP:
        report_id = packet.data[5]
    scalar, count = _ENABLED_SENSOR_REPORTS[report_id]
    if debug: print("\t\tDBG::Scaling %d bytes of sensor data with scalar %.3f)"%(scalar, count))
    results = []
    base_offset = 9
    for _offset_idx in range(count):
        total_offset = base_offset + (_offset_idx * 2)
        raw_data = unpack_from("<h", packet.data, offset=total_offset)[0]
        scaled_data = raw_data * scalar
        if debug: print("\t\tDBG:: [%d] raw: %d scaled: %.3f"%(_offset_idx, raw_data, scaled_data))
        results.append(scaled_data)

    return tuple(results)


class Packet:
    """A class representing a Hillcrest LaboratorySensor Hub Transport packet"""

    def __init__(self, packet_bytes):
        self.header = self.header_from_buffer(packet_bytes)
        data_end_index = self.header.data_length + _BNO_HEADER_LEN
        self.data = packet_bytes[_BNO_HEADER_LEN:data_end_index]

    @elapsed_time
    def __str__(self):
        from .debug import channels, reports

        length = self.header.packet_byte_count
        outstr = "\n\t\t********** Packet *************\n"
        outstr += "\t\tDBG:: HEADER:\n"

        outstr += "\t\tDBG:: Len: %d\n" % (self.header.data_length)
        outstr += "\t\tDBG:: Channel: %s\n" % channels[self.header.channel_number]
        if self.channel_number == _BNO_CHANNEL_INPUT_SENSOR_REPORTS:
            if self.report_id in reports:
                outstr += "\t\tDBG:: \tReport Type: %s\n" % reports[self.report_id]
            else:
                outstr += "\t\tDBG:: \t** UNKNOWN Report Type **: %s\n" % hex(
                    self.report_id
                )

            if (
                self.report_id > 0xF0
                and len(self.data) >= 6
                and self.data[5] in reports
            ):
                outstr += "\t\tDBG:: \tSensor Report Type: %s\n" % reports[self.data[5]]

        outstr += "\t\tDBG:: Sequence number: %s\n" % self.header.sequence_number
        outstr += "\n"
        outstr += "\t\tDBG:: Data:"

        for idx, packet_byte in enumerate(self.data[:length]):
            packet_index = idx + 4
            if (packet_index % 4) == 0:
                outstr += "\n\t\tDBG::[0x{:02X}] ".format(packet_index)
            outstr += "0x{:02X} ".format(packet_byte)
        outstr += "\n"
        outstr += "\t\t*******************************\n"

        # for _idx, _byte in enumerate(self.data):
        #     outstr += "\t[%0.2d] %x\n" % (_idx, _byte)
        return outstr

    @property
    def report_id(self):
        """The Packet's Report ID"""
        return self.data[0]

    @property
    def channel_number(self):
        """The packet channel"""
        return self.header.channel_number

    @classmethod
    def header_from_buffer(cls, packet_bytes):
        """Creates a `PacketHeader` object from a given buffer"""
        packet_byte_count = unpack_from("<H", packet_bytes)[0]
        packet_byte_count &= ~0x8000
        channel_number = unpack_from("<B", packet_bytes, offset=2)[0]
        sequence_number = unpack_from("<B", packet_bytes, offset=3)[0]
        data_length = max(0, packet_byte_count - 4)

        header = PacketHeader(
            channel_number, sequence_number, data_length, packet_byte_count
        )
        return header

    @classmethod
    def is_error(cls, header):
        """Returns True if the header is an error condition"""

        if header.channel_number > 5:
            return True
        if header.packet_byte_count == 0xFFFF and header.sequence_number == 0xFF:
            return True
        return False


class BNO080:
    """Library for the BNO080 IMU from Hillcrest Laboratories

        :param ~busio.I2C i2c_bus: The I2C bus the BNO080 is connected to.

    """

    def __init__(self, debug=False):
        self._debug = debug
        self._dbg("********** __init__ *************")
        self._data_buffer = bytearray(DATA_BUFFER_SIZE)
        # TODO: this is wrong there should be one per channel per direction

        self._sequence_number = [0, 0, 0, 0, 0, 0]
        # self._sequence_number = {"in": [0, 0, 0, 0, 0, 0], "out": [0, 0, 0, 0, 0, 0]}
        # sef
        self._wait_for_initialize = True
        self._init_complete = False
        self._id_read = False
        # for saving the most recent reading when decoding several packets
        self._readings = {}
        self.initialize()

    def initialize(self):
        """Initialize the sensor"""
        self.reset()
        if not self._check_id():
            raise RuntimeError("Could not read ID")
        # TODO: _ENABLED_SENSOR_REPORTS
        self._enable_feature(_BNO_REPORT_GYROSCOPE)  # gyro
        self._enable_feature(_BNO_REPORT_ACCELEROMETER)  # accelerometer
        self._enable_feature(_BNO_REPORT_LINEAR_ACCELERATION)  # linear acceleration
        self._enable_feature(_BNO_REPORT_ROTATION_VECTOR)  # quaternion
        self._enable_feature(_BNO_REPORT_MAGNETIC_FIELD)  # magnetometer

    @property
    @elapsed_time
    def magnetic(self):
        """A tuple of the current magnetic field measurements on the X, Y, and Z axes"""

        debug_state = self._debug
        self._debug = True

        while True:  # add timeout
            new_packet = self._wait_for_packet_type(_BNO_CHANNEL_INPUT_SENSOR_REPORTS)
            self._dbg("Got sensor report:")
            if self._debug:
                print(new_packet)
            if new_packet.data[5] != _BNO_REPORT_MAGNETIC_FIELD:
                continue

            mag_tuple = _parse_report_data(new_packet, _MAG_SCALAR)

            self._debug = debug_state
            return mag_tuple

    @property
    def quaternion(self):
        """A quaternion representing the current rotation vector"""
        while True:  # add timeout
            new_packet = self._wait_for_packet_type(_BNO_CHANNEL_INPUT_SENSOR_REPORTS)
            self._dbg("Got sensor report:")
            if self._debug:
                print(new_packet)
            if new_packet.data[5] != _BNO_REPORT_ROTATION_VECTOR:
                self._dbg("WRONG REPORT TYPEEEEE")
                continue

            return _parse_report_data(new_packet, _QUAT_SCALAR, 4)

    @property
    def linear_acceleration(self):
        """A tuple representing the current linear acceleration values on the X, Y, and Z
        axes in meters per second squared"""
        while True:  # add timeout
            new_packet = self._wait_for_packet_type(_BNO_CHANNEL_INPUT_SENSOR_REPORTS)
            if self._debug:
                print(new_packet)
            if new_packet.data[5] != _BNO_REPORT_LINEAR_ACCELERATION:
                continue

            return _parse_report_data(new_packet, _ACCEL_SCALAR)

    @property
    def acceleration(self):
        """A tuple representing the acceleration measurements on the X, Y, and Z
        axes in meters per second squared"""
        # receive packets, and dump until you get an accelerometer packet
        while True:  # add timeout
            new_packet = self._wait_for_packet_type(_BNO_CHANNEL_INPUT_SENSOR_REPORTS)
            self._dbg("Got sensor report:")
            if self._debug:
                print(new_packet)
            if new_packet.data[5] != _BNO_REPORT_ACCELEROMETER:
                continue

            return _parse_report_data(new_packet, _ACCEL_SCALAR)

    @property
    def gyro(self):
        """A tuple representing Gyro's rotation measurements on the X, Y, and Z
        axes in radians per second"""
        # receive packets, and dump until you get a quat packet
        while True:  # add timeout
            new_packet = self._wait_for_packet_type(_BNO_CHANNEL_INPUT_SENSOR_REPORTS)
            self._dbg("Got sensor report:")
            if self._debug:
                print(new_packet)

            if new_packet.data[5] != _BNO_REPORT_GYROSCOPE:
                continue

            return _parse_report_data(new_packet, _GYRO_SCALAR, 3)

    def _store_sensor_report(self, packet):
        self._reading[packet.report_id] = _parse_report_data(packet, self._debug)

    def _process_available_packets(self):
        while self._data_ready:
            new_packet = self._read_packet()
            self._handle_packet(new_packet)

    def _wait_for_packet_type(self, channel_number, report_id=None, timeout=5.0):
        if report_id:
            report_id_str = " with report id %s" % hex(report_id)
        else:
            report_id_str = ""
        self._dbg("** Waiting for packet on channel", channel_number, report_id_str)
        start_time = monotonic()
        while _elapsed(start_time) < timeout:
            new_packet = self._wait_for_packet()

            if new_packet.channel_number == channel_number:
                if report_id:
                    if new_packet.report_id == report_id:
                        return new_packet
                else:
                    return new_packet
            self._handle_packet(new_packet)

        raise RuntimeError("Timed out waiting for a packet on channel", channel_number)

    def _wait_for_packet(self, timeout=_PACKET_READ_TIMEOUT):
        start_time = monotonic()
        while _elapsed(start_time) < timeout:
            if not self._data_ready:
                continue

            self._dbg("")
            self._dbg("packet ready reading")
            new_packet = self._read_packet()
            # new_packet = Packet(self._data_buffer)
            if self._debug:
                print(new_packet)
            return new_packet
        raise RuntimeError("Timed out waiting for a packet")

    # update the cached sequence number so we know what to increment from
    # TODO: this is wrong there should be one per channel per direction
    def _update_sequence_number(self, new_packet, is_write=False):
        channel = new_packet.channel_number
        seq = new_packet.header.sequence_number
        self._sequence_number[channel] = seq

    def _handle_packet(self, packet):
        if self._debug:
            self._dbg("Handling packet:")
            print(packet)

        if packet.channel_number == _BNO_CHANNEL_INPUT_SENSOR_REPORTS and packet.report_id in [_ENABLED_SENSOR_REPORTS]:
            self._store_sensor_report(packet)

        # advertisement match on channel+seq, len
        # DBG::[  0] 0x14 0x81 0x00 0x01
        # DBG::[  4] 0x00 0x01 0x04 0x00

        if packet.channel_number == _BNO_CHANNEL_SHTP_COMMAND:
            if packet.header.data_length == 272:
                self._dbg("Got 272 len packet on channel 0")
                self._wait_for_initialize = True
                self._init_complete = False
                self._id_read = False

        # ch 1 command 1 = reset
        # DBG::[  0] 0x05 0x80 0x01 0x01
        # DBG::[  4] 0x01
        if packet.channel_number == BNO_CHANNEL_EXE:
            if packet.data[0] == 1:
                self._dbg("********** Found reset packet! ************")
                self._init_complete = False
                self._dbg("...sleeping")
                sleep(1)
                self._dbg("reinitializing")
                self.initialize()

        # 0xF1 == command response Command is 0x84? - unsolicited initialize
        # DBG::[  0] 0x14 0x80 0x02 0x01
        # DBG::[  4] 0xF1 0x00 0x84 0x00
        # DBG::[  8] 0x00 0x00 0x01 0x00
        # DBG::[ 12] 0x00 0x00 0x00 0x00
        # DBG::[ 16] 0x00 0x00 0x00 0x00
        if packet.channel_number == _BNO_CHANNEL_CONTROL:
            if packet.report_id == _BNO_CMD_COMMAND_RESPONSE:
                self._dbg("Got command response")
                if packet.data[2] == 0x84:
                    self._dbg("Got unsolicited init response")
                    if self._wait_for_initialize:
                        self._wait_for_initialize = False
                        self._init_complete = True

                    else:
                        raise RuntimeError(
                            "Unsolicted init received before Advertisement"
                        )

        # Ch 2 ID Response
        # DBG::[  0] 0x14 0x80 0x02 0x03
        # DBG::[  4] 0xF8 0x03 0x03 0x02
        # DBG::[  8] 0x98 0xA4 0x98 0x00
        # DBG::[ 12] 0x72 0x01 0x00 0x00
        # DBG::[ 16] 0x07 0x00 0x00 0x00

        # Ch 3, ReportID: 0xFB timestamp
        # DBG::[  0] 0x17 0x80 0x03 0x01
        # DBG::[  4] 0xFB 0x17 0x00 0x00
        # DBG::[  8] 0x00 0x05 0x00 0x00
        # DBG::[ 12] 0x00 0x3D 0xFD 0xF4
        # DBG::[ 16] 0xFD 0xAB 0x07 0x72
        # DBG::[ 20] 0x3F 0x44 0x32



	# self._data_buffer[0] = SHTP_REPORT_SET_FEATURE_COMMAND	 # Set feature command. Reference page 55
	# self._data_buffer[1] = reportID							   # Feature Report ID. 0x01 = Accelerometer, 0x05 = Rotation vector
	# self._data_buffer[2] = 0								   # Feature flags

    # self._data_buffer[3] = 0								   # Change sensitivity (LSB)
	# self._data_buffer[4] = 0								   # Change sensitivity (MSB)

	# self._data_buffer[5] = (microsBetweenReports >> 0) & 0xFF  # Report interval (LSB) in microseconds. 0x7A120 = 500ms
	# self._data_buffer[6] = (microsBetweenReports >> 8) & 0xFF  # Report interval
	# self._data_buffer[7] = (microsBetweenReports >> 16) & 0xFF # Report interval
	# self._data_buffer[8] = (microsBetweenReports >> 24) & 0xFF # Report interval (MSB)

    # self._data_buffer[9] = 0								   # Batch Interval (LSB)
	# self._data_buffer[10] = 0								   # Batch Interval
	# self._data_buffer[11] = 0								   # Batch Interval
	# self._data_buffer[12] = 0								   # Batch Interval (MSB)

    # self._data_buffer[13] = (specificConfig >> 0) & 0xFF	   # Sensor-specific config (LSB)
	# self._data_buffer[14] = (specificConfig >> 8) & 0xFF	   # Sensor-specific config
	# self._data_buffer[15] = (specificConfig >> 16) & 0xFF	  # Sensor-specific config
	# self._data_buffer[16] = (specificConfig >> 24) & 0xFF	  # Sensor-specific config (MSB)


    @staticmethod
    def _get_feature_enable_report(feature_id):
        # TODO !!! ALLOCATION !!!
        set_feature_report = bytearray(17)
        set_feature_report[0] = _BNO_CMD_SET_FEATURE_COMMAND
        set_feature_report[1] = feature_id
        pack_into("<I", set_feature_report, 5, _DEFAULT_REPORT_INTERVAL)
        return set_feature_report

    def _enable_feature(self, feature_id):
        self._dbg("Enabling feature id:", feature_id)

        set_feature_report = self._get_feature_enable_report(feature_id)
        self._send_packet(_BNO_CHANNEL_CONTROL, set_feature_report)
        while True:
            packet = self._wait_for_packet_type(
                _BNO_CHANNEL_CONTROL, _BNO_CMD_GET_FEATURE_RESPONSE
            )
            if self._debug:
                print(packet)

            if packet.data[1] == feature_id:
                if (
                    feature_id == _BNO_REPORT_ROTATION_VECTOR
                ):  # check for other vector types as well
                    self._readings[feature_id] = (0.0, 0.0, 0.0, 0.0)
                else:
                    self._readings[feature_id] = (0.0, 0.0, 0.0)
                self._dbg("Enabled")
                return True

        return False

    def _check_id(self):

        self._dbg("\n********** READ ID **********")
        if self._id_read:
            return True
        data = bytearray(2)
        data[0] = _SHTP_REPORT_PRODUCT_ID_REQUEST
        data[1] = 0  # padding
        self._dbg("\n** Sending ID Request Report **")
        self._send_packet(_BNO_CHANNEL_CONTROL, data)
        self._dbg("\n** Waiting for packet **")
        # _a_ packet arrived, but which one?
        while True:
            self._wait_for_packet_type(
                _BNO_CHANNEL_CONTROL, _SHTP_REPORT_PRODUCT_ID_RESPONSE
            )
            sensor_id = self._parse_sensor_id()
            if sensor_id:
                self._id_read = True
                return True
            self._dbg("Packet didn't have sensor ID report, trying again")

        return False

    def _parse_sensor_id(self):
        if not self._data_buffer[4] == _SHTP_REPORT_PRODUCT_ID_RESPONSE:
            return None
        # 0 Report ID = 0xF8
        # 14 Reserved
        sw_major = self._get_data(2, "<B")
        sw_minor = self._get_data(3, "<B")
        sw_patch = self._get_data(12, "<H")
        sw_part_number = self._get_data(4, "<I")
        sw_build_number = self._get_data(8, "<I")

        self._dbg("")
        self._dbg("*** Part Number: %d" % sw_part_number)
        self._dbg(
            "*** Software Version: %d.%d.%d" % (sw_major, sw_minor, sw_patch), end=""
        )
        self._dbg(" Build: %d" % (sw_build_number))
        self._dbg("")
        return sw_part_number

    def _dbg(self, *args, **kwargs):
        if self._debug:
            print("DBG::\t\t\t\t", *args, **kwargs)

    def _get_data(self, index, fmt_string):
        # index arg is not including header, so add 4 into data buffer
        data_index = index + 4
        return unpack_from(fmt_string, self._data_buffer, offset=data_index)[0]

    def _read_header(self):
        """Reads the first 4 bytes available as a header"""
        with self.bus_device_obj as bus_dev:  # pylint:disable=no-member
            bus_dev.readinto(self._data_buffer, end=4)
        packet_header = Packet.header_from_buffer(self._data_buffer)
        self._dbg(packet_header)
        return packet_header

    # @elapsed_time
    # def _print_buffer(self, write_full=False):
    #     if not self._debug:
    #         return
    #     header = Packet.header_from_buffer(self._data_buffer)
    #     length = header.packet_byte_count
    #     if write_full:
    #         print(" writing complete buffer")
    #         length = len(self._data_buffer)

    #     for idx, packet_byte in enumerate(self._data_buffer[:length]):
    #         if (idx % 4) == 0:
    #             print("\n\t\tDBG::[%3d] " % idx, end="")
    #         print("0x{:02X} ".format(packet_byte), end="")
    #     print("")

    # pylint:disable=no-self-use
    @property
    def _data_ready(self):
        raise RuntimeError("Not implemented")

    def reset(self):
        """Reset the sensor to an initial unconfigured state"""
        raise RuntimeError("Not implemented")

    def _send_packet(self, channel, data):
        raise RuntimeError("Not implemented")

    def _read_packet(self):
        raise RuntimeError("Not implemented")

    def _send_packet(self, channel, data):
        raise RuntimeError("Not implemented")
