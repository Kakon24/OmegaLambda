import datetime
import time
import os
import math
import re
import logging
import subprocess
# import threading

from ..common.util import time_utils, conversion_utils
from ..common.IO import config_reader
from ..common.datatype import filter_wheel
from ..controller.camera import Camera
from ..controller.telescope import Telescope
from ..controller.dome import Dome
from ..controller.focuser_control import Focuser
from ..controller.focuser_procedures import FocusProcedures
#from .guider import Guider
from .weather_checker import Weather
    
class ObservationRun():
    def __init__(self, observation_request_list, image_directory, shutdown_toggle):
        '''

        :param observation_request_list: List of ObservationTickets
        '''
        self.image_directory = image_directory
        self.observation_request_list = observation_request_list
        self.current_ticket = None
        self.shutdown_toggle = shutdown_toggle
        self.tz = observation_request_list[0].start_time.tzinfo
        self.camera = Camera()
        self.telescope = Telescope()
        self.dome = Dome()
        self.weather = Weather()
        self.focuser = Focuser()
        self.focus_procedures = FocusProcedures(self.focuser, self.camera)
        #self.guider = Guider(self.camera, self.telescope)
        
        self.filterwheel_dict = filter_wheel.get_filter().filter_position_dict()
        self.config_dict = config_reader.get_config()
        
        self.weather.start()
        self.camera.start()
        self.telescope.start()
        self.dome.start()
        self.focuser.start()
        self.focus_procedures.start()
        
    def everything_ok(self):
        if not self.camera.live_connection.wait(timeout = 10):
            check = False
            logging.error('Camera connection timeout')
        elif not self.telescope.live_connection.wait(timeout = 10):
            check = False
            logging.error('Telescope connection timeout')
        elif not self.dome.live_connection.wait(timeout = 10):
            check = False
            logging.error('Dome connection timeout')
        elif not self.focuser.live_connection.wait(timeout = 10):
            check = False
            logging.error('Focuser connection timeout')
        elif self.weather.weather_alert.isSet():
            check = False
            # Same situation for weather check -- make it resume once the weather improves if possible
        elif conversion_utils.get_sun_elevation(datetime.datetime.now(self.tz), self.config_dict.site_latitude, self.config_dict.site_longitude) >= 0:
            sunset_time = conversion_utils.get_sunset(datetime.datetime.now(self.tz), self.config_dict.site_latitude, self.config_dict.site_longitude)
            sunset_time = datetime.datetime.now(datetime.timezone(-datetime.timedelta(hours=4))) + datetime.timedelta(minutes=2)
            logging.info('The Sun has risen above the horizon...observing will stop until the Sun sets again at {}.'.format(sunset_time.strftime('%Y-%m-%d %H:%M:%S%z')))
            self._shutdown_procedure()
            sunset_epoch_milli = time_utils.datetime_to_epoch_milli_converter(sunset_time)
            current_epoch_milli = time_utils.datetime_to_epoch_milli_converter(datetime.datetime.now(self.tz))
            time.sleep((sunset_epoch_milli - current_epoch_milli)/1000)
            logging.info('The Sun should now be setting again...observing will resume shortly.')
            if not self.weather.weather_alert.isSet():
                check = True
                if not self.current_ticket:
                    self.observe()
                else:
                    self._startup_procedure()
                    self._ticket_slew(self.current_ticket)
                    self.focus_target(self.current_ticket)
            else: 
                print('Weather is still too poor to resume observing.')
                check = False
        else:
            check = True
        return check

    def _startup_procedure(self):
        Initial_check = self.everything_ok()
        
        self.camera.onThread(self.camera.coolerSet, True)
        self.dome.onThread(self.dome.ShutterPosition)
        time.sleep(2)
        Initial_shutter = self.dome.shutter
        if Initial_shutter in (1,3,4) and Initial_check == True:
            self.dome.onThread(self.dome.MoveShutter, 'open')
            self.dome.onThread(self.dome.Home)
            self.telescope.onThread(self.telescope.Unpark)
        elif not Initial_check:
            self.shutdown(); return
        self.camera.onThread(self.camera.cooler_ready)
        self.dome.onThread(self.dome.SlaveDometoScope, True)
        return Initial_shutter
    
    def _ticket_slew(self, ticket):
        self.telescope.onThread(self.telescope.Slew, ticket.ra, ticket.dec)
        slew = self.telescope.slew_done.wait(timeout = 60)
        if not slew:
            logging.error('Telescope slew has failed.  Retrying...')
            self.telescope.onThread(self.telescope.Slew, ticket.ra, ticket.dec)
            slew2 = self.telescope.slew_done.wait(timeout = 60)
            if not slew2:
                logging.critical('Telescope still cannot slew to target.  Cannot continue observing.')
                return False
        return True

    def observe(self):
        Initial_shutter = self._startup_procedure()
        
        for ticket in self.observation_request_list:
            self.current_ticket = ticket
            if not self.everything_ok(): 
                self.shutdown(); return
            if not self._ticket_slew(ticket):
                return
            if Initial_shutter in (1,3,4):
                self.dome.move_done.wait()
                self.dome.shutter_done.wait()
            self.tz = ticket.start_time.tzinfo
            current_time = datetime.datetime.now(self.tz)
            if ticket.start_time > current_time:
                print("It is not the start time {} of {} observation, "
                      "waiting till start time.".format(ticket.start_time.isoformat(), ticket.name))
                current_epoch_milli = time_utils.datetime_to_epoch_milli_converter(current_time)
                start_time_epoch_milli = time_utils.datetime_to_epoch_milli_converter(ticket.start_time)
                time.sleep((start_time_epoch_milli - current_epoch_milli)/1000)
            
            self.camera.cooler_settle.wait()
            if not self.everything_ok(): 
                self.shutdown(); return
            FWHM = self.focus_target(ticket)
            input("The program is ready to start taking images of {}.  Please take this time to "
                  "check the focus and pointing of the target.  When you are ready, press Enter: ".format(ticket.name))
            (taken, total) = self.run_ticket(ticket, FWHM)
            print("{} out of {} exposures were taken for {}.  Moving on to next target.".format(taken, total, ticket.name))
        self.shutdown()
        
    def focus_target(self, ticket):
        if type(ticket.filter) is list:
            focus_filter = [ticket.filter[0]]
        elif type(ticket.filter) is str:
            focus_filter = ticket.filter
        focus_exposure = int(self.config_dict.focus_exposure_multiplier*ticket.exp_time)
        if focus_exposure <= 0: 
            focus_exposure = 1
        FWHM = self.focus_procedures.onThread(self.focus_procedures.StartupFocusProcedure, focus_exposure, self.filterwheel_dict[focus_filter], 
                                              self.image_directory)
        self.focus_procedures.focused.wait()
        return FWHM
        
    def run_ticket(self, ticket, FWHM):
        self.focus_procedures.onThread(self.focus_procedures.ConstantFocusProcedure, FWHM)
        
        if ticket.cycle_filter:
            img_count = self.take_images(ticket.name, ticket.num, ticket.exp_time,
                                         ticket.filter, ticket.end_time, self.image_directory,
                                         True)
            self.focus_procedures.onThread(self.focus_procedures.StopConstantFocusing)
            return (img_count, ticket.num)
        
        else:
            img_count = 0
            for i in range(len(ticket.filter)):
                img_count_filter = self.take_images(ticket.name, ticket.num, ticket.exp_time,
                                             [ticket.filter[i]], ticket.end_time, self.image_directory,
                                             False)
                img_count += img_count_filter
            self.focus_procedures.onThread(self.focus_procedures.StopConstantFocusing)
            return (img_count, ticket.num*len(ticket.filter))

    def take_images(self, name, num, exp_time, filter, end_time, path, cycle_filter):
        num_filters = len(filter)
        image_num = 1
        N = []
        image_base = {}
        i = 0
        while i < num:
            logging.debug('In take_images loop')
            if end_time <= datetime.datetime.now(self.tz):
                print("The observations end time of {} has passed.  "
                      "Stopping observation of {}.".format(end_time, name))
                break
            if not self.everything_ok(): break
            current_filter = filter[i % num_filters]
            image_name = "{0:s}_{1:d}s_{2:s}-{3:04d}.fits".format(name, exp_time, current_filter, image_num)
            
            if i == 0 and os.path.exists(os.path.join(path, image_name)):   #Checks if images already exist (in the event of a crash)
                for f in filter:
                    N = [0]    
                    for fname in os.listdir(path):
                        n = re.search('{0:s}_{1:d}s_{2:s}-(.+?).fits'.format(name, exp_time, f), fname)
                        if n: N.append(int(n.group(1)))
                    image_base[f] = max(N) + 1
                
                image_name = "{0:s}_{1:d}s_{2:s}-{3:04d}.fits".format(name, exp_time, current_filter, image_base[current_filter])
                
            self.camera.onThread(self.camera.expose, 
                                 int(exp_time), self.filterwheel_dict[current_filter], os.path.join(path, image_name), "light")
            self.camera.image_done.wait(timeout = exp_time*2 + 60)
            
            name = 'MaxIm_DL.exe'
            cmd = 'tasklist /FI "IMAGENAME eq %s" /FI "STATUS eq running"' % name
            status = subprocess.Popen(cmd, stdout=subprocess.PIPE).stdout.read()
            responding = name in str(status)
            
            if not responding:
                self.camera.crashed.set()
                logging.error('MaxIm DL is not responding.  Restarting...')
                time.sleep(5)
                self.camera.crashed.clear()
                subprocess.call('taskkill /f /im MaxIm_DL.exe')                                               #TODO: Maybe add check if os = windows?
                time.sleep(5)
                self.camera = Camera()
                self.camera.start()
                time.sleep(5)
                continue
                
            # Guider here
            
            if cycle_filter:
                if N:
                    image_num = math.floor(image_base[filter[(i + 1) % num_filters]] + ((i + 1)/num_filters))
                else:
                    image_num = math.floor(1 + ((i + 1)/num_filters))
            elif not cycle_filter:
                if N:
                    image_num = image_base[filter[(i + 1) % num_filters]] + (i + 1)
                else:
                    image_num += 1
            i += 1
        return i
    
    def shutdown(self):
        if self.shutdown_toggle:
            self._shutdown_procedure()
            self.stop_threads()
        else:
            pass
        
    def stop_threads(self):
        self.camera.onThread(self.camera.disconnect)
        self.telescope.onThread(self.telescope.disconnect)
        self.dome.onThread(self.dome.disconnect)
        self.focuser.onThread(self.focuser.disconnect)
        
        self.weather.stop.set()
        self.camera.onThread(self.camera.stop)
        self.telescope.onThread(self.telescope.stop)
        self.dome.onThread(self.dome.stop)
        self.focuser.onThread(self.focuser.stop)
        self.focus_procedures.onThread(self.focus_procedures.stop)
    
    def _shutdown_procedure(self):
        print("Shutting down observatory.")
        self.dome.onThread(self.dome.SlaveDometoScope, False)
        self.telescope.onThread(self.telescope.Park)
        self.dome.onThread(self.dome.Park)
        self.dome.onThread(self.dome.MoveShutter, 'close')
        self.camera.onThread(self.camera.coolerSet, False)
        
        self.telescope.slew_done.wait()
        self.dome.move_done.wait()
        self.dome.shutter_done.wait()