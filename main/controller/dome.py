import win32com.client
import pythoncom
import time
import threading
import queue
import logging

class Dome(threading.Thread):
    
    def __init__(self, loop_time = 1.0/60):
        self.q = queue.Queue()
        self.timeout = loop_time
        self.running = True
        super(Dome, self).__init__(name='Dome-Th')
        
        self.move_done = threading.Event()
        self.shutter_done = threading.Event()


    def onThread(self, function, *args, **kwargs):
        self.q.put((function, args, kwargs))
        
    def run(self):
        pythoncom.CoInitialize()
        self.Dome = win32com.client.Dispatch("ASCOMDome.Dome")
        self.connect()
        while self.running:
            logging.debug("Dome thread is alive")
            try:
                function, args, kwargs = self.q.get(timeout=self.timeout)
                function(*args, **kwargs)
            except queue.Empty:
                time.sleep(1)
        pythoncom.CoUninitialize()
    
    def stop(self):
        logging.debug("Stopping dome thread")
        self.running = False
        
    def connect(self):
        try: self.Dome.Connected = True
        except: print("ERROR: Could not connect to dome")
        else: print("Dome has successfully connected")
        
    def _is_ready(self):
        while self.Dome.Slewing:
            time.sleep(2)
        if not self.Dome.Slewing:
            return
    
    def Home(self):
        self._is_ready()
        try: self.Dome.FindHome()
        except: print("ERROR: Dome cannot find home")
        else: 
            print("Dome is homing")
            while not self.Dome.AtHome:
                time.sleep(2)
            return
    
    def Park(self):
        self.move_done.clear()
        self._is_ready()
        try: self.Dome.Park()
        except: print("ERROR: Error parking dome")
        else: 
            print("Dome is parking")
            self._is_ready()
            self.move_done.set()
        
    def MoveShutter(self, open_or_close):
        self.shutter_done.clear()
        self._is_ready()
        if open_or_close == 'open':
            self.Dome.OpenShutter()
            print("Shutter is opening")
            while self.Dome.ShutterStatus != 0:
                time.sleep(5)
            self.shutter_done.set()
        elif open_or_close == 'close':
            self.Dome.CloseShutter()
            print("Shutter is closing")
            while self.Dome.ShutterStatus != 1: #Seems like 1 = closed, 0 = open.  Partially opened = open.
                time.sleep(5)
            self.shutter_done.set()
            
        else: print("Invalid shutter move command")
        return
    
    def SlaveDometoScope(self, toggle):
        self.move_done.clear()
        self._is_ready()
        if toggle == True:
            try: self.Dome.Slaved = True
            except: print("ERROR: Cannot slave dome to scope")
            else: 
                print("Dome is slaving to scope")
                self._is_ready()
                self.move_done.set()
        elif toggle == False:
            try: self.Dome.Slaved = False
            except: print("ERROR: Cannot stop slaving dome to scope")
            else: print("Dome is no longer slaving to scope")
        logging.debug('Dome slaving toggled')
        
    def Slew(self, Azimuth):
        self.move_done.clear()
        self._is_ready()
        try: self.Dome.SlewtoAzimuth(Azimuth)
        except: print("ERROR: Error slewing dome")
        else: 
            print("Dome is slewing to {} degrees".format(Azimuth))
            self._is_ready()
            self.move_done.set()
    
    def Abort(self):
        self.Dome.AbortSlew()
        
    def disconnect(self):   #Always close shutter and park before disconnecting
        self._is_ready()
        while self.Dome.ShutterStatus != 1:
            time.sleep(5)
        if self.Dome.AtPark and self.Dome.ShutterStatus == 1:
            try: 
                self.Dome.Connected = False
                return True
            except: 
                print("ERROR: Could not disconnect from dome")
                return False
        else: 
            print("Dome is not parked, or shutter not closed")
            return False