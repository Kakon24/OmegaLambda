import datetime
import pytz
from astropy.time import Time
import time
import os
import re
import copy
import logging
import subprocess
import threading

from ..common.util import time_utils, conversion_utils
from ..common.IO import config_reader
from ..common.datatype import filter_wheel
from ..controller.camera import Camera
from ..controller.telescope import Telescope
from ..controller.dome import Dome
from ..controller.focuser_control import Focuser
from ..controller.focuser_procedures import FocusProcedures
from ..controller.flatfield_lamp import FlatLamp

from ..controller.thread_monitor import Monitor
from ..controller.focuser_gui import Gui
from .calibration import Calibration
from .guider import Guider
from .condition_checker import Conditions


class ObservationRun:
    def __init__(self, observation_request_list, image_directory, shutdown_toggle, calibration_toggle, focus_toggle):
        """
        Initializes the observation run.

        Parameters
        ----------
        observation_request_list : LIST
            List of observation tickets.
        image_directory : LIST
            Directories to which the images will be saved to, matching each observation ticket.
        shutdown_toggle : BOOL
            Whether or not to shut down after finished with observations.
        calibration_toggle : BOOL
            Whether or not to take calibration images at the specified calibration time in the configuration
            file.
        focus_toggle : BOOL
            Whether or not to focus on each target before beginning the observation.

        Returns
        -------
        None.
        """
        # Basic parameters
        self.observation_request_list = observation_request_list
        self.image_directories = {ticket: path for (ticket, path) in zip(observation_request_list, image_directory)}
        self.calibrated_tickets = [0] * len(observation_request_list)
        self.current_ticket = self.observation_request_list[0]
        self.shutdown_toggle = shutdown_toggle
        self.calibration_toggle = calibration_toggle
        self.focus_toggle = focus_toggle
        self.continuous_focus_toggle = True
        self.tz = observation_request_list[0].start_time.tzinfo
        self.time_start = None
        self.plot_lock = threading.Lock()

        # Initializes all relevant hardware
        self.camera = Camera()
        self.telescope = Telescope()
        self.dome = Dome()
        self.focuser = Focuser()
        self.conditions = Conditions(plot_lock=self.plot_lock)
        self.flatlamp = FlatLamp()


        # Initializes higher level structures - focuser, guider, and calibration
        self.focus_procedures = FocusProcedures(self.focuser, self.camera, self.conditions, plot_lock=self.plot_lock)
        self.calibration = Calibration(self.camera, self.flatlamp, self.image_directories)
        self.guider = Guider(self.camera, self.telescope)
        self.gui = Gui(self.focuser, self.focus_procedures, focus_toggle)

        # Initializes config objects
        self.filterwheel_dict = filter_wheel.get_filter().filter_position_dict()
        self.config_dict = config_reader.get_config()

        # Starts the threads
        self.focuser.start()        # Must be started first so that it may check all available COM ports for robofocus
        self.conditions.start()
        self.camera.start()
        self.telescope.start()
        self.dome.start()
        self.focus_procedures.start()
        self.flatlamp.start()
        self.calibration.start()
        self.guider.start()
        self.gui.start()


        self.th_dict = {'camera': self.camera, 'telescope': self.telescope,
                        'dome': self.dome, 'focuser': self.focuser, 'flatlamp': self.flatlamp,
                        'conditions': self.conditions, 'guider': self.guider,
                        'focus_procedures': self.focus_procedures, 'gui': self.gui
                        }
        self.monitor = Monitor(self.th_dict)
        self.monitor.start()

    def everything_ok(self):
        """
        Description
        -----------
        Checks hardware connections and all outside conditions (humidity, wind, rain,
                                                                sun elevation, and cloud coverage)

        Returns
        -------
        bool
            If False, something has gone wrong, and so the observing will have to stop. Otherwise, conditions are
            good to continue observation.

        """
        check = True
        connections = {
            'Camera': self.camera,
            'Telescope': self.telescope,
            'Dome': self.dome,
            'FlatLamp': self.flatlamp
        }
        message = ''
        for key, value in connections.items():
            if not value.live_connection.wait(timeout=10):
                message += key + ' '
                check = False
        if message:
            logging.error('Hardware connection timeout: {}'.format(message))
        if not self.focuser.live_connection.wait(timeout=10):
            self.continuous_focus_toggle = False
            self.focus_toggle = False
            logging.warning('Hardware connection timeout: Focuser.  Will continue observing without focusing.')

        self.threadcheck()

        if self.conditions.weather_alert.isSet():
            calibration = (self.config_dict.calibration_time == "end") and (self.calibration_toggle is True)
            self.guider.stop_guiding()
            self.guider.loop_done.wait(timeout=10)
            time.sleep(5)
            cooler = self.conditions.sun
            self._shutdown_procedure(calibration=calibration, cooler=cooler)
            logging.info("Sleeping for {} minutes, then weather checks will resume to attempt "
                         "a possible re-open.".format(self.config_dict.min_reopen_time))
            time.sleep(self.config_dict.min_reopen_time * 60)

            while self.conditions.weather_alert.isSet():
                if self.conditions.sun:
                    cooler = True
                    self.camera.onThread(self.camera.cooler_set, False)
                    sunset_time = conversion_utils.get_sunset(datetime.datetime.now(self.tz),
                                                              self.config_dict.site_latitude,
                                                              self.config_dict.site_longitude)
                    logging.info('The Sun has risen above the horizon...observing will stop until the Sun sets again '
                                 'at {}.'.format(sunset_time.strftime('%Y-%m-%d %H:%M:%S%z')))
                    current_time = datetime.datetime.now(self.tz)
                    while current_time < sunset_time:
                        self.threadcheck()
                        current_time = datetime.datetime.now(self.tz)
                        if current_time > self.observation_request_list[-1].end_time:
                            return False
                        time.sleep((self.config_dict.weather_freq + 1) * 60)
                    logging.info('The Sun should now be setting again...observing will resume shortly.')

                else:
                    self.threadcheck()
                    logging.info("Still waiting for good conditions to reopen.")
                    current_time = datetime.datetime.now(self.tz)
                    if current_time > self.observation_request_list[-1].end_time:
                        return False
                    time.sleep(self.config_dict.weather_freq * 60)

            if not self.conditions.weather_alert.isSet():
                current_time = datetime.datetime.now(self.tz)
                if current_time + datetime.timedelta(minutes=15) > self.observation_request_list[-1].end_time:
                    return False
                check = True
                self._startup_procedure(cooler=cooler)

                if self.current_ticket.end_time > datetime.datetime.now(self.tz):
                    self._ticket_slew(self.current_ticket)
                    ###  Probably don't need to redo coarse focus after reopening from weather
                    # if self.focus_toggle:
                    #     self.focus_target(self.current_ticket)
                    if self.current_ticket.self_guide:
                        self.guider.onThread(self.guider.guiding_procedure, self.image_directories[self.current_ticket])
            else:
                logging.info('Weather is still too poor to resume observing.')
                self.everything_ok()
        return check

    def _startup_procedure(self, cooler=True):
        """
        Parameters
        ----------
        cooler : BOOL, optional
            Whether or not to turn on the camera's cooler.  The default is True.

        Returns
        -------
        Initial_shutter : INT
            The position of the shutter before observing started.
            0 = open, 1 = closed, 2 = opening, 3 = closing, 4 = error.
            -1 = failed hardware/weather check.

        """
        # Give initial time lag to allow first weather check to complete
        time.sleep(10)
        initial_check = self.everything_ok()
        if cooler:
            self.camera.onThread(self.camera.cooler_set, True)
        self.dome.onThread(self.dome.shutter_position)
        time.sleep(2)
        initial_shutter = self.dome.shutter
        if initial_shutter in (1, 3, 4) and initial_check is True:
            self.dome.onThread(self.dome.move_shutter, 'open')
            self.dome.onThread(self.dome.home)
        elif not initial_check:
            if not self.conditions.weather_alert.isSet():
                self.shutdown()
            return -1
        self.telescope.onThread(self.telescope.unpark)
        self.camera.onThread(self.camera.cooler_ready)
        self.dome.onThread(self.dome.slave_dome_to_scope, True)
        return initial_shutter

    def _ticket_slew(self, ticket):
        """

        Parameters
        ----------
        ticket : ObservationTicket Object
            Created from json_reader and object_reader.

        Returns
        -------
        bool
            True if slew was successful, otherwise False.

        """
        self.telescope.onThread(self.telescope.slew, ticket.ra, ticket.dec)
        self.telescope.slew_done.wait()
        time.sleep(2)
        slew = self.telescope.last_slew_status
        if not slew:
            logging.warning('Telescope cannot slew to target.  Waiting until slew conditions are acceptable.')
            while not slew:
                self.telescope.onThread(self.telescope.park)
                time.sleep(self.config_dict.weather_freq*60)
                if not self.everything_ok():
                    return False
                self.telescope.onThread(self.telescope.slew, ticket.ra, ticket.dec)
                self.telescope.slew_done.wait()
                time.sleep(2)
                slew = self.telescope.last_slew_status
        return True

    def check_start_time(self, ticket):
        """
        Checks the start time of the given ticket and waits if it has not been reached yet.

        Parameters
        ----------
        ticket : ObservationTicket object

        Returns
        -------
        shutdown: bool
            Whether or not the ticket start time caused a shutdown.
        """
        shutdown = False
        current_time = datetime.datetime.now(self.tz)
        if ticket.start_time > current_time:
            logging.info("It is not the start time {} of {} observation, "
                         "waiting till start time.".format(ticket.start_time.isoformat(), ticket.name))
            if ticket != self.observation_request_list[0] and \
                    ((ticket.start_time - current_time) > datetime.timedelta(minutes=3)):
                logging.info("Start time of the next ticket is not immediate.  Shutting down "
                             "observatory in the meantime.")
                self._shutdown_procedure(calibration=False, cooler=False)
                shutdown = True
            current_epoch_milli = time_utils.datetime_to_epoch_milli_converter(current_time)
            start_time_epoch_milli = time_utils.datetime_to_epoch_milli_converter(ticket.start_time)
            time.sleep((start_time_epoch_milli - current_epoch_milli) / 1000)
        return shutdown

    def observe(self):
        """
        Description
        ----------
        Makes sure the dome, shutter, camera are ready to begin observation,
        and the start time has passed before beginning observation.  Then it loops
        through all tickets and starts the necessary procedures.

        Returns
        -------
        None.
        """
        if (self.config_dict.calibration_time == "start") and (self.calibration_toggle is True):
            cooler = False
            self.camera.onThread(self.camera.cooler_set, True)
            self.camera.onThread(self.camera.cooler_ready)
            self.camera.cooler_settle.wait()
            logging.info('Taking darks and flats...')
            self.take_calibration_images(beginning=True)
        else:
            cooler = True
        self.check_start_time(self.observation_request_list[0])
        initial_shutter = self._startup_procedure(cooler=cooler)


        if initial_shutter == -1:
            return

        for ticket in self.observation_request_list:
            self.current_ticket = ticket
            if not self.everything_ok():
                self.shutdown()
                return
            self.crash_check('TheSkyX.exe')
            self.crash_check('ASCOMDome.exe')

            self.tz = ticket.start_time.tzinfo
            shutdown = self.check_start_time(ticket)
            if ticket.end_time < datetime.datetime.now(self.tz):
                logging.info("the end time {} of {} observation has already passed. "
                             "Skipping to next target.".format(ticket.end_time.isoformat(), ticket.name))
                continue
            if not self.everything_ok():
                self.shutdown()
                return
            if shutdown:
                initial_shutter = self._startup_procedure(cooler=False)

            if not self._ticket_slew(ticket):
                self.shutdown()
                return
            if initial_shutter in (1, 3, 4):
                time.sleep(10)
                self.dome.move_done.wait()
                self.dome.shutter_done.wait()
            self.camera.cooler_settle.wait()
            if self.focus_toggle:
                self.focus_target(ticket)

            if not self.everything_ok():
                self.shutdown()
                return

            # if ticket == self.observation_request_list[0]:
            #     input("The program is ready to start taking images of {}.  Please take this time to "
            #           "check the focus and pointing of the target.  When you are ready, press Enter: ".format(
            #         ticket.name))
            self.time_start = time_utils.convert_to_jd_utc()
            (taken, total) = self.run_ticket(ticket)
            logging.info("{} out of {} exposures were taken for {}.  Moving on to next target.".format(taken, total,
                                                                                                       ticket.name))
        calibration = (self.config_dict.calibration_time == "end") and (self.calibration_toggle is True)
        self.shutdown(calibration)

    def focus_target(self, ticket):
        """
        Description
        -----------
        Starts the focus procedures module to focus on the current target.

        Parameters
        ----------
        ticket : ObservationTicket Object
            Created from json_reader and object_reader.

        Returns
        -------
        None.

        """
        self.focus_procedures.focused.clear()
        focus_filter = str(ticket.filter[0]) if type(ticket.filter) is list \
            else ticket.filter if type(ticket.filter) is str else None
        focus_exp = float(ticket.exp_time[0]) if type(ticket.exp_time) is list \
            else ticket.exp_time if type(ticket.exp_time) in (int, float) else None
        if not focus_filter:
            logging.error('Filter argument is wrong type')
            return
        focus_exposure = self.config_dict.focus_exposure_multiplier*focus_exp
        if focus_exposure < 0.001:
            focus_exposure = 0.001
        elif focus_exposure > 30:
            focus_exposure = 30
        self.focus_procedures.onThread(self.focus_procedures.startup_focus_procedure, focus_exposure,
                                       self.filterwheel_dict[focus_filter], self.image_directories[ticket])
        self.focus_procedures.focused.wait()

    def run_ticket(self, ticket):
        """
        Parameters
        ----------
        ticket : ObservationTicket Object
            The observation ticket object with information useful to
            the observing run.

        Returns
        -------
        img_count: INT
            Number of images taken.
        ticket.num: INT
            The total number of images that are specified on the
            observation ticket.
        """
        if self.continuous_focus_toggle:
            self.focus_procedures.onThread(self.focus_procedures.constant_focus_procedure)

        ticket.exp_time = [ticket.exp_time] if type(ticket.exp_time) in (int, float) else ticket.exp_time
        ticket.filter = [ticket.filter] if type(ticket.filter) is str else ticket.filter
        if ticket.self_guide:
            self.guider.onThread(self.guider.guiding_procedure, self.image_directories[ticket])
        header_info = self.get_general_header_info(ticket)
        if ticket.cycle_filter:
            img_count = self.take_images(ticket.name, ticket.num, ticket.exp_time,
                                         ticket.filter, ticket.end_time, self.image_directories[ticket],
                                         True, header_info)
            if self.continuous_focus_toggle:
                self.focus_procedures.stop_constant_focusing()
            if ticket.self_guide:
                self.guider.stop_guiding()
                self.guider.loop_done.wait(timeout=10)
            return img_count, ticket.num

        else:
            img_count = 0
            if len(ticket.exp_time) <= 1:
                ticket.exp_time *= len(ticket.filter)
            for i in range(len(ticket.filter)):
                img_count_filter = self.take_images(ticket.name, ticket.num, [ticket.exp_time[i]],
                                                    [ticket.filter[i]], ticket.end_time, self.image_directories[ticket],
                                                    False, header_info)
                img_count += img_count_filter
            if self.continuous_focus_toggle:
                self.focus_procedures.stop_constant_focusing()
            if ticket.self_guide:
                self.guider.stop_guiding()
                self.guider.loop_done.wait(timeout=10)
            return img_count, ticket.num * len(ticket.filter)

    def take_images(self, name, num, exp_time, _filter, end_time, path, cycle_filter, header_info):
        """
        Parameters
        ----------
        name : STR
            Name of target to be observed.
        num : INT
            Total number of exposures to be taken during the night.
        exp_time : LIST
            The exposure times of each image.
        _filter : LIST, STR
            The filters to be used during the night.
        end_time : datetime.datetime Object
            The end time of the observation session, set
            in the observation ticket.
        path : STR
            The image save path.
        cycle_filter : BOOL
            If True, camera will cycle filter after each exposre,
            if False, camera will cycle filter after num value has been reached.

        Returns
        -------
        i : INT
            The number of images taken for the current ticket.
        """
        num_filters = len(_filter)
        num_exptimes = len(exp_time)
        # num_filters and num_exptimes should always be equal, not sure if we need both
        image_num = 1
        names_list = []
        image_base = {}
        i = 0
        while i < num:
            logging.debug('In take_images loop')
            if end_time <= datetime.datetime.now(self.tz):
                logging.info("The observations end time of {} has passed.  "
                             "Stopping observation of {}.".format(end_time, name))
                break
            if not self.everything_ok():
                break
            current_filter = _filter[i % num_filters]
            current_exp = exp_time[i % num_exptimes]
            image_name = "{0:s}_{1:.3f}s_{2:s}-{3:04d}.fits".format(name, current_exp, str(current_filter).upper(),
                                                                    image_num)

            if i == 0 and os.path.exists(os.path.join(path, image_name)):
                # Checks if images already exist (in the event of a crash)
                for f, exp in zip(_filter, exp_time):
                    names_list = [0]
                    for fname in os.listdir(path):
                        if n := re.search('{0:s}_{1:.3f}s_{2:s}-(.+?).fits'.format(name, exp, str(f).upper()),
                                          fname):
                            names_list.append(int(n.group(1)))
                    image_base[f] = max(names_list) + 1

                image_name = "{0:s}_{1:.3f}s_{2:s}-{3:04d}.fits".format(name, current_exp, str(current_filter).upper(),
                                                                        image_base[current_filter])
            header_info_i = self.add_timed_header_info(header_info, name, current_exp)
            self.camera.onThread(self.camera.expose,
                                 current_exp, self.filterwheel_dict[current_filter],
                                 os.path.join(path, image_name), "light", **header_info_i)
            self.camera.image_done.wait(timeout=int(current_exp)*2 + 60)

            if self.crash_check('MaxIm_DL.exe'):
                continue

            if cycle_filter:
                if names_list:
                    image_num = int(image_base[_filter[(i + 1) % num_filters]] + ((i + 1) / num_filters))
                else:
                    image_num = int(1 + ((i + 1)/num_filters))
            elif not cycle_filter:
                if names_list:
                    image_num = image_base[_filter[(i + 1) % num_filters]] + (i + 1)
                else:
                    image_num += 1
            i += 1
        return i

    def get_general_header_info(self, ticket):
        ra2k, dec2k = ticket.ra, ticket.dec
        ra_ap, dec_ap = conversion_utils.convert_j2000_to_apparent(ra2k, dec2k)
        header_info = {
            'OBJECT': ticket.name,
            'OBSERVER': 'Omegalambda automation code',
            'SITELAT': conversion_utils.sexagesimal(self.config_dict.site_latitude),
            'SITELONG': conversion_utils.sexagesimal(self.config_dict.site_longitude),
            'SITEALT': self.config_dict.site_altitude,
            'JD_SOBS': self.time_start,
            'RA_OBJ': ra_ap,
            'DEC_OBJ': dec_ap,
            'RAOBJ2K': ra2k,
            'DECOBJ2K': dec2k,
        }
        return header_info

    def add_timed_header_info(self, header_info_orig, name, exp_time):
        header_info = copy.deepcopy(header_info_orig)
        # Define for mid-exposure time
        header_info['JD_UTC'] = time_utils.convert_to_jd_utc() + (exp_time/2) / (24*60*60)
        epoch_datetime = Time(header_info['JD_UTC'], format='jd', scale='utc').datetime
        epoch_datetime = pytz.utc.localize(epoch_datetime)
        bjd_tdb = time_utils.convert_to_bjd_tdb(header_info['JD_UTC'], name, self.config_dict.site_latitude,
                                                self.config_dict.site_longitude,
                                                self.config_dict.site_altitude,
                                                header_info['RAOBJ2K'], header_info['DECOBJ2K'])
        if bjd_tdb:
            header_info['BJD_TDB'] = bjd_tdb
        header_info['AZ_OBJ'], header_info['ALT_OBJ'] = conversion_utils.convert_radec_to_altaz(header_info['RAOBJ2K'], header_info['DECOBJ2K'],
                                                          self.config_dict.site_latitude,
                                                          self.config_dict.site_longitude, time=epoch_datetime)
        header_info['ZD_OBJ'] = 90 - header_info['ALT_OBJ']
        header_info['AIRMASS'] = conversion_utils.airmass(header_info['ALT_OBJ'])

        lmst = time_utils.get_local_sidereal_time(self.config_dict.site_longitude, date=epoch_datetime)
        ha = (lmst - header_info['RAOBJ2K']) % 24
        if ha > 12:
            ha -= 24
        header_info['HA_OBJ'] = ha
        return header_info

    def crash_check(self, program):
        """
        Description
        -----------
        Checks to see if any important programs are not responding, and if so,
        restarts them.

        Parameters
        ----------
        program : STR
            Name of the program to check for.

        Returns
        -------
        bool
            True if the program is not responding and needs to be restarted, otherwise
            False.

        """
        prog_dict = {'MaxIm_DL.exe': [self.camera, Camera], 'TheSkyX.exe': [self.telescope, Telescope],
                     'ASCOMDome.exe': [self.dome, Dome]}
        if program not in prog_dict.keys():
            logging.error('Unrecognized program name to perform a crash check for.')
            return False
        cmd = 'tasklist /FI "IMAGENAME eq %s" /FI "STATUS eq running"' % program
        status = subprocess.Popen(cmd, stdout=subprocess.PIPE).stdout.read()
        responding = program in str(status)

        if not responding:
            prog_dict[program][0].crashed.set()
            logging.error('{} is not responding.  Restarting...'.format(program))
            time.sleep(5)
            prog_dict[program][0].crashed.clear()
            subprocess.call('taskkill /f /im {}'.format(program))
            time.sleep(5)
            prog_dict[program][0] = prog_dict[program][1]()
            prog_dict[program][0].start()
            time.sleep(5)
            if program in ('MaxIm_DL.exe', 'TheSkyX.exe') and self.current_ticket.self_guide is True:
                self.guider.stop_guiding()
                self.guider.onThread(self.guider.stop)
                time.sleep(5)
                self.guider = Guider(self.camera, self.telescope)
                self.guider.start()
                time.sleep(5)
                self.guider.onThread(self.guider.guiding_procedure,
                                     self.image_directories[self.current_ticket])
            return True
        else:
            return False

    def take_calibration_images(self, beginning=False):
        """
        Description
        -----------
        Takes flats and darks for the current observation ticket and
        any previous ones.

        Parameters
        ----------
        beginning : BOOL, optional
            True if taking images before observations start, otherwise False. The default is False.
        Returns
        -------
        None.
        """
        for i in range(len(self.observation_request_list)):
            if self.calibrated_tickets[i]:
                continue
            self.calibration.onThread(self.calibration.take_flats, self.observation_request_list[i])
            self.calibration.flats_done.wait()
            self.calibration.onThread(self.calibration.take_darks, self.observation_request_list[i])
            self.calibration.darks_done.wait()
            self.calibrated_tickets[i] = 1
            if self.current_ticket == self.observation_request_list[i] and beginning is False:
                break

    def shutdown(self, calibration=False):
        """
        Description
        -----------
        Decides whether or not to shut down, and whether or not to take calibration images.

        Parameters
        ----------
        calibration : BOOL, optional
            Whether or not to take calibration images. The default is False.

        Returns
        -------
        None.

        """
        if self.shutdown_toggle or self.conditions.weather_alert.isSet():
            self._shutdown_procedure(calibration=calibration)
            time.sleep(1)
            self.stop_threads()
        else:
            return

    def stop_threads(self):
        """
        Description
        -----------
        Stops all of the hardware threads.

        Returns
        -------
        None.

        """
        self.camera.onThread(self.camera.disconnect)
        self.telescope.onThread(self.telescope.disconnect)
        self.dome.onThread(self.dome.disconnect)
        self.focuser.onThread(self.focuser.disconnect)
        self.flatlamp.onThread(self.flatlamp.disconnect)

        self.monitor.run_th_monitor = False                 #Have to stop this first otherwise it will restart everything
        self.conditions.stop.set()
        self.focus_procedures.stop_constant_focusing()      # Should already be stopped, but just in case
        self.guider.stop_guiding()                          # Should already be stopped, but just in case
        self.camera.onThread(self.camera.stop)
        self.telescope.onThread(self.telescope.stop)
        self.dome.onThread(self.dome.stop)
        self.focuser.onThread(self.focuser.stop)
        self.focus_procedures.stop()
        self.guider.stop()
        self.flatlamp.onThread(self.flatlamp.stop)
        self.calibration.onThread(self.calibration.stop)
        logging.debug(' Shutting down thread monitor. Number of thread restarts: {}'.format(self.monitor.n_restarts))
        time.sleep(5)

    def _shutdown_procedure(self, calibration, cooler=True):
        """
        Description
        ----------
        Safely shuts down the telescope, camera, and dome

        Parameters
        ----------
        calibration : BOOL
            Whether or not to take calibration images at the end
        cooler : BOOL, optional
            Whether or not to turn off the cooler at the end of shutdown.  The default is True.

        Returns
        -------
        None.
        """
        logging.info("Shutting down observatory.")
        time.sleep(5)
        self.dome.onThread(self.dome.slave_dome_to_scope, False)
        self.telescope.onThread(self.telescope.park)
        self.dome.onThread(self.dome.park)
        self.dome.onThread(self.dome.move_shutter, 'close')
        time.sleep(2)
        self.telescope.slew_done.wait()
        self.dome.move_done.wait()
        self.dome.shutter_done.wait()
        time.sleep(2)
        self.telescope.onThread(self.telescope.park)      # Backup in case a pulse guide interrupted the last park
        self.telescope.slew_done.wait()
        if calibration:
            logging.info('Taking flats and darks...')
            self.take_calibration_images()
        if cooler:
            self.camera.onThread(self.camera.cooler_set, False)


    def threadcheck(self):
        '''
        Description
        ----------
        Checks to see if self.monitor has raised a crashed thread,
        Restarts the crashed threads if there are any
        
        Returns
        -------
        None
        '''
        threadlist = self.monitor.crashed
        if threadlist and len(threadlist) != 0:
            for thname in threadlist:
                self.restart(thname)
        else:
            logging.debug('All threads OK')

    def restart(self, thname):
        '''
        Description
        -----------
        Redefines and then restarts the inputted thread
        
        Parmeters
        --------
        thname : Handle
            Handle of the original thread to restart
        '''
        logging.error('Restarting thread {}'.format(thname))
        if thname == 'camera':
            self.camera = Camera()
            self.camera.start()
            self.monitor.n_restarts['camera'] += 1
        elif thname == 'telescope':
            self.telescope = Telescope()
            self.telescope.start()
            self.monitor.n_restarts['telescope'] += 1
        elif thname == 'dome':
            self.dome = Dome()
            self.dome.start()
            self.monitor.n_restarts['dome'] += 1
        elif thname == 'flatlamp':
            self.flatlamp = FlatLamp()
            self.flatlamp.start()
            self.monitor.n_restarts['flatlamp'] += 1
        elif thname == 'conditions':
            self.conditions = Conditions()
            self.conditions.start()
            self.monitor.n_restarts['conditions'] += 1
        elif thname == 'guider':
            self.guider = Guider(self.camera, self.telescope)
            self.guider.start()
            self.monitor.n_restarts['guider'] += 1
            if self.current_ticket:
                if self.current_ticket.self_guide:
                    self.guider.onThread(self.guider.guiding_procedure, self.image_directories[self.current_ticket])
        elif thname == 'focus_procedures':
            self.focus_procedures = FocusProcedures(self.focuser, self.camera, self.conditions)
            self.focus_procedures.start()
            self.monitor.n_restarts['focus_procedures'] += 1
            if self.current_ticket:
                if self.focus_toggle and not self.focus_procedures.focused:
                    self.focus_target(self.current_ticket)
                if self.continuous_focus_toggle:
                    self.focus_procedures.onThread(self.focus_procedures.constant_focus_procedure)
        elif thname == 'gui':
            self.gui = Gui(self.focuser, self.focus_procedures, self.focus_toggle)
            self.gui.start()
            self.monitor.n_restarts['gui'] += 1
        self.monitor.crashed.remove(thname)
        logging.error('crashed list {}'.format(self.monitor.crashed))