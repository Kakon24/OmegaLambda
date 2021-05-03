<h1>Welcome to -OmegaLambda</h1>
This is the complete code for automating the
campus telescope at the George Mason University Observatory.
<br>
<br>
<h2>I. Installation</h2>
To install, simply download the repository 
into any directory you'd like, and make sure that you have all
of the requirements from the requirements.txt file installed
as well.  Python >= 3.8 is required.  The code has been optimized
for a Windows environment and there has been no testing done on other OSs.
<br>
<br>
You can also use:
<br>

`git clone https://github.com/Kakon24/omegalambda`

Also make sure you install the module by running `pip install .` from your `omegalambda` directory.
This will allow you to import it from anywhere and run the CLI from anywhere.  We currently don't have any unit tests to run (possibly a future goal), since the scale of the project is relatively small 
and easy to manage, but you are free to inspect the code to see its inner workings.  The weather module can also be run independently since
it does not depend on any hardware connections.

Please note that since the code requires Python >= 3.8, you may wish to make a separate environment for
this module, whether that be a conda environment or a Python virtual environment.

<h2>II. Modules</h2>
<h3>A. Config</h3>

The `config` module contains basic configuration files for the code in the `.json` format.  Each
configuration parameter is explained in the docstring for said parameter's software object, and also later
in the relevant sections of this readme.  The `parameters_config` file is for general code configurations,
`logging` is for the logging module, and `fw_config` is for the filter wheel positions.

<h3>B. Logger</h3>

The `logger` module is pretty self-explanatory, it handles the logging messages and log file writing of the code.
We use a rotating file handler, keeping backups of the previous 9 logs before overwriting the oldest ones.
The logger can be initiated by this simple example:

        from omegalambda.logger.logger import Logger

        log = Logger(r'C:\Users\[username]\omegalambda\omegalambda\config\logging.json')

And that's it!  A log file will now be automatically generated until the logger is stopped by calling `Logger.stop()`.

<h3>C. Input/Output (IO) and Datatypes</h3>

