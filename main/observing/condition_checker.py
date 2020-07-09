#Condition Checker

import urllib.request
import requests
import os
import re
import time
import threading
import logging
import datetime
import numpy as np

from PIL import Image

from ..common.util import time_utils, conversion_utils
from ..common.IO import config_reader

class Conditions(threading.Thread):
    
    def __init__(self):
        '''
        Description
        -----------
        Subclassed from threading.Thread.  Weather periodically checks the weather conditions while observing.

        Returns
        -------
        None.

        '''
        super(Conditions, self).__init__(name='Conditions-Th')                    # Calls threading.Thread.__init__ with the name 'Conditions-Th'
        self.weather_alert = threading.Event() 
        self.stop = threading.Event()                             # Threading events to set flags and interact between threads
        self.config_dict = config_reader.get_config()                       # Global config dictionary
        self.weather_url = 'http://weather.cos.gmu.edu/Current_Monitor.htm'                                                                     #GMU COS Website for humitiy and wind
        self.rain_url = 'https://weather.com/weather/radar/interactive/l/b63f24c17cc4e2d086c987ce32b2927ba388be79872113643d2ef82b2b13e813'      #Weather.com radar for rain
        self.sun = False
        
    def run(self):
        '''
        Description
        -----------
        Calls self.weather_check and self.rain_check once every 15 minutes.  If conditions are clear, does nothing.
        If conditions are bad, stops observation_run and shuts down the observatory.

        Returns
        -------
        None.

        '''
        Last_Rain = None
        if not self.check_internet():
            logging.error("Your internet connection requires attention.")
            return
        while not self.stop.isSet():
            (H, W, R) = self.weather_check()
            Radar = self.rain_check()
            Sun_elevation = conversion_utils.get_sun_elevation(datetime.datetime.now(datetime.timezone.utc), self.config_dict.site_latitude, self.config_dict.site_longitude)
            Cloud_cover = self.cloud_check()
            if (H >= self.config_dict.humidity_limit) or (W >= self.config_dict.wind_limit) or (Last_Rain != R and Last_Rain != None) or (Radar == True) or (Sun_elevation >= 0) or (Cloud_cover == True):
                self.weather_alert.set()
                if Sun_elevation >= 0:
                    self.sun = True
                else:
                    self.sun = False
                logging.critical("Weather conditions have become too poor for continued observing, or the Sun is rising.")
            else:
                logging.debug("Condition checker is alive: Last check false")
                Last_Rain = R
                self.weather_alert.clear()
            self.stop.wait(timeout = self.config_dict.weather_freq*60)
                
    def check_internet(self):
        '''
        
        Returns
        -------
        BOOL
            True if Internet connection is verified, False otherwise.

        '''
        try:
            urllib.request.urlopen('http://google.com')
            return True
        except:
            return False
   
    def weather_check(self):
        '''

        Returns
        -------
        Humidity : FLOAT
            Current humitiy (%) at Research Hall, from GMU COS weather station.
        Wind : FLOAT
            Current wind speeds in mph at Research Hall, from GMU COS weather station.
        Rain : FLOAT
            Current total rain in in. at Research Hall, from GMU COS weather station.

        '''
        self.weather = urllib.request.urlopen(self.weather_url)
        header = requests.head(self.weather_url).headers
        if 'Last-Modified' in header:
            Update_time = time_utils.convert_to_datetime_UTC(header['Last-Modified'])
            Diff = datetime.datetime.now(datetime.timezone.utc) - Update_time
            if Diff > datetime.timedelta(minutes=30):                                                   # Checking when the web page was last modified (may be outdated)
                logging.warning("GMU COS Weather Station Web site has not updated in the last 30 minutes!")
                #Implement backup weather station
        else: 
            logging.warning("GMU COS Weather Station Web site did not return a last modified timestamp--it may be outdated!")
            #Implement backup weather station
        with open(os.path.join(self.config_dict.home_directory, r'resources\weather_status\weather.txt'),'w') as file:  # Writes the html code to a text file
            for line in self.weather:
                file.write(str(line)+'\n')
                
        with open(os.path.join(self.config_dict.home_directory, r'resources\weather_status\weather.txt'), 'r') as file:     # Reads the text file to find humidity, wind, rain
            text = file.read()
            conditions = re.findall(r'<font color="#3366FF">(.+?)</font>', text)
            Humidity = float(conditions[1].replace('%',''))
            Wind = float(re.search('[+-]?\d+\.\d+', conditions[3]).group())
            Rain = float(re.search('[+-]?\d+\.\d+', conditions[5]).group())
            
            return (Humidity, Wind, Rain)
        
    def rain_check(self):
        '''

        Returns
        -------
        BOOL
            True if there is rain nearby, False otherwise.

        '''
        s = requests.Session()
        self.radar = s.get(self.rain_url, headers={'User-Agent': 'Mozilla/5.0'})
        with open(os.path.join(self.config_dict.home_directory, r'resources\weather_status\radar.txt'),'w') as file:    # Writes weather.com html to a text file
            file.write(str(self.radar.text))
            
        epoch_sec = time_utils.datetime_to_epoch_milli_converter(datetime.datetime.utcnow()) / 1000
        esec_round = time_utils.rounddown_300(epoch_sec)
        # Website radar images only update every 300 seconds
        if abs(epoch_sec - esec_round) < 10:
            time.sleep(10 - abs(epoch_sec - esec_round))
        
        with open(os.path.join(self.config_dict.home_directory, r'resources\weather_status\radar.txt'), 'r') as file:
            html = file.read()
            apiKey = re.search(r'"SUN_V3_API_KEY":"(.+?)",', html).group(1)             # Api key needed to access images, found from html
        
        coords = {0: '291:391:10', 1: '291:392:10', 2: '292:391:10', 3: '292:392:10'}   # Radar map coordinates found by looking through html
        rain = []
        for key in coords:
            url = ( 'https://api.weather.com/v3/TileServer/tile?product=twcRadarMosaic' + '&ts={}'.format(str(esec_round)) 
                   + '&xyz={}'.format(coords[key]) + '&apiKey={}'.format(apiKey) )      # Constructs url of 4 nearest radar images
            
            with open(os.path.join(self.config_dict.home_directory, r'resources\weather_status\radar-img{0:04d}.png'.format(key + 1)), 'wb') as file:
                req = s.get(url, headers={'User-Agent': 'Mozilla/5.0'})
                file.write(req.content)                                                 # Writes 4 images to local png files
            
            img = Image.open(os.path.join(self.config_dict.home_directory, r'resources\weather_status\radar-img{0:04d}.png'.format(key + 1)))
            px = img.size[0]*img.size[1]
            colors = img.getcolors()
            if len(colors) > 1:     # Checks for any colors (green to red for rain) in the images
                percent_colored = 1 - colors[-1][0] / px
                if percent_colored >= 0.1:
                    return True
                else:
                    rain.append(1)
            else:
                continue
            img.close()
        if sum(rain) >= 2:
            return True
        else:
            return False
        
    def cloud_check(self):
        satellite = 'goes-16'
        day = int(time_utils.days_of_year())
        conus_band = 13
        time = datetime.datetime.now(datetime.timezone.utc)
        year = time.year
        time_round = time_utils.rounddown_300(time.hour*60*60 + time.minute*60 + time.second)
        
        s = requests.Session()
        for i in range(6):
            hour = int(time_round/(60*60))
            minute = int((time_round - hour*60*60)/60) - i
            time = '{0:02d}{1:02d}'.format(hour, minute)
            if (minute - 1) % 5 != 0:
                continue
            url = 'https://www.ssec.wisc.edu/data/geo/images/goes-16/animation_images/{}_{}{}_{}_{}_conus.gif'.format(satellite, year, day, time, conus_band)
            req = s.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        
        with open(os.path.join(self.config_dict.home_directory, r'resources\weather_status\cloud-img.gif'), 'wb') as file:
            file.write(req.content)
        
        if os.stat(os.path.join(self.config_dict.home_directory, r'resources\weather_status\cloud-img.gif')).st_size <= 2000:
            logging.error('Cloud coverage image cannot be retrieved')
            return False
        
        img = Image.open(os.path.join(self.config_dict.home_directory, r'resources/weather_status/cloud-img.gif'))
        img_array = np.array(img)
        img_array = img_array.astype('float64')
        #fairfax coordinates ~300, 1350
        img_internal = img_array[270:370, 1310:1410]
        img_small = Image.fromarray(img_internal)
        px = img_small.size[0]*img_small.size[1]
        colors = img_small.getcolors()
        clouds = [color for color in colors if color[1] > 30]
        percent_cover = sum([cloud[0] for cloud in clouds]) / px * 100
        img.close()
        img_small.close()
        print(percent_cover)
        if percent_cover >= self.config_dict.cloud_cover_limit:
            return True
        else:
            return False

        
            