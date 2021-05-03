import datetime
import numpy as np
from astropy.time import Time
import pandas as pd
from astroquery.simbad import Simbad
from astropy.coordinates import SkyCoord
import astropy.units as u
from barycorrpy import JDUTC_to_BJDTDB
import logging
from typing import Union, Optional
import requests
import requests.exceptions
import re
import urllib3.exceptions

import pytz
import dateutil.parser


def rounddown_300(x: Union[int, float]) -> int:
    """

    Parameters
    ----------
    x : INT or FLOAT
        Any real number.

    Returns
    -------
    INT
        Rounds x down to the nearest multiple of 300.
        Does not round up.  Needed for weather.com api.

    """
    logging.debug('Called time_utils function')
    return int(x/300)*300


def convert_to_datetime_utc(date: str) -> datetime.datetime:
    """

    Parameters
    ----------
    date : STR
        May be a date/time string in almost any format.  Will be parsed by dateutil.parser.

    Returns
    -------
    DATETIME.DATETIME
        Datetime object in UTC time, timezone-aware.

    """
    logging.debug('Called time_utils function')
    d = dateutil.parser.parse(date)
    return d.replace(tzinfo=pytz.UTC) - d.utcoffset()


def convert_to_datetime(date: str) -> datetime.datetime:
    """

    Parameters
    ----------
    date : STR
        May be a date/time string in almost any format.  Will be parsed by dateutil.parser.

    Returns
    -------
    d : DATETIME.DATETIME
        Datetime object in whatever timezone is passed in, timezone-aware.

    """
    logging.debug('Called time_utils function')
    d = dateutil.parser.parse(date)
    return d


def datetime_to_epoch_milli_converter(date: Union[str, datetime.datetime]) -> Union[int, float]:
    """

    Parameters
    ----------
    date : DATETIME.DATETIME
        Should be timezone-aware, in UTC--generated from convert_to_datetime_UTC.

    Returns
    -------
    FLOAT
        Number of milliseconds since Jan. 1, 1970.  Common way of measuring time.

    """
    logging.debug('Called time_utils function')
    if type(date) is not datetime.datetime:
        date = convert_to_datetime_utc(date)
    epoch = datetime.datetime.utcfromtimestamp(0)
    return (date.replace(tzinfo=None) - epoch).total_seconds() * 1000


def epoch_milli_to_datetime_converter(epochmilli: Union[int, float]) -> datetime.datetime:
    """

    Parameters
    ----------
    epochmilli : FLOAT
        Timestamp in the form of milliseconds since Jan. 1, 1970.

    Returns
    -------
    DATETIME.DATETIME
        Timezone-aware, UTC datetime.datetime object.

    """
    logging.debug('Called time_utils function')
    return datetime.datetime.utcfromtimestamp(epochmilli / 1000).replace(tzinfo=pytz.UTC)