The `main/common/IO` directory includes the main file reader object (`Reader`) that converts these `.json`
files into Python dictionaries.  These are then fed to the `ObjectReader` which sorts them into the appropriate
datatype to be deserialzed.  One of these objects is the `Config` class in `config_reader.py`.
It has the following attributes:

        cooler_setpoint : INT, FLOAT, optional
            Setpoint in C when running camera cooler.  Our default is -30 C.
        cooler_idle_setpoint : INT, FLOAT, optional
            Setpoint in C when not running camera cooler.  Our default is +5 C.
        cooler_settle_time : INT, optional
            Time in minutes given for the cooler to settle to its setpoint. Our default is 5-10 minutes.
        maximum_jog : INT, optional
            Maximum distance in arcseconds to be used for the telescope jog function. Our default is 1800 arcseconds.
        site_latitude : FLOAT, optional
            Latitude at the telescope location.  Our default is +38.828 degrees.
        site_longitude : FLOAT, optional
            Longitude at the telescope location.  Our default is -77.305 degrees.
        site_altitude : FLOAT, optional
            Altitude above sea level at the telescope location.  Our default is 154 meters.
        humidity_limit : INT, optional
            Limit for humidity while observing.  Our default is 85%.
        wind_limit : INT, optional
            Limit for wind speed in mph while observing.  Our default is 20 mph.
        weather_freq : INT, optional
            Frequency of weather checks in minutes.  Our default is 10 minutes.
        cloud_cover_limit : FLOAT, optional
            Limit for percentage of sky around Fairfax to be covered by clouds before closing up.
            Our default is 75%.
        cloud_saturation_limit: FLOAT, optional
            Minimum pixel value that represents a clouds in the satellite image.  Our default is 100.
        rain_percent_limit: FLOAT, optional
            Limit for the percentage of rain present in 1/4 of the field surveyed before shutting down (two tiles
            out of the four must pass this threshold).  Our default is 5%.
        user_agent : STR, optional
            Internet user agent for connections, specifically to weather.com.  Our default is Mozilla/5.0.
        cloud_satellite : STR, optional
            Which satellite to use to check for cloud cover.  Currently only supports goes-16.  Our default is goes-16.
        weather_api_key : STR, optional
            The api key to search for in weather.com's api.  Sometimes changes and needs an update.  Should be a regex
            search string.
        min_reopen_time : INT or FLOAT, optional
            Minimum wait time to reopen (in minutes) after a weather check has gone off.  Our default is 30 minutes.
        plate_scale : FLOAT, optional
            CCD camera conversion factor between pixels and arcseconds, in arcseconds/pixel.  Our default is
            0.350 arcseconds/pixel.
        saturation : INT, optional
            CCD camera saturation limit for exposure in counts.  This is more like the exposure linearity limit, after
            which you'd prefer not to have targets pass.  Our default is 25,000 counts.
        focus_exposure_multiplier : FLOAT, optional
            Multiplier for exposure times on focusing images.  The multiplier is applied to the exposure time for the
            current ticket.  Our default is 0.33.
        initial_focus_delta : INT, optional
            Initial number of steps the focuser will move for each adjustment.  Our default is 15 steps.
        focus_temperature_constant : FLOAT, optional
            Relationship between focuser steps and degrees Fahrenheit, in steps/degF.  Our default is 2 steps/degF.
        focus_iterations : INT, optional
            The total number of exposures to take at the beginning of the night while focusing.  Our default is 11.
        focus_adjust_frequency : FLOAT or INT, optional
            How often the focus will adjust over the course of the night, in minutes.  Our default is 15 minutes.
        focus_max_distance : INT, optional
            Maximum distance away from the initial focus position that the focuser can move.  Our default is 100 steps.
        guiding_threshold : FLOAT, optional
            How far to let a star drift, in arcseconds, before making a guiding correction. Our default is 10
            arcseconds.
        guider_ra_dampening : FLOAT, optional
            Dampening coefficient for guider telescope corrections on the RA axis.  Our default is 0.75.
        guider_dec_dampening : FLOAT, optional
            Dampening coefficient for guider telescope corrections on the Dec axis.  Our default is 0.5.
        guider_max_move : FLOAT, optional
            The maximum distance in arcseconds that the guider can make adjustments for.  Our default is 30 arcseconds.
        guider_angle : FLOAT, optional
            The clocking angle of the CCD camera's x and y axes against the RA and Dec axes of the telescope, in
            degrees.  This is defined as the angle between the +x axis and the +RA axis, by rotating counterclockwise
            in the reference frame where RA increases to the left and Dec increases upwards.
            (i.e. counterclockwise angles in this frame are positive, while clockwise angles are negative).
            0.0 degrees corresponds to alignment between +x/+y and +RA/+Dec.  Our default is 180 degrees.
        guider_flip_y : BOOL, optional
            This supports guider axes configurations that are mirrored with respect to a simple guider angle flip.
            If True, this will flip the y axis of the guider.
            This would correspond to configurations that, at a 0 degree guider angle, would have +x aligned with +RA
            while +y is aligned with -Dec.  Or similarly if the guider angle is 180 degrees, +x aligns with -RA while
            +y aligns with +Dec.  Our default is False.
        data_directory : STR, optional
            Where images and other data are saved on the computer.  Our default is
            H:/Observatory Files/Observing Sessions/2020_Data.
        calibration_time : STR, optional
            If darks and flats should be taken at the start or end of a given observing session.  Can be str "start"
            or "end."  If "start", it will take darks and flats for ALL observing tickets at the start of the night.
            If "end", it will take darks and flats for all FINISHED tickets at the end of the night.
            Our default is "end".
        calibration_num : INT, optional
            The number of darks and flats that should be taken per target.  Note that there will be one set of flats
            with this number of exposures, but two sets of darks, each with this number of exposures: one to match
            the flat exposure time and the other to match the science exposure time.  Our default is 10.

As you can see, this object contains general configuration parameters that affect nearly every aspect of how
the code runs.  The only methods associated with this object are the `serialized()` and `deserialized()` methods,
the latter of which is a staticmethod used to convert `json.loads` objects into `Config` objects, and
the former of which is used to convert a `Config` object back into a Python dictionary.  These two methods
are common throughout the `FilterWheel` and `ObservationTicket` objects as well.

The `main/common/datatype` folder contains 
the software implementations of some of the other input datatypes.  Among these are the `FilterWheel` type, with the 
following attributes:

        position_1 - position_8 : str
            Each position will be the name/label of the filter in said position (i.e. "r" for red filter).
            For readability, each position is labeled by a str "position_X" rather than just an int X.

and the `ObservationTicket` type.  Observation Tickets are the method by which our code is instructed to
observe a certain target on a given night.  As such, an observation ticket object contains all the necessary
information about a target for the code to collect data on it.  `ObservationTicket` objects have the following
attributes:

        name : str, optional
            Name of intended target, ex: TOI1234.01 . The default is None.
        ra : float, str, optional
            Right ascension of target object. The default is None.
        dec : float, str, optional
            Declination of target object. The default is None.
        start_time : str, optional
            Start time of the observations. The default is None.
        end_time : str, optional
            End time of the observations. The default is None.
        _filter : str or list, optional
            List of filters that will be used during observing session.  Must be one of the following:
            "uv", "b", "v", "r", "ir", or "Ha".  The default is None.
        num : int, optional
            Number of exposures. The default is None.
        exp_time : float or list, optional
            Exposure time of each image in seconds.  List order must match the order of filters.  
            The default is None.
        self_guide : bool, optional
           If True, self-guiding module will activate, keeping the telescope
           pointed steady at the same target with minor adjustments. The default is None.
        guide : bool, optional
            Currently unused.  The default is None.
        cycle_filter : bool, optional
            If True, filters will be cycled through after each exposure, if False will take
            the num of specific images in one filter before moving to the next filter. 
            The default is None.

`ObservationTicket` objects have an additional method associated with them called `check_ticket()`.
This is used to validate that all parameters of the ticket are in the proper format, can be read by the code, 
and have valid values.  This generally should not be an issue if one utilizes the built-in observation ticket
creator widget, located in `observation_tickets/`.  This GUI is created using `tkinter` and allows for easy
creation of observation tickets.

<h3>D. Utils</h3>
The `main/common/util` folder contains three utility files with different classes of utility functions used throughout
the code.  `conversion_utils` handles unit conversions and coordinate conversions, `time_utils` handles
timezone and other date/time conversions, and `filereader_utils` handles image reading
to find stars peaks, FWHMs, and other image properties.

<h3>E. Controller</h3>
<h4>i. Hardware</h4>
The `main/controller/hardware.py` file contains the `Hardware` object, which is a parent class that all of
our hardware modules are subclassed from.  `Hardware` itself is a subclass of `threading.Thread`, allowing
each of our hardware objects to run concurrently on their own separate threads.  Before any hardware object
is instantiated, a global config object must be created.  This is done automatically when the `parameters_config.json`
file is read in via the `json_reader` and then the `object_reader`.  An example of how
this would be done is shown:

        import omegalambda as om
        
        # Read the config file in via the json reader
        reader = om.Reader('C:\Users\[username]\omegalambda\omegalambda\'
                        + 'config\parameters_config.json')
        # Sort the object into the correct type (in this case, Config)
        obj_reader = om.ObjectReader(reader)
        # The global object is automatically created!  Now you can instantiate any hardware class.

HOWEVER, it is not necessary to undergo this procedure, as it is done automatically upon
importing the OmegaLambda package.  If you wish to read the config file from a different directory from the default, you will
need to perform this step with your preferred directory.
The filter wheel configuration file may be read in in the exact same manner.

The `Hardware` class itself overwrite `threading.Thread`'s `__init__` and `run` methods to create a 
queue system for placing methods on the queue list for a hardware object.
A concrete example will be provided for the `Camera` module.

<h4>ii. Camera</h4>
`main/controller/camera.py` controls the CCD camera via a win32com port dispatch to MaxIm DL.
It has methods for setting the cooler, exposing images, etc.  Now, for that example of how the threading and queue system works:

        import omegalambda as om

        # Initialize the camera object (does not connect to the hardware yet)
        camera = om.Camera()

        # Start the camera thread (actually calls camera.run).  When the thread is started, it will
        # automatically try connecting to the hardware.
        camera.start()

        # If the hardware connection was successfully established, you should get a logging
        # message saying so.  Then, you can put methods on the camera queue by using onThread():
        camera.onThread(camera.expose, 15, 2)
        
        # You can then disconnect from the hardware and stop the thread
        camera.onThread(camera.disconnect)
        camera.onThread(camera.stop)

<h4>iii. Dome</h4>
`main/controller/dome.py` controls the dome via a win32com port dispatch to ASCOM.  It has methods
for slewing, parking, home, syncing, opening & closing the shutter, etc.

<h4>iv. Telescope</h4>
`main/controller/telescope.py` controls the telescope via a win32com port dispatch to ASCOM, specifically
our SoftwareBisque mount.  It has methods for slewing, parking, unparking, tracking, guiding, etc.

<h4>v. Focus Control</h4>
`main/controller/focus_control.py` controls the position tertiary mirror of the telescope via a serial port
connection.  It does not rely on RoboFocus or any other API and talks directly to the rotor mechanism.  It has methods
for moving the focus in/out, or moving to an arbitrary position.

<h4>vi. Focus GUI</h4>
`main/controller/focuser_gui.py` is a GUI for controlling the focuser.  This was created to still allow user control
of the focus manually while the code is running.  The win32com dispatches already allow this because
MaxIm DL, ASCOM, etc. all have GUIs for manual control, but because we used a serial connection for
the focuser, this was a necessary addition.

<h4>vii. Flatfield Lamp</h4>
`main/controller/flatfield_lamp.py` controls the flatfield lamp inside the dome.  This is done via a serial
connection to an Arduino device that turns the lamp on or off.  As such, there are methods for turning the lamp on
and off.

<h3>F. High-Level Hardware Structures</h3
<h4>i. Weather Conditions</h4>
`main/observing/condition_checker.py` implements a framework for checking the current weather conditions
periodically to ensure that it is still safe to be observing.  The weather is checked via the GMU
College of Science weather monitor, or, if that website is down/outdated, it uses estimates from weather.com instead.


<h4>ii. Focus Procedures</h4>
`main/controller/focuser_procedures.py` implements a framework for automatically determining the best
focus position at the beginning of an observation, as well as gradually adjusting the focus position over the
course of the night.  

It reads images from the camera and calculates the FWHM of the brightest stars to 
determine the focus quality.  It then moves the focus to a new position and makes another measurement.  After
~10 of these measurements, it fits the data to a parabola (with a positive quadratic term) and moves the focus to the minimum 
of the parabola (that is, if the fit succeeded...it doesn't always).

The gradual focusing uses a linear temperature-dependence model to determine how much to move the focus
over the course of the night.


The `FocusProcedures` object thus requires the `Focus`, `Camera`, and `Conditions` objects
as input parameters.

<h4>iii. Guiding</h4>
`main/observing/guider.py` implements a framework for actively guiding on a target to keep it relatively
stable within an image.

It reads in images from the camera and determines where the stars are.  It then waits for the next image and
calculates the displacement of the stars between images, then instructs the telescope to move back to correct
the displacement.

The `Guider` object thus requires the `Camera` and `Telescope` objects as input parameters.

<h4>iv. Calibration</h4>
`main/observing/calibration.py` implements a framework for gathering calibration images (i.e. darks
and flats) for a given target.

It reads in the target's exposure times/filters and gathers the necessary calibration images while turning on
the flatfield lamp for flats and turning it off for darks.  The calibration module assumes that the dome is closed
when it has been called, as it does not force the dome to close itself.

The `Calibration` object thus requires the `Camera` and `FlatLamp` objects as input parameters, as
well as the image directories for each target.

<h4>v. Thread Monitoring</h4>
`main/controller/thread_monitor.py` implements a framework for monitoring the status of each hardware
thread and making sure it is still "alive" (i.e. running).  If it finds that a thread has crashed, it will send instructions
to restart it to the main observation run code.  It requires all of the code's threads sorted into a
dictionary as an input parameter.

<h3>G. The Main Observation Run</h3>
`main/observing/observation_run.py` is the heart of the OmegaLambda code.  This is where everything is put 
together into a complete framework for observation runs.  It instantiates all of the hardware objects and starts
their threads before beginning the observing sequence, which generally follows the order of: check 
weather conditions and start time; open observatory and slew; focus on the target; take as many exposures as
instructed while checking the weather, focusing, and guiding in the background; if the weather alert goes
off, shut down and take calibration images and wait for the weather to clear up again; move on to the next target;
repeat for all targets; shut down the observatory and end all processes.

An example of how the code would be started using the obesrvation run module looks like this:

        # Read in your observation ticket
        reader = Reader('observation_ticket_example.json')
        object_reader = ObjectReader(reader)
        
        # Prepare the observation ticket and image write directory
        observation_request_list = [object_reader.ticket]
        folder = 'C:\Useres\[username]\example_image_directory\'
        
        # Instantiate the observation run object
        run_object = ObservationRun(observation_request_list, folder, shutdown_toggle=True,
                                    calibration_toggle=True, focus_toggle=True)

        # Call the observe() function to begin
        run_object.observe()

<h2>III. The Main Driver</h2>
All of the examples thus far have been to demonstrate how the code works, but they would not actually be
particularly useful for a real nightly observation.  This code was really only built to be utilized by its main driver, 
under `main/drivers/driver.py`.  The `run()` function properly initializes all of the config objects, reads
the observation ticket, and begins the observation run in the "intended" way, for lack of a better term.
One could call the `run()` function in the driver directly, but this can also be a bit clunky and not user-friendly, so
we have developed a command-line interface (CLI) to run the code, which is the main way that
it is utilized nightly at our observatory.

<h2>IV. The Command-Line Interface (CLI)</h2>
`main/__main__.py` is responsible for creating the CLI, so one is able to simply create an observation ticket
and pass it into the code via the CLI without worrying about any of its inner-workings.  The CLI only has one 
function, `run`, which calls the `run()` function in the driver.  Run has the observation tickets as its only required
arguments (by which you pass in the filepaths as strings), but it also has a few optional parameters
as well corresponding to the init parameters of the `ObservationRun` class.  One can always use the `-h` or `--help` commands
on the CLI for further info, but we also provide it here.  As always, if you have a specific
environment for this code, make sure you are in it before attempting to run it or use the CLI.

If you simply run `python -m omegalambda -h`, you will receive a message showing you the available functions
(of which there is only one):

        usage: __main__.py [-h] {run} ...
        
        Telescope automation code
        
        positional arguments:
          {run}
            run       Start an observation run
        
        optional arguments:
          -h, --help  show this help message and exit

And if you run `python -m omegalambda run -h`, you will see all of the optional arguments for the `run` 
function:

        usage: __main__.py run [-h] [--data PATH] [--config PATH] [--filter PATH] [--logger PATH] 
                                    [--noshutdown] [--nocalibration] [--nofocus] 
                                    obs_tickets [obs_tickets ...]
        
        positional arguments:
          obs_tickets           Paths to each observation ticket, or 1 path to a directory with 
                                observation tickets.
        
        optional arguments:
          -h, --help            show this help message and exit
          --data PATH, -d PATH  Manual save path for CCD image files.
          --config PATH, -c PATH
                                Manual file path to the general config json file.
          --filter PATH, -f PATH
                                Manual file path to the filter wheel config json file.
          --logger PATH, -l PATH
                                Manual file path to the logging config json file.
          --noshutdown, -ns     Use this option if you do not want to shutdown after running 
                                the tickets. Note this will also stop the program from taking 
                                any darks and flats if the calibration time is set to end.
          --nocalibration, -nc  Use this option if you do not want to take any darks and flats.
          --nofocus, -nf        Use this option if you do not want to perform the automatic 
                                focus procedure at thebeginning of the night. Continuous 
                                focusing will still be enabled.

So, a few examples.  Say you want to run your observation ticket with all of the defaults.  You would simply
do 

`python -m omegalambda run '/path/to/observation/ticket.json'`.  

If you have multiple tickets, just add them on:

`python -m omegalambda run '/path/to/observation/ticket1.json' '/path/to/observation/ticket2.json'`.  

However, if you already took dark and flat
images beforehand, you would instead want to run 

`python -m omegalambda run -nc '/path/to/observation/ticket'`.

Or, if you are already confident about the focus of your target, or want to focus manually:

`python -m omegalambda run -nf '/path/to/observation/ticket'`.

Finally, if you'd like to continue using the telescope after the observing sequence:

`python -m omegalambda run -ns '/path/to/observation/ticket'`.

These arguments can be stacked of course, so if you are in a situation where all 3 of the above apply:

`python -m omegalambda run -nf -ns -nc '/path/to/observation/ticket'`.

<h2>V. The Observation Ticket Creator Widget</h2>
Under `observation_tickets/` there is a widget called `Observation_ticket_creator.pyw`.  This is a
GUI designed to make it easy to create observation tickets for a given target.  Simply run the python file and 
input your target specifications into the appropriate blanks.  Also note the checkboxes for the `self_guide`, `guide`, 
and `cycle_filter` attributes.  Once you are done, simply click "Apply" and "Quit".  The "Fetch" button
is designed to automatically fetch the planned target information for the current night at the GMU
observatory.  This target also appears in the title of the GUI.  Please note that this Fetch button WILL NOT WORK
unless you are running the code on the GMU observatory control computer, because it requires
a local file with usernames/passwords that we do not want to give out to the public.

<h2>Final Note</h2>
For an even more in-depth guide on how the code is utilized in our observatory and how a typical night
of observation might go, please see this user guide: https://docs.google.com/document/d/1nmQr_vSFRBtiRrTm_y940Fxu_KhYTOQgs1gg9rFC_TQ/edit#.
