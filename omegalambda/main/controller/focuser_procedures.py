# Focusing procedures
import os
import logging
import time
import threading
import numpy as np
import datetime
from scipy.optimize import curve_fit
import matplotlib.pyplot as plt

from .hardware import Hardware
from ..common.IO import config_reader
from ..common.util import filereader_utils

np.warnings.filterwarnings('ignore')


def standard_parabola(x, a, b, c):
    """
    A standard parabola function for scipy.optimize to fit.

    Returns
    -------
    FLOAT:
        a + bx + cx^2
    """
    return a + b*x + c*x**2


class FocusProcedures(Hardware):

    def __init__(self, focus_obj, camera_obj, conditions_obj, plot_lock=None):
        """
        Initializes focusprocedures as a subclass of hardware.

        Parameters
        ----------
        focus_obj : CLASS INSTANCE OBJECT of Focuser
            From custom focuser class.
        camera_obj : CLASS INSTANCE OBJECT of Camera
            From custom camera class.
        conditions_obj : CLASS INSTANCE OBJECT of Conditions
            From custom conditions class.
        plot_lock : threading.Lock
            Thread lock so as not to attempt multiple matplotlib plots at once.

        Returns
        -------
        None.

        """
        self.focuser = focus_obj
        self.camera = camera_obj
        self.conditions = conditions_obj
        self.config_dict = config_reader.get_config()
        self.plot_lock = plot_lock
        self.position_previous = None
        self.temp_previous = None
       
        self.focused = threading.Event()
        self.continuous_focusing = threading.Event()
        super(FocusProcedures, self).__init__(name='FocusProcedures')

    def _class_connect(self):
        """
        Description
        -----------
        Overwrites base not implemented method.  However, nothing is necessary for the guider specifically,
        so the method just passes.

        Returns
        -------
        True : BOOL
        """
        return True

    def get_temperature(self):
        """
        Returns
        -------
        FLOAT or INT : The temperature value as read by the focuser class.
        """
        self.focuser.onThread(self.focuser.get_temperature)
        self.focuser.adjusting.wait()
        time.sleep(1)
        return self.focuser.temperature

    def startup_focus_procedure(self, exp_time, _filter, image_path):
        """
        Description
        -----------
        Automated focusing procedure to be used before taking any science images.  Uses the
        camera to take test exposures and measures the FWHM of the images.

        Parameters
        ----------
        exp_time : FLOAT or INT
            Length of camera exposures in seconds.
        _filter : STR
            Filter to take camera exposures in.
        image_path : STR
            File path to the CCD images to be used for focusing.

        Returns
        -------
        None.

        """
        self.focused.clear()
        
        if not os.path.exists(os.path.join(image_path, r'focuser_images')):
            os.mkdir(os.path.join(image_path, r'focuser_images'))
        # Creates new sub-directory for focuser images
        self.focuser.onThread(self.focuser.current_position)
        self.focuser.adjusting.wait()
        time.sleep(2)
        initial_position = self.focuser.position
        fwhm_values = []
        focus_positions = []
        peaks = []
        i = 0
        errors = 0
        crash_loops = 0
        while i < self.config_dict.focus_iterations:
            if self.camera.crashed.isSet() or self.focuser.crashed.isSet():
                if crash_loops <= 4:
                    logging.warning('The camera or focuser has crashed...waiting for potential recovery.')
                    time.sleep(10)
                    crash_loops += 1
                    continue
                elif crash_loops > 4:
                    logging.error('The camera or focuser has still not recovered from crashing...focus procedures '
                                  'cannot continue.')
                    break
            image_name = '{0:s}_{1:.3f}s-{2:04d}.fits'.format('FocuserImage', exp_time, i + 1)
            path = os.path.join(image_path, r'focuser_images', image_name)
            self.camera.onThread(self.camera.expose, exp_time, _filter, save_path=path, type="light")
            self.camera.image_done.wait()
            time.sleep(2)
            self.focuser.onThread(self.focuser.current_position)
            self.camera.onThread(self.camera.get_fwhm)
            time.sleep(2)
            current_position = self.focuser.position
            fwhm_test, peak, saturated = filereader_utils.radial_average(path, self.config_dict.saturation)
            fwhm = self.camera.fwhm if self.camera.fwhm and not saturated else fwhm_test
            if abs(current_position - initial_position) >= self.config_dict.focus_max_distance:
                logging.error('Focuser has stepped too far away from initial position and could not find a focus.')
                break
            if not fwhm:
                logging.warning('No fwhm could be calculated...trying again')
                errors += 1
                if errors < 3:
                    continue
                else:
                    logging.critical('Cannot focus on target')
                    break
            errors = 0      # This way it must be 3 in a row
            if i < self.config_dict.focus_iterations // 2:
                self.focuser.onThread(self.focuser.move_in, self.config_dict.initial_focus_delta)
                self.focuser.adjusting.wait(timeout=10)
            elif i == self.config_dict.focus_iterations // 2:
                self.focuser.onThread(self.focuser.absolute_move,
                                      int(initial_position + self.config_dict.initial_focus_delta))
                time.sleep(5)
                self.focuser.adjusting.wait(timeout=30)
            elif i > self.config_dict.focus_iterations // 2:
                self.focuser.onThread(self.focuser.move_out, self.config_dict.initial_focus_delta)
                self.focuser.adjusting.wait(timeout=10)
            logging.debug('Found fwhm = {} for the last image'.format(fwhm))
            fwhm_values.append(fwhm)
            focus_positions.append(current_position)
            peaks.append(peak)
            i += 1
        
        fit_status, minfocus = self.plot_focus_model(fwhm_values, focus_positions, peaks)
        if minfocus:
            if abs(initial_position - minfocus) <= self.config_dict.focus_max_distance:
                logging.info('The focuser found a minimum focus at {}'.format(int(minfocus)))
                self.focuser.adjusting.wait(timeout=10)
                self.focuser.onThread(self.focuser.absolute_move, int(minfocus))
                self.focuser.adjusting.wait(timeout=30)
            else:
                fit_status = False
        if not fit_status:
            logging.error('The focuser could not find a minimum focus.  Resetting to initial position.')
            self.focuser.adjusting.wait(timeout=10)
            self.focuser.onThread(self.focuser.absolute_move, initial_position)
            self.focuser.adjusting.wait(timeout=30)

        self.focused.set()
        self.focuser.onThread(self.focuser.current_position)
        time.sleep(2)
        self.temp_previous = self.conditions.temperature
        self.position_previous = self.focuser.position
        return

    def plot_focus_model(self, fwhm_values, position_values, peak_values):
        data = sorted(zip(position_values, fwhm_values, peak_values))
        # fwhm_deltas = np.diff(data[1], n=1)
        # peak_deltas = np.diff(data[2], n=1)
        # x = []
        # y = []
        # for i in range(len(fwhm_deltas)):
        #     if 0.2*data[2][i] < abs(peak_deltas[i]) < 3*data[2][i] and \
        #             (peak_deltas[i] < 0 and fwhm_deltas[i] < 0) or (peak_deltas[i] > 0 and fwhm_deltas[i] > 0):
        #         continue
        #     else:
        #         if i == 0:
        #             x.append(data[0][i])
        #             y.append(data[1][i])
        #         x.append(data[0][i+1])
        #         y.append(data[1][i+1])
        x = [_[0] for _ in data]
        y = [_[1] for _ in data]
        logging.debug('Position Data: {}'.format(x))
        logging.debug('FWHM Data: {}'.format(y))
        logging.debug('Peak Data: {}'.format(peak_values))
        minfocus = None
        if fit_status := (len(x) >= 3 and len(y) >= 3):
            med = np.median(x)
            fit, _ = curve_fit(standard_parabola, x, y, p0=[5e-04, -7, 2e+04],
                               bounds=([-np.inf, -np.inf, 1e-5], [np.inf, np.inf, np.inf]))
            xfit = np.linspace(med - 75, med + 75, 126)
            yfit = fit[2] * (xfit ** 2) + fit[1] * xfit + fit[0]
            if not isinstance(self.plot_lock, type(None)):
                self.plot_lock.acquire()
            else:
                logging.warning('No thread lock is being utilized for plot drawing: plots may draw incorrectly!')
            fig, ax = plt.subplots()
            ax.plot(x, y, 'bo', label='Raw data')
            ax.plot(xfit, yfit, 'r-', label='Parabolic fit')
            ax.legend()
            ax.set_xlabel('Focus Positions (units)')
            ax.set_ylabel('FWHM value (pixels)')
            ax.set_title('Focus Positions Graph')
            ax.grid()
            current_path = os.path.abspath(os.path.dirname(__file__))
            target_path = os.path.abspath(os.path.join(current_path, r'../../test/FocusPlot_{}.png'.format(
                datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))))
            target_path_2 = os.path.abspath(os.path.join(current_path, r'../../test/FocusData_{}.txt'.format(
                datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))))
            plt.savefig(target_path)
            if not isinstance(self.plot_lock, type(None)):
                self.plot_lock.release()
            d = np.array([[xi, yi] for xi, yi in zip(x, y)])
            np.savetxt(target_path_2, d, delimiter=',', header='Position [steps], FWHM [px]', fmt=('%d', '%.5f'))

            minindex = np.where(yfit == min(yfit))[0][0]
            if np.any(np.isin(minindex, [np.where(yfit == yfit[0]), np.where(yfit == yfit[-1])])):
                fit_status = False
            else:
                minfocus = round(xfit[minindex])
                logging.info('The theoretical minimum focus was calculated to be at position {}'.format(minfocus))

        return fit_status, minfocus
    
    def constant_focus_procedure(self):
        """
        Description
        -----------
        Automated focusing procedure to be used while taking science images.

        Returns
        -------
        None.

        """
        # Will be constantly running in the background
        # Current focus position = initial focus position + 2 steps/degF * (Tcurrent - Tinitial)
        # Will check & adjust once every 30 minutes (adjustable)
        self.continuous_focusing.set()
        while self.continuous_focusing.isSet() and (self.camera.crashed.isSet() is False
                                                    and self.focuser.crashed.isSet() is False):
            time.sleep(self.config_dict.focus_adjust_frequency * 60)
            logging.debug('Continuous focusing procedure is alive...')
            temp_current = self.conditions.temperature
            if temp_current is None:
                continue
            if self.position_previous is None:
                self.focuser.onThread(self.focuser.current_position)
                time.sleep(2)
                self.position_previous = self.focuser.position
                continue
            if self.temp_previous is None or (temp_current - self.temp_previous > 10):
                self.temp_previous = temp_current
                continue
            new_position = self.position_previous + \
                self.config_dict.focus_temperature_constant * (temp_current - self.temp_previous)
            pos_diff = int(new_position - self.position_previous)
            func = self.focuser.move_in if pos_diff < 0 else self.focuser.move_out if pos_diff > 0 else None
            if not func:
                self.temp_previous = temp_current
                continue
            self.focuser.onThread(func, abs(pos_diff))
            self.focuser.adjusting.wait(timeout=15)
            self.temp_previous = temp_current
            self.position_previous = new_position

    @staticmethod
    def get_newest_image(image_path):
        """

        Parameters
        ----------
        image_path : STR
            File path to the images being saved by the camera.

        Returns
        -------
        newest_image : STR
            Full path to the most recently created image file in the given directory.
        """
        images = os.listdir(image_path)
        paths = [full_path for fname in images if os.path.isfile(full_path := os.path.join(image_path, fname))]
        newest_image = max(paths, key=os.path.getctime)
        return newest_image

    def stop_constant_focusing(self):
        """
        Description
        -----------
        Stops the continuous focusing procedure that is used while taking images.
        Must NOT be called with onThread, otherwise the focuser will be stuck on constant focusing on won't ever get
        to execute stop.

        Returns
        -------
        None.

        """
        logging.debug('Stopping continuous focusing')
        self.continuous_focusing.clear()