def days_since_j2000(date: Optional[Union[datetime.datetime, str]] = None) -> float:
    """

    Parameters
    ----------
    date : DATETIME.DATETIME, optional
        Should be timezone-aware, UTC datetime.datetime object.  The default is None, which
        will calculate the days since J2000 for today.

    Returns
    -------
    days : FLOAT
        Timestamp in the form of days since Jan. 1, 2000.

    """
    logging.debug('Called time_utils function')
    if date is None:
        date = datetime.datetime.now(datetime.timezone.utc)
    if type(date) is not datetime.datetime:
        date = convert_to_datetime_utc(date)
    if not date.tzinfo:
        date = pytz.utc.localize(date)
    j2000 = datetime.datetime(2000, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
    days = (date - j2000).total_seconds()/(60*60*24)
    return days


def days_of_year(date: Optional[Union[str, datetime.datetime]] = None) -> float:
    """

    Parameters
    ----------
    date : DATETIME.DATETIME, optional
        Should be timezone-aware datetime object. The default is None, which will calculate the
        days of the year for today.

    Returns
    -------
    days : FLOAT
        Timestamp in the form of days since Jan. 1, [current year].

    """
    logging.debug('Called time_utils function')
    if date is None:
        date = datetime.datetime.now(datetime.timezone.utc)
    if type(date) is not datetime.datetime:
        date = convert_to_datetime_utc(date)
    first_day = datetime.datetime(date.year, 1, 1, 0, 0, 0, tzinfo=date.tzinfo)
    days = (date - first_day).total_seconds()/(60*60*24)
    return days + 1


def fractional_hours_of_day(time: Optional[Union[str, datetime.datetime]] = None) -> float:
    """

    Parameters
    ----------
    time : DATETIME.DATETIME, optional
        Should be timezone-aware, UTC datetime.datetime object.  The default is None, which
        will calculate the fractional hours of the day for right now.

    Returns
    -------
    hours : FLOAT
        Timestamp in the form of fractional hours of the day.  I.e. if it is 12 p.m., the day
        is halfway over, so this will return 0.5.

    """
    logging.debug('Called time_utils function')
    if time is None:
        time = datetime.datetime.now(datetime.timezone.utc)
    if type(time) is not datetime.datetime:
        time = convert_to_datetime_utc(time)
    if not time.tzinfo:
        time = pytz.utc.localize(time)
    hours = (time - datetime.datetime(time.year, time.month, time.day, 0, 0, 0, tzinfo=datetime.timezone.utc))
    hours = hours.total_seconds()/(60*60)
    return hours


def decimal_year(time=None) -> float:
    """

    Returns
    -------
    FLOAT
        Current year in decimal form.  i.e. if it is June, 1995, this would return 1995.5.
        Needed for different epoch coordinate conversions.

    """
    logging.debug('Called time_utils function')
    if time is None:
        time = datetime.datetime.now()
    mods = ((time.year % 400 == 0), (time.year % 100 == 0), (time.year % 4 == 0))
    leap = True if mods[0] else False if mods[1] else True if mods[2] else False
    days_in_year = 365 if not leap else 366
    return time.year + (time.month - 1)/12 + (time.day - 1)/days_in_year + time.hour/(days_in_year*24) + \
        time.minute/(days_in_year*24*60) + time.second/(days_in_year*24*60*60)


def get_local_sidereal_time(longitude: float, date: Optional[Union[str, datetime.datetime]] = None,
                            leap_seconds = 0) -> float:
    """
    Find the local mean sidereal time for a particular longitude and datetime.
    Formulas gathered from the following references.
    References:
        1.  K. Collins and J. Kielkopf, “Astroimagej: Imagej for astronomy,” (2013). Astrophysics source code library.
            https://github.com/karenacollins/AstroImageJ.
        2.  R. Fisher, "Astronomical Times," Harvard University. https://lweb.cfa.harvard.edu/~jzhao/times.html.

    Parameters
    ----------
    longitude : FLOAT
        Site longitude where you want to calculate LST.  West is negative.
    date : DATETIME.DATETIME, optional
        UTC Date and time for which you want to calculate LST. The default is None, which
        will calculate the LST for the current date & time.
    leap_seconds : INT, optional
        The number of seconds offset between TAI and TT.  As of April 9, 2021, there are 37 seconds offset.
        If 0, will do an html request to get the current number.

    Returns
    -------
    LST : FLOAT
        Local sidereal time in hours.

    """
    if leap_seconds == 0:
        s = requests.Session()
        try:
            req = s.get('https://hpiers.obspm.fr/eop-pc/webservice/CURL/leapSecond.php')
            match = re.search('([0-9]+)|', req.text)
            if match:
                leap_seconds = int(match.group(0))
        except (urllib3.exceptions.MaxRetryError, urllib3.exceptions.HTTPError, urllib3.exceptions.TimeoutError,
                urllib3.exceptions.InvalidHeader, requests.exceptions.ConnectionError, requests.exceptions.Timeout,
                requests.exceptions.HTTPError):
            logging.warning('Could not get leap second data!')
    logging.debug('Called time_utils function')
    if date is None:
        date = datetime.datetime.now(datetime.timezone.utc)
    if type(date) is not datetime.datetime:
        date = convert_to_datetime_utc(date)
    if not date.tzinfo:
        date = pytz.utc.localize(date)
    if date.tzinfo not in (pytz.UTC, pytz.utc, datetime.timezone.utc):
        date = date.astimezone(pytz.UTC)
    jd = convert_to_jd_utc(date.replace(hour=0, minute=0, second=0, microsecond=0))
    ut_hours = fractional_hours_of_day(date)

    omega = sun_moon_longitudes(jd, leap_seconds)[0]
    tmid = (jd - 2451545.0) / 36525.0  # offset Julian centuries
    t0 = (6.697374558 + 2400.0513369072 * tmid + (2.58622 * tmid**2)*1e-5 - (1.7222078704899681391543959355894 * tmid**3)*1e-9) % 24
    gmst = (t0 + ut_hours * 1.00273790935 + n_longitude(jd, leap_seconds) * np.cos(true_obliquity(jd, leap_seconds)*np.pi/180) / 15) % 24
    gmst += (0.00625 * np.sin(omega) + 0.0000063 * np.sin(2 * omega)) / 3600

    lmst_frac = (gmst + longitude / 15) / 24
    day_frac = lmst_frac - int(lmst_frac)
    if day_frac < 0:
        day_frac += 1
    lmst = 24.0 * day_frac
    return lmst


def sun_moon_longitudes(julian_date, leap_seconds):
    """
    Find the longitude of the moon's ascending node, the mean orbital longitude of the moon, and the geometric mean longitude
    of the sun for a particular julian date.
    Formulas gathered from the following references.
    References:
        1.  K. Collins and J. Kielkopf, “Astroimagej: Imagej for astronomy,” (2013). Astrophysics source code library.
            https://github.com/karenacollins/AstroImageJ.

    Parameters
    ----------
    julian_date: FLOAT, the julian date at which to calculate.
    leap_seconds: INT, number of leap seconds offset between TAI and TT.

    Returns
    -------
    all in radians
    omega: FLOAT, longitude of moon's ascending node
    glsun: FLOAT, mean geometric longitude of sun
    lmoon: FLOAT, mean longitude of the moon
    """

    # leap second offset between TT and UT1
    dt = (leap_seconds + 32.184) / (36525 * 24 * 60 * 60)
    t = (julian_date - 2451545.0) / 36525.0
    t += dt

    # Moon orbit longitude of ascending node
    omega = (125.04452 - 1934.136261 * t + 0.0020708 * t**2 + t**3 / 450000) % 360
    lmoon = (218.31654591 + 481267.88134236 * t - 0.00163 * t**2 + t**3 / 538841. - t**4 / 65194000) % 360
    # Sun orbit longitude
    lsun = (280.46645 + 36000.76983 * t + 0.0003032 * t**2) % 360
    # Mean anomaly of sun
    msun = (357.52910 + 35999.05030 * t - 0.0001559 * t**2 - 0.00000048 * t**3) % 360
    msun = np.radians(msun)
    # Center of sun
    csun = (1.9146000 - 0.004817 * t - 0.000014 * t**2) * np.sin(msun) + (0.019993 - 0.000101 * t) * np.sin(2. * msun) \
            + 0.000290 * np.sin(3. * msun)
    # Geometric longitude
    glsun = (lsun + csun) % 360

    omega, glsun, lmoon = np.radians([omega, glsun, lmoon])
    return omega, glsun, lmoon


def n_longitude(julian_date, leap_seconds):
    """
    Find the nutation of the longitude of the ecliptic for a specific julian date.
    Formulas gathered from the following references.
    References:
        1.  K. Collins and J. Kielkopf, “Astroimagej: Imagej for astronomy,” (2013). Astrophysics source code library.
            https://github.com/karenacollins/AstroImageJ.
        2. J. Souchay and N. Capitaine, "Precession and Nutation of the Earth," from Ideas in Astronomy and Astrophysics
            (2013).  Springer Berlin Heidelberg: Berlin, Heidelberg. 115-166, DOI: 10.1007/978-3-642-32961-6_4.

    Parameters
    ----------
    julian_date: FLOAT, the julian date at which to calculate.
    leap_seconds: INT, number of leap seconds offset between TAI and TT.

    Returns
    -------
    dpsi: FLOAT, nutation of the ecliptic, in degrees
    """
    omega, glsun, lmoon = sun_moon_longitudes(julian_date, leap_seconds)

    # Nutation correction
    dpsi = -17.16 * np.sin(omega) - 1.263 * np.sin(2. * glsun) - 0.205 * np.sin(2. * lmoon) - 0.034 * np.sin(2. * lmoon - omega)
    dpsi /= 3600
    return dpsi


def true_obliquity(julian_date, leap_seconds):
    """
    Find the true obliquity of the ecliptic for a specific julian date.
    Formulas gathered from the following references.
    References:
        1.  K. Collins and J. Kielkopf, “Astroimagej: Imagej for astronomy,” (2013). Astrophysics source code library.
            https://github.com/karenacollins/AstroImageJ.\
        2. J. Souchay and N. Capitaine, "Precession and Nutation of the Earth," from Ideas in Astronomy and Astrophysics
            (2013).  Springer Berlin Heidelberg: Berlin, Heidelberg. 115-166, DOI: 10.1007/978-3-642-32961-6_4.

    Parameters
    ----------
    julian_date: FLOAT, the julian date at which to calculate.
    leap_seconds: INT, number of leap seconds offset between TAI and TT.

    Returns
    -------
    eps0+deps : FLOAT, obliquity of the ecliptic in degrees
    """
    # leap second offset between TT and UT1
    dt = (leap_seconds + 32.184) / (36525 * 24 * 60 * 60)
    t = (julian_date - 2451545.0) / 36525.0
    t += dt

    # Mean Obliquity (deg)
    eps0 = 23.0 + 26/60 + 21.448/3600
    eps0 += (-46.8150 * t - 0.00059 * t**2 + 0.001813 * t**3)/3600

    omega, glsun, lmoon = sun_moon_longitudes(julian_date, leap_seconds)
    deps = 9.17 * np.cos(omega) + 0.548 * np.cos(2. * glsun) + 0.089 * np.cos(2. * lmoon) + 0.018 * np.cos(2. * lmoon - omega)
    deps /= 3600
    return eps0 + deps


def convert_to_jd_utc(time=None, split_date=False):
    if not time:
        time = datetime.datetime.now(datetime.timezone.utc)
    if type(time) is not datetime.datetime:
        time = convert_to_datetime_utc(time)
    t = Time(time, format='datetime', scale='utc')
    if split_date:
        return t.jd1, t.jd2
    return t.jd


def convert_to_bjd_tdb(jd, name, lat, lon, height, ra=None, dec=None):
    # Get target proper motion, parallax, and radial velocity from exofop
    epoch = 2451545.0
    pmra = pmdec = None
    if ra:
        ra *= 15

    # First try ExoFOP for proper motions
    # if ('TOI' in name) or ('toi' in name):
    #     toi_table = pd.read_csv('https://exofop.ipac.caltech.edu/tess/download_toi.php?sort=toi&output=pipe', delimiter='|')
    #     toi = re.search('(?:TOI|toi)(?:_| |-|.)(\d+)(?:.|-| |_)(\d+)', name)
    #     if toi:
    #         toi = int(toi.group(1)) + int(toi.group(2))/100
    #         if int(toi) == toi:
    #             toi += .01
    #         toi_info = toi_table.loc[toi_table['TOI'] == toi]
    #         if toi_info.values.size:
    #             pmra = toi_info['PM RA (mas/yr)'].values[0]
    #             pmdec = toi_info['PM Dec (mas/yr)'].values[0]

    # Query SIMBAD for proper motion, parallax, and RV
    try:
        simbad = Simbad()
        simbad.add_votable_fields('ra(2;A;ICRS;J2000)', 'dec(2;D;ICRS;J2000)','pm', 'plx','parallax','rv_value')
        simbad.remove_votable_fields('coordinates')
        table = simbad.query_object(name)
    except (urllib3.exceptions.MaxRetryError, urllib3.exceptions.HTTPError, urllib3.exceptions.TimeoutError,
            urllib3.exceptions.InvalidHeader, requests.exceptions.ConnectionError, requests.exceptions.Timeout,
            requests.exceptions.HTTPError, TimeoutError):
        return None
    if not table:
        if not ra or not dec:
            return None
        table = simbad.query_region(SkyCoord(ra*u.degree, dec*u.degree, frame='icrs'), radius='5m')
    if table:
        if not ra:
            ra = decimal(table['RA_2_A_ICRS_J2000'][0]) * 15
        if not dec:
            dec = decimal(table['DEC_2_D_ICRS_J2000'][0])
        if not pmra:
            pmra = table['PMRA'][0]
        if not pmdec:
            pmdec = table['PMDEC'][0]
        parallax = table['PLX_VALUE'][0]
        radial_velocity = table['RV_VALUE'][0] * 1000
    else:
        return None

    if (not radial_velocity) or (not pmra) or (not pmdec) or (not ra) or (not dec) or (not parallax):
        return None

    return JDUTC_to_BJDTDB(JDUTC=jd, ra=ra, dec=dec, epoch=epoch, pmra=pmra, pmdec=pmdec, px=parallax,
                           rv=radial_velocity, lat=lat, longi=lon, alt=height, leap_update=False)[0][0]


def sexagesimal(decimal: float) -> str:
    hh = int(decimal)
    f1 = hh if hh != 0 else 1

    extra = decimal % f1
    mm = int(extra * 60)
    f2 = mm if mm != 0 else 1

    extra2 = (extra * 60) % f2
    ss = extra2 * 60

    mm = abs(mm)
    ss = abs(ss)
    return '{:02d} {:02d} {:08.5f}'.format(hh, mm, ss)


def decimal(sexagesimal: str) -> float:
    splitter = 'd|h|m|s|:| '
    valtup = re.split(splitter, sexagesimal)
    hh, mm, ss = float(valtup[0]), float(valtup[1]), float(valtup[2])
    if hh > 0 or valtup[0] == '+00' or valtup[0] == '00':
        return hh + mm/60 + ss/3600
    elif hh < 0 or valtup[0] == '-00':
        return hh - mm/60 - ss/3600