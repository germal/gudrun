#!/usr/bin/env python
"""Read data continuously from Adafruit 9 DoF "IMU".

Arduino struct-passing method thanks to Jean Rabault:
https://folk.uio.no/jeanra/Microelectronics/TransmitStructArduinoPython.html"""

from __future__ import print_function
from serial import Serial
from serial.serialutil import SerialException
import struct


def get_port_address(verbose=False):
    import os.path
    from subprocess import check_output
    
    ss_config_path = os.path.join(os.path.dirname(__file__), 'device_search_string.txt')

    if os.path.isfile(ss_config_path):
        with open(ss_config_path, 'r') as f:
            search_string = f.read().strip()
    else:
        search_string = 'Arduino_LLC_Arduino_Leonardo_8037:2341'
        from warnings import warn
        warn('No %s; using default search string of %s.' % (ss_config_path, search_string))

    if verbose: print('Searching for device "%s" ...' % search_string)
    
    cmd = ['rosrun', 'gudrun_sensors', 'get_usb_device_by_ID.py', search_string]
    if verbose: print('$ ' + ' '.join(cmd))
    addr = check_output(cmd).strip()

    if addr == 'device_not_found':
        raise IOError("Device '%s' wasn't found." % search_string)
    
    return addr


class IMU(object):
    """A class to stream the serial messages from Arduino."""

    def __init__(self, num_values=9, verbose=0):
        SIZE_STRUCT = num_values * 4
        self.SIZE_STRUCT = SIZE_STRUCT
        self.verbose = verbose
        try:
            self.connect()
        except IOError:
            self.attempt_reconnect()

    def connect(self):
        self.port = Serial(get_port_address(), 115200)
        self.port.flushInput()

    def read_one_value(self):
        """Wait for next serial message from the Arduino,
        and read the whole message as a structure."""
        read = False

        try:

            while not read:
                myByte = self.port.read(1)
                if myByte == 'S':
                    data = self.port.read(self.SIZE_STRUCT)
                    myByte = self.port.read(1)
                    if myByte == 'E':

                        # is  a valid message struct
                        structure = '<' + 'f' * int(self.SIZE_STRUCT / 4)
                        new_values = list(struct.unpack(structure, data))

                        read = True

                        # sensors_vec_t   acceleration;         /**< acceleration values are in meter per second per second (m/s^2) */
                        # sensors_vec_t   gyro;                 /**< gyroscope values are in rad/s */
                        # sensors_vec_t   magnetic;             /**< magnetic vector values are in micro-Tesla (uT) */
                        # sensors_vec_t   orientation;          /**< orientation values are in degrees */

                        # convert micro-Tesla to Tesla
                        for i in range(6, 9):
                            new_values[i] = new_values[i] / 1000.

                        # convert roll,pitch,heading to radians
                        if len(new_values) > 9:
                            for i in range(9, 12):
                                new_values[i] = new_values[i] * 3.14159 / 180.

                        return new_values

        except SerialException as e:
            self.attempt_reconnect()

        return None

    def stream(self):
        """Convenience loop reading packets continuously.

        e.g.
        >>> imu = IMU()
        >>> for packet in imu.stream():
        ...     ax, ay, az = packet[:3]
        """
        while True:
            yield self.read_one_value()

    def attempt_reconnect(self):
        """Try to recoonnect repeatedly, with limited exponential backoff."""
        from warnings import warn
        from time import sleep

        backoff = .1
        backoff_max = 10

        while True:

            msg = 'Disconnected? Attempting reconnection in %s seconds (max %s).' % (backoff, backoff_max)
            # warn(msg)
            print(msg)
            sleep(backoff)

            try:
                self.connect()
                print('Connected!')
                break

            except IOError:
                backoff = min(1.5 * backoff, backoff_max)


def ros_publish(rate=None):
    """Send the data to ROS."""
    import rospy
    from sensor_msgs.msg import Imu, MagneticField

    from std_msgs.msg import Float32
    from math import sqrt

    FRAME_NAME = 'imu'

    rospy.init_node('imu')

    # Set up our publishers and persistent message objects.
    def set_cov_diagonal(arr, s):
        """Fill out a covariance matrix along its diagonal."""
        try:
            s = list(s)
        except TypeError:
            s = [s]*3
        for i, si in zip([0, 4, 8], s):
            arr[i] = si

    # Apparently the rule-of-thumb is that you can use your publishing rate as a rough
    # guess for what your queue size should be? My rate is more like 250 Hz, though, so idunno.
    estimated_frequency = rate or 100

    # Publish the linear accelerations and angular velocities.
    publisher_imu_data_raw = rospy.Publisher('imu/data_raw', Imu, queue_size=estimated_frequency)
    msg_imu_data_raw = Imu()
    msg_imu_data_raw.header.frame_id = FRAME_NAME

    # We don't publish orientation in this pseudo-Imu topic, so, per the docs, 
    # we set the first element of the corresponding covariance matrix to -1.
    msg_imu_data_raw.orientation_covariance[0] = -1  

    # Publish the magnetometer.
    publisher_imu_mag = rospy.Publisher('imu/mag', MagneticField, queue_size=estimated_frequency)
    msg_imu_mag = MagneticField()
    msg_imu_mag.header.frame_id = FRAME_NAME

    # I got these covariance numbers in a super-scientific way by watching rqt
    # and eyeballing the typical range of quiescent variation.
    set_cov_diagonal(msg_imu_data_raw.linear_acceleration_covariance, 0.15)
    set_cov_diagonal(msg_imu_data_raw.angular_velocity_covariance, 0.005)
    set_cov_diagonal(msg_imu_mag.magnetic_field_covariance, 0.0007)

    # Monitoring this topic will convince you that the static field of the motor's permanent magnet is fierce.
    # It might be relatively constant, though.
    # TODO: Do hard-iron magnetometer compensation.
    publisher_mag_magnitude = rospy.Publisher('imu/mag_magnitude', Float32, queue_size=estimated_frequency)

    # This needs to match what the firmware is sending (look for the `#define DO_FUSION` line).
    # Setting to false for now, since the Madgwick code seems to work better,
    # and doing that computation on the firmware decreases our publish rate
    # from 250 Hz to "only" about 196 Hz.
    fetch_device_fused = False
    imu = IMU(num_values=12 if fetch_device_fused else 9)

    # Maybe we throttle; maybe not. Not sure what's best practice here.
    # Also, if we don't read, will earlier piece of the pipeline from the sensor chips buffer??
    # I don't think we want that.
    if rate is not None:
        dt = 1. / rate
        t_last = rospy.get_time() - dt - 1  # Ensure we'll publish on the first loop.

    for data in imu.stream():
        if rospy.is_shutdown():
            break

        # Sometimes the IMU will return None.
        if data:

            if rate is not None: t = rospy.get_time()

            if rate is None or t >= t_last + dt:

                # First three data values are linear accelerations.
                msg = msg_imu_data_raw
                publish = publisher_imu_data_raw.publish
                msg_imu_data_raw.linear_acceleration.x, msg.linear_acceleration.y, msg.linear_acceleration.z = data[0:3]

                # Next three are angular velocities.
                msg.angular_velocity.x, msg.angular_velocity.y, msg.angular_velocity.z = data[3:6]

                # Apply emperical anti-drift offsets.
                # These were obtained by letting the car sit still on a desk, and watching rqt.
                msg.angular_velocity.x -= .035
                msg.angular_velocity.y -= .0125
                msg.angular_velocity.z -= .01625

                # Though we probably won't use it in the Madgwick filter,
                #  we'll also extract and publish the firmware's fused orientation.
                if len(data) > 9:
                    from tf.transformations import quaternion_from_euler
                    qx, qy, qz, qw = quaternion_from_euler(*data[9:12])
                    msg.orientation.x = qx
                    msg.orientation.y = qy
                    msg.orientation.z = qz
                    msg.orientation.w = qw


                # Stamp and publish the linear acceleration/angular velocity pseudo-Imu message.
                msg.header.stamp = rospy.Time.now()
                publish(msg)

                # Final three values are magnetometer.
                msg = msg_imu_mag
                publish = publisher_imu_mag.publish
                msg.magnetic_field.x, msg.magnetic_field.y, msg.magnetic_field.z = data[6:9]
                msg.header.stamp = rospy.Time.now()
                publish(msg)

                # For debugging purposes, also publish the magnitude of the magnetic field vector.
                publisher_mag_magnitude.publish(sqrt(sum([c**2 for c in data[6:9]])))

                t_last = rospy.get_time()


if __name__ == '__main__':
    ros_publish()
