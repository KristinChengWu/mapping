import math
from math import pi, sin, cos, tan, sqrt
import json

import numpy as np
import pandas as pd
from scipy.optimize import root_scalar
from astropy.time import Time
import astropy.units as u
from astropy.coordinates.earth import EarthLocation

from scanning import FYST_LOC, _central_diff

"""
specify units when passing in x, y
azimuth in terms of east from north 
"""

##################
#  SKY PATTERN 
##################

class SkyPattern():
    """
    Attributes
    ---------------------------
    data : pd.DataFrame : time_offset [s], x_coord [deg], y_coord [deg]
    param : dict
    repeatable
    """

    _param_unit = {'num_repeat': u.dimensionless_unscaled, 'sample_interval': u.s}
    _data_unit = {'time_offset': u.s, 'x_coord': u.deg, 'y_coord': u.deg}

    def __init__(self, data, repeatable=False, **kwargs) -> None:
        """
        Initialize an arbitrary scan. 

        Parameters
        --------------------------------
        data : str; ndarray, Iterable, dict, or DataFrame
            File path to csv file. Dict can contain Series, arrays, constants, dataclass or list-like objects. 
            Has columns 'time_offset', 'x_coord', 'y_coord'
        repeatable : bool, default False
            Whether this pattern can repeat itself (end where it starts).
        
        **kwargs
        max_scan_duration : time-like, default unit sec
            Maximum total scan time to determine number of repeats. Must be positive. 
            Cannot be used with num_repeat. 'repeatable' must be True.
        num_repeat : int, default 1 
            Number of repeats of the pattern. Must be >= 1
            Cannot be used with max_scan_duration. 'repeatable' must be True.
        """
        self.repeatable = repeatable 

        if isinstance(data, str):
            data = pd.read_csv(data, index_col=False, usecols=['time_offset', 'x_coord', 'y_coord'])
        else:
            data = pd.DataFrame(data, columns=['time_offset', 'x_coord', 'y_coord'])

        # determine sample_interval 
        sample_interval_list = np.diff(data['time_offset'].to_numpy())
        if np.std(sample_interval_list)/np.mean(sample_interval_list) <= 0.01:
            sample_interval = np.mean(sample_interval_list)
        else:
            raise ValueError('sample_interval must be constant')
        kwargs['sample_interval'] = sample_interval

        self.param = self._clean_param(**kwargs)
        self.data = self._repeat_scan(data)

    def _clean_param(self, **kwargs):
        kwarg_keys = kwargs.keys()

        # determining number of repeats 
        if self.repeatable:
            if 'max_scan_duration' in kwarg_keys and 'num_repeat' in kwarg_keys:
                raise ValueError('max_scan_duration and num_repeat cannot be inputted together')
            elif 'max_scan_duration' in kwarg_keys:
                kwargs['num_repeat'] = math.nan
                kwargs['max_scan_duration'] = u.Quantity(kwargs['max_scan_duration'], u.s).value
            else:
                kwargs['num_repeat'] = int(kwargs.get('num_repeat', 1))  

        # checking if repeats aren't passed if a non-repeatable pattern
        else:
            if 'max_scan_duration' in kwarg_keys or 'num_repeat' in kwarg_keys:
                raise ValueError('this is not a repeatable SkyPattern, so max_scan_duration and num_repeat cannot be initialized')
            kwargs['num_repeat'] = 1

        return kwargs

    def _repeat_scan(self, data):
        one_scan_duration = data.iloc[-1]['time_offset'] + self.sample_interval.value

        # determine number of repeats
        num_repeat = self.num_repeat
        if math.isnan(num_repeat):
            max_scan_duration = self.param.pop('max_scan_duration') # only store number of repeats, not maximum scan duration
            num_repeat = math.floor(max_scan_duration/one_scan_duration)
            if num_repeat < 1:
                raise ValueError(f'max_scan_duration = {max_scan_duration} s is too short, one scan duration is {one_scan_duration} second')

            self.param['num_repeat'] = num_repeat

        # repeat pattern if necessary 
        time_offset = data['time_offset']
        if num_repeat > 1:
            data_temp = data.copy()
            for i in range(1, num_repeat):
                data_temp['time_offset'] = time_offset + one_scan_duration*i
                data = data.append(data_temp, ignore_index=True)

        return data

    def save_data(self, path_or_buf=None, columns='default', include_repeats=True):
        """
        Parameters
        ----------------------------
        path_or_buf : str or file handle, default None
            File path or object, if None is provided the result is returned as a dictionary.
        columns : sequence or str, default 'default'
            Columns to write. 
            'default' for ['time_offset', 'x_coord', 'y_coord']
            'all' for ['time_offset', 'x_coord', 'y_coord', 'x_vel', 'y_vel', 'vel', 'x_acc', 'y_acc', 'acc', 'x_jerk', 'y_jerk', 'jerk']
        include_repeats : bool, default 'True'
            include repeats of the SkyPattern

        Returns
        ----------------------
        None or dict
            If path_or_buf is None, returns the resulting json format as a dictionary. Otherwise returns None.
        """

        # replace str options
        if columns == 'default':
            columns = ['time_offset', 'x_coord', 'y_coord']
        elif columns == 'all':
            columns = ['time_offset', 'x_coord', 'y_coord', 'x_vel', 'y_vel', 'vel', 'x_acc', 'y_acc', 'acc', 'x_jerk', 'y_jerk', 'jerk']
        
        data = self.data.copy()

        # whether to include repetitions 
        if not include_repeats and self.num_repeat > 1:
            before_index = int(len(data.index)/self.num_repeat)
            data = data.iloc[:before_index]

        # generate required data
        for col in columns:
            if not col in ['time_offset', 'x_coord', 'y_coord']:
                data[col] = getattr(self, col).value
        
        # save data file 
        if path_or_buf is None:
            return data[columns].to_dict('list')
        else:
            data.to_csv(path_or_buf, columns=columns, index=False)

    def save_param(self, path_or_buf=None):
        """
        Parameters
        ----------------------------
        path_or_buf : str or file handle, default None
            File path or object, if None is provided the result is returned as a dictionary.
        
        Returns
        ----------------------
        None or dict
            If path_or_buf is None, returns the resulting json format as a dictionary. Otherwise returns None.
        """
        
        param_temp = self.param.copy()

        # save param_json
        if path_or_buf is None:
            return param_temp
        else:
            with open(path_or_buf, 'w') as f:
                json.dump(param_temp, f)

    # GETTERS

    def __getattr__(self, attr):

        if attr in self.param.keys():
            if self._param_unit[attr] is u.dimensionless_unscaled:
                return self.param[attr]
            else:
                return self.param[attr]*self._param_unit[attr]
        elif attr in self.data.columns:
            return self.data[attr].to_numpy()*self._data_unit[attr]
        else:
            raise AttributeError(f'attribtue {attr} not found')

    @property
    def scan_duration(self):
        return self.time_offset[-1] + self.sample_interval

    @property
    def x_vel(self):
        return _central_diff(self.x_coord.value, self.sample_interval.value)*u.deg/u.s

    @property
    def y_vel(self):
        return _central_diff(self.y_coord.value, self.sample_interval.value)*u.deg/u.s

    @property
    def vel(self):
        return np.sqrt(self.x_vel**2 + self.y_vel**2)

    @property
    def x_acc(self):
        return _central_diff(self.x_vel.value, self.sample_interval.value)*u.deg/u.s/u.s

    @property
    def y_acc(self):
        return _central_diff(self.y_vel, self.sample_interval.value)*u.deg/u.s/u.s
    
    @property
    def acc(self):
        return np.sqrt(self.x_acc**2 + self.y_acc**2)

    @property
    def x_jerk(self):
        return _central_diff(self.x_acc.value, self.sample_interval.value)*u.deg/(u.s)**3
    
    @property
    def y_jerk(self):
        return _central_diff(self.y_acc.value, self.sample_interval.value)*u.deg/(u.s)**3
    
    @property
    def jerk(self):
        return np.sqrt(self.x_jerk**2 + self.y_jerk**2)

class Pong(SkyPattern):
    """
    The Curvy Pong pattern allows for an approximation of a Pong pattern while avoiding 
    sharp turnarounds at the vertices. 
    
    See "The Impact of Scanning Pattern Strategies on Uniform Sky Coverage of Large Maps" 
    (SCUBA Project SC2/ANA/S210/008) for details of implementation. 
    """

    _param_unit = {
        'num_term': u.dimensionless_unscaled,
        'width': u.deg, 'height': u.deg, 'spacing': u.deg,
        'velocity': u.deg/u.s, 'angle': u.deg, 'sample_interval': u.s, 
        'num_repeat': u.dimensionless_unscaled
    }
    repeatable = True

    def __init__(self, param_json=None, **kwargs) -> None:
        """
        Initialize a Pong pattern by passing a parameter file or dictionary and optionally 
        adding keywords to overwrite existing ones:
            option1 : Pong(param_json, **kwargs) 
        or building from scratch: 
            option2 : Pong(**kwargs)

        Parameters
        ---------------------------
        param_json : str or dict
            Contains parameters used to generate pattern. 
        
        **kwargs
        num_term : int
            Number of terms in the triangle wave expansion. Must be positive. 
        width, height : angle-like, default unit deg
            Width and height of field of view. Must be positive. 
        spacing : angle-like, default unit deg
            Space between adjacent (parallel) scan lines in the Pong pattern. Must be positive.
        velocity : angle/time-like, default unit deg/s
            Target magnitude of the scan velocity excluding turn-arounds. 
        angle : angle-like, default 0, default unit deg
            Position angle of the box in the native coordinate system. 
        sample_interval : time, default 1/400, default unit s
            Time between read-outs. Must be positive.
        max_scan_duration : time-like, default unit sec
            Maximum total scan time to determine number of repeats. Must be positive. 
            Cannot be used with num_repeat.
        num_repeat : int, default 1 
            Number of repeats of the pattern. Must be >= 1
            Cannot be used with max_scan_duration.
        """

        # pass kwargs
        if param_json is None:
            self.param = self._clean_param(**kwargs)
            self.data = self._generate_scan()

        # pass parameters by json
        else:

            if isinstance(param_json, str):
                with open(param_json, 'r') as f:
                    param = json.load(f)
            elif isinstance(param_json, dict):
                param = param_json
            else:
                raise TypeError('param_json')

            # overwrite any parameters
            if 'max_scan_duration' in kwargs.keys():
                param.pop('num_repeat')

            param.update(kwargs)
            self.param = self._clean_param(**param)

            self.data = self._generate_scan()

    def _clean_param(self, **kwargs):
        kwargs = super()._clean_param(**kwargs)
        kwargs['num_term'] = int(kwargs['num_term'])
        kwargs['width'] = u.Quantity(kwargs['width'], u.deg).value
        kwargs['height'] = u.Quantity(kwargs['height'], u.deg).value
        kwargs['spacing'] = u.Quantity(kwargs['spacing'], u.deg).value
        kwargs['velocity'] = u.Quantity(kwargs['velocity'], u.deg/u.s).value
        kwargs['angle'] = u.Quantity(kwargs.get('angle', 0), u.deg).value
        kwargs['sample_interval'] = u.Quantity(kwargs.get('sample_interval', 1/400), u.s).value
        return kwargs

    def _generate_scan(self):
        
        # unpack parameters
        num_term = self.num_term
        width = self.width.value
        height = self.height.value
        spacing = self.spacing.value
        velocity = self.velocity.value
        sample_interval = self.sample_interval.value

        angle = self.angle.to(u.rad).value

        # --- START OF ALGORITHM ---

        # Determine number of vertices (reflection points) along each side of the
        # box which satisfies the common-factors criterion and the requested size / spacing    

        vert_spacing = sqrt(2)*spacing
        x_numvert = math.ceil(width/vert_spacing)
        y_numvert = math.ceil(height/vert_spacing)
 
        if x_numvert%2 == y_numvert%2:
            if x_numvert >= y_numvert:
                y_numvert += 1
            else:
                x_numvert += 1

        num_vert = [x_numvert, y_numvert]
        most_i = num_vert.index(max(x_numvert, y_numvert))
        least_i = num_vert.index(min(x_numvert, y_numvert))

        while math.gcd(num_vert[most_i], num_vert[least_i]) != 1:
            num_vert[most_i] += 2
        
        x_numvert = num_vert[0]
        y_numvert = num_vert[1]
        assert(math.gcd(x_numvert, y_numvert) == 1)
        assert((x_numvert%2 == 0 and y_numvert%2 == 1) or (x_numvert%2 == 1 and y_numvert%2 == 0))

        # Calculate the approximate periods by assuming a Pong scan with
        # no rounding at the corners. Average the x- and y-velocities
        # in order to determine the period in each direction, and the
        # total time required for the scan.

        vavg = velocity/sqrt(2) # changed so velocity is TOTAL velocity and vavg is single-direction velocity
        peri_x = x_numvert * vert_spacing * 2 / vavg
        peri_y = y_numvert * vert_spacing * 2 / vavg
        period = x_numvert * y_numvert * vert_spacing * 2 / vavg

        pongcount = math.ceil(period/sample_interval)
        amp_x = x_numvert * vert_spacing / 2
        amp_y = y_numvert * vert_spacing / 2
        
        # Calculate the grid positions and apply rotation angle. Load
        # data into a dataframe.    

        t_count = 0
        time_offset = []
        x_coord = []
        y_coord = []

        for i in range(pongcount):
            x_coord1 = self._fourier_expansion(num_term, amp_x, t_count, peri_x)
            y_coord1 = self._fourier_expansion(num_term, amp_y, t_count, peri_y)

            x_coord.append(x_coord1*cos(angle) - y_coord1*sin(angle))
            y_coord.append(x_coord1*sin(angle) + y_coord1*cos(angle))
            time_offset.append(t_count)
            t_count += sample_interval
        
        # repeat pattern if necessary 
        data = pd.DataFrame({
            'time_offset': time_offset, 
            'x_coord': x_coord, 'y_coord': y_coord,
        })

        return self._repeat_scan(data)
    
    def _fourier_expansion(self, num_term, amp, t_count, peri):
        N = num_term*2 - 1
        a = (8*amp)/(pi**2)
        b = 2*pi/peri

        pos = 0
        for n in range(1, N+1, 2):
            c = math.pow(-1, (n-1)/2)/n**2 
            pos += c * sin(b*n*t_count)

        pos *= a
        return pos

class Daisy(SkyPattern):
    """See "CV Daisy - JCMT small area scanning patter" (JCMT TCS/UN/005) for details of implementation."""

    _param_unit = {
        'velocity': u.deg/u.s, 'start_acc': u.deg/u.s/u.s, 
        'R0': u.deg, 'Rt': u.deg, 'Ra': u.deg,
        'T': u.s, 'sample_interval': u.s, 'y_offset': u.deg
    }
    repeatable=False

    def __init__(self, param_json=None, **kwargs) -> None:
        """
        Initialize a daisy pattern by passing a parameter file or dictionary and optionally 
        adding keywords to overwrite existing ones:
            option1 : Daisy(param_json, **kwargs) 
        or building from scratch: 
            option2 : Daisy(**kwargs)

        Parameters
        ---------------------------
        param_json : str or dict
            Contains parameters used to generate pattern. 

        **kwargs
        velocity : angle-like/time-like, default unit deg/s
            Constant velocity (CV) for scan to go at. 
        start_acc : acceleration-like, default unit deg/s^2
            Acceleration at start of pattern.
        R0 : angle-like, default unit deg
            Radius R0. Must be positive.
        Rt : angle-like, default unit deg
            Turn radius. Must be positive.
        Ra : angle-like, default unit deg
            Avoidance radius. Must be non-negative. 
        T : time-like, default unit sec
            Total time of the simulation. Must be postivie. 
        sample_interval : time-like, default 1/400, default unit sec
            Time step. 
        y_offset : angle-like, default 0, default unit deg
            Start offset in y. 
        """

        # pass kwargs
        if param_json is None:
            self.param = self._clean_param(**kwargs)
            self.data = self._generate_scan()

        # pass parameters by json
        else:

            if isinstance(param_json, str):
                with open(param_json, 'r') as f:
                    param = json.load(f)
            elif isinstance(param_json, dict):
                param = param_json
            else:
                raise TypeError('param_json')

            param.update(kwargs)
            self.param = self._clean_param(**param)

            self.data = self._generate_scan()

    def _clean_param(self, **kwargs):
        kwargs['velocity'] = u.Quantity(kwargs['velocity'], u.deg/u.s).value
        kwargs['start_acc'] = u.Quantity(kwargs['start_acc'], u.deg/u.s/u.s).value
        kwargs['R0'] = u.Quantity(kwargs['R0'], u.deg).value
        kwargs['Rt'] = u.Quantity(kwargs['Rt'], u.deg).value
        kwargs['Ra'] = u.Quantity(kwargs['Ra'], u.deg).value
        kwargs['T'] = u.Quantity(kwargs['T'], u.s).value
        kwargs['sample_interval'] = u.Quantity(kwargs.get('sample_interval', 1/400), u.s).value
        kwargs['y_offset'] = u.Quantity(kwargs.get('y_offset', 0), u.deg).value
        return kwargs
        
    def _generate_scan(self):

        # unpack parameters
        speed = self.velocity.to(u.arcsec/u.s).value
        start_acc = self.start_acc.to(u.arcsec/u.s/u.s).value
        R0 = self.R0.to(u.arcsec).value
        Rt = self.Rt.to(u.arcsec).value
        Ra = self.Ra.to(u.arcsec).value
        T = self.T.to(u.s).value
        dt = self.sample_interval.to(u.s).value
        y_offset = self.y_offset.to(u.arcsec).value

        # --- START OF ALGORITHM ---

        # Tangent vector & start value
        (vx, vy) = (1.0, 0.0) 

        # Position vector & start value
        (x, y) = (0.0, y_offset) 

        # number of steps 
        N = int(T/dt)

        # x, y arrays for storage
        x_coord = np.empty(N)
        y_coord = np.empty(N)
        #x_vel = np.empty(N)
        #y_vel = np.empty(N)
        
        # Effective avoidance radius so Ra is not used if Ra > R0 
        #R1 = min(R0, Ra) 

        s0 = speed 
        speed = 0 
        for step in range(N): 

            # Ramp up speed with acceleration start_acc 
            # to limit startup transients. Telescope has zero speed at startup. 
            speed += start_acc*dt 
            if speed >= s0: 
                speed = s0 

            r = sqrt(x*x + y*y) 

            # Straight motion inside R0 
            if r < R0: 
                x += vx*speed*dt 
                y += vy*speed*dt 

            # Motion outside R0
            else: 
                (xn,yn) = (x/r,y/r) # Compute unit radial vector 

                # If aiming close to center, resume straight motion
                # seems to only apply for the initial large turn 
                if (-xn*vx - yn*vy) > sqrt(1 - Ra*Ra/r/r): #if (-xn*vx - yn*vy) > 1/sqrt(1 + (Ra/r)**2):
                    x += vx*speed*dt 
                    y += vy*speed*dt 

                # Otherwise decide turning direction
                else: 
                    if (-xn*vy + yn*vx) > 0: 
                        Nx = vy 
                        Ny = -vx 
                    else: 
                        Nx = -vy 
                        Ny = vx 

                    # Compute curved trajectory using serial exansion in step length s 
                    s = speed*dt 
                    x += (s - s*s*s/Rt/Rt/6)*vx + s*s/Rt/2*Nx 
                    y += (s - s*s*s/Rt/Rt/6)*vy + s*s/Rt/2*Ny 
                    vx += -s*s/Rt/Rt/2*vx + (s/Rt + s*s*s/Rt/Rt/Rt/6)*Nx 
                    vy += -s*s/Rt/Rt/2*vy + (s/Rt + s*s*s/Rt/Rt/Rt/6)*Ny 

            # Store result for plotting and statistics
            x_coord[step] = x
            y_coord[step] = y
            #x_vel[step] = speed*vx
            #y_vel[step] = speed*vy

        """
        ax = -2*xval[1: -1] + xval[0:-2] + xval[2:] # numerical acc in x 
        ay = -2*yval[1: -1] + yval[0:-2] + yval[2:] # numerical acc in y 
        x_acc = np.append(np.array([0]), ax/dt/dt)
        y_acc = np.append(np.array([0]), ay/dt/dt)
        x_acc = np.append(x_acc, 0)
        y_acc = np.append(y_acc, 0)
        """

        return pd.DataFrame({
            'time_offset': np.arange(0, T, dt), 
            'x_coord': x_coord/3600, 'y_coord': y_coord/3600, 
            #'x_vel': x_vel/3600, 'y_vel': y_vel/3600,
        })
 
#######################
#  TELESCOPE PATTERN 
#######################

class TelescopePattern():
    """
    Attributes
    -------------------------------
    instrument
    param: ra, dec, location, (start_datetime or start_hrang or [start_el and moving_up])
    sample_interval
    data: time_offset, lst, alt_coord, az_coord
    """

    _param_unit = {
        'ra': u.deg, 'dec': u.deg, 'location': u.dimensionless_unscaled,
        'start_hrang': u.hourangle, 
        'start_datetime': u.dimensionless_unscaled, 
        'start_lst': u.hourangle,
        'start_el': u.deg, 'moving_up': u.dimensionless_unscaled
    }
    _data_unit = {'time_offset': u.s, 'lst': u.hourangle, 'alt_coord': u.deg, 'az_coord': u.deg}

    # INITIALIZATION

    def __init__(self, data, instrument=None, module='boresight', obs_param=None, **kwargs) -> None:
        """
        Determine the motion of the telescope.
            option1: data, instrument (optional), module (optional), ra, dec, location, (start_datetime or start_hrang or start_lst or [start_el and moving_up])
            option2: data, instrument (optional), module (optional), obs_param = {ra:, dec:, location: {lat:, lon:, height:, }, start_:}, **kwargs for updating 
            option3: instrument, module, data*, location
            * data includes 'lst' (local sidereal time)

        Parameters
        -----------------------------
        data : SkyPattern; str, ndarray, Iterable, dict, or DataFrame
            If SkyPattern, then it is a SkyPattern object with time_offset, ra, dec.
            Otherwise, is a csv file or dict that has columns 'time_offset', 'az_coord', 'alt_coord' and optionally 'lst'.

        instrument : Instrument or None, default None
            instrument object to be used if any
        module : str or (distance, theta), default 'boresight'
            location relative to the center of the instrument where **kwargs is applied:
                'boresight' for boresight of the telescope 
                string indicating a module name in the instrument e.g. 'SFH' or one of the default slots in the instrument e.g. 'c', 'i1'
                tuple of (distance, theta) indicating module's offset from the center of the instrument, default unit deg

        obs_param : str
            File path to json containing all required obervation parameters (see **kwargs).

        **kwargs
        ra : angle-like, default unit deg
            starting right acension / right acension of sky_pattern
        dec : angle-like, default unit deg
            starting declination / declination of sky_pattern
        location : EarthLocation or dict
            if dict, contains {'lat', 'lon', 'height'} with default unit deg

        start_datetime : str or datetime, default timezone UTC
            starting date and time of observation
        start_hrang : angle-like, default unit hourangle
            starting hour angle of observation
        start_lst : angle-like, default unit hourangle
            starting local sidereal time
        start_el : angle-like, default unit deg
            starting elevation of obervation, must be used with moving_up
        moving_up : bool, default True
            whether observation is moving towards the meridian or away, must be used with start_el 
        """

        # --- Observation Parameters ---

        # pass by obs_param
        if not obs_param is None:

            with open(obs_param, 'r') as f:
                param = json.load(f)

            # overwrite parameters FIXME start_
            param.update(kwargs)
            self.param = self._clean_param(**param)
        
        # pass by kwargs
        else:
            self.param = self._clean_param(**kwargs)

        # --- SkyPattern or data ---

        # passed data
        if not isinstance(data, SkyPattern):
            if isinstance(data, str):
                try:
                    self.data = pd.read_csv(data, index_col=False, usecols=['time_offset', 'lst', 'az_coord', 'alt_coord'])
                except ValueError:
                    self.data = pd.read_csv(data, index_col=False, usecols=['time_offset', 'az_coord', 'alt_coord'])
                    self.data['lst'] = self._get_lst()
            else:
                try:
                    self.data = pd.DataFrame(data, columns=['time_offset', 'lst', 'az_coord', 'alt_coord'])
                except ValueError:
                    self.data = pd.DataFrame(data, columns=['time_offset', 'az_coord', 'alt_coord'])
                    self.data['lst'] = self._get_lst()
            
            # determine sample_interval 
            sample_interval_list = np.diff(self.data.time_offset)
            if np.std(sample_interval_list)/np.mean(sample_interval_list) <= 0.01:
                sample_interval = np.mean(sample_interval_list)
                self.sample_interval = sample_interval
            else:
                raise ValueError('sample_interval must be constant')

        # passed sky_pattern
        else:
            self.sample_interval = data.sample_interval.value

            self.data=pd.DataFrame({'time_offset':data.time_offset})
            self.data['lst'] = self._get_lst(data)
            az1, alt1 = self._from_sky_pattern(data)

            self.data['az_coord'] = az1
            self.data['alt_coord'] = alt1

        # --- Instrument and module --- 

        self.instrument = instrument
        dist, theta = self._true_module_loc(module)
        
        # az_coord and alt_coord are for the module's location
        # we need the az/alt coordinates of the boresight

        if not (module == 'boresight' or (math.isclose(dist, 0) and math.isclose(theta, 0))):
            az0, alt0 = self._transform_to_boresight(self.data['az_coord'].to_numpy(), self.data['alt_coord'].to_numpy(), dist, theta)
            self.data['az_coord'] = az0
            self.data['alt_coord'] = alt0
        else:
            self.data['alt_coord'] = self.alt_coord.value%360
            self.data['az_coord'] = self._norm_angle(self.az_coord.value)

    def _clean_param(self, **kwargs):
        kwarg_keys = kwargs.keys()

        if 'ra' in kwarg_keys:
            kwargs['ra'] = u.Quantity(kwargs['ra'], u.deg).value
        if 'dec' in kwarg_keys:
            kwargs['dec'] = u.Quantity(kwargs['dec'], u.deg).value

        location = kwargs.get('location', FYST_LOC)
        if not isinstance(location, EarthLocation):
            lat = u.Quantity(location['lat'], u.deg).value
            lon = u.Quantity(location['lon'], u.deg).value
            height = u.Quantity(location['height'], u.m).value
            location = EarthLocation(lat=lat, lon=lon, height=height)
        kwargs['location'] = location

        if 'start_hrang' in kwarg_keys:
            kwargs['start_hrang'] = u.Quantity(kwargs['start_hrang'], u.hourangle).value
        elif 'start_datetime' in kwarg_keys:
            kwargs['start_datetime'] = pd.Timestamp(kwargs['start_datetime']).to_pydatetime()
        elif 'start_lst' in kwarg_keys:
            kwargs['start_lst'] = u.Quantity(kwargs['start_lst'], u.hourangle).value
        elif 'start_el' in kwarg_keys:
            kwargs['start_el'] = u.Quantity(kwargs['start_el'], u.deg).value
            kwargs['moving_up'] = kwargs.get('moving_up', True)

        return kwargs

    def _get_lst(self, sky_pattern=None):

        if not sky_pattern is None:
            extra_ra_offset = sky_pattern.x_coord[0]
            extra_dec_offset = sky_pattern.y_coord[0]
        else:
            extra_ra_offset = 0*u.deg
            extra_dec_offset = 0*u.deg

        # given a starting datetime
        if 'start_datetime' in self.param.keys():
            start_datetime = Time(self.start_datetime, location=self.location)
            start_lst = start_datetime.sidereal_time('apparent')

        # given a starting hourangle
        elif 'start_hrang' in self.param.keys():
            # FIXME check for valid hourangle
            start_lst = self.start_hrang + extra_ra_offset + self.ra
        
        # given a starting lst
        elif 'start_lst' in self.param.keys():
            start_lst = self.start_lst

        # given a starting elevation
        elif 'start_el' in self.param.keys():

            # determine possible hour angles
            alt_rad = self.start_el.to(u.rad).value
            dec_rad = (self.dec + extra_dec_offset).to(u.rad).value
            lat_rad = self.location.lat.rad

            try:
                start_hrang_rad = math.acos((sin(alt_rad) - sin(dec_rad)*sin(lat_rad)) / (cos(dec_rad)*cos(lat_rad)))
            except ValueError as e:
                raise ValueError('Altitude is not possible at provided ra, dec, and latitude.') from e
                # FIXME list range of possible altitudes

            # choose hour angle

            def altitude(dec, lat, ha):
                sin_alt = sin(dec)*sin(lat) + cos(dec)*cos(lat)*cos(ha)
                return math.asin(sin_alt)

            start_hrang_rad1 = (start_hrang_rad*u.rad + 1*u.deg).to(u.rad).value
            ha1_delta = altitude(dec_rad, lat_rad, start_hrang_rad1) - altitude(dec_rad, lat_rad, start_hrang_rad)
            ha1_up = True if ha1_delta > 0 else False

            start_hrang_rad2 = (-start_hrang_rad*u.rad + 1*u.deg).to(u.rad).value
            ha2_delta = altitude(dec_rad, lat_rad, start_hrang_rad2) - altitude(dec_rad, lat_rad, -start_hrang_rad)
            ha2_up = True if ha2_delta > 0 else False
            assert(ha1_up != ha2_up)

            if (self.moving_up and ha2_up) or (not self.moving_up and ha1_up):
                start_hrang_rad = -start_hrang_rad

            # starting sidereal time
            start_lst = start_hrang_rad*u.rad + extra_ra_offset + self.ra
        
        else:
            raise TypeError('start_datetime or start_hrang or start_lst or start_el is required')

        # find sidereal time
        SIDEREAL_TO_UT1 = 1.002737909350795
        return (self.time_offset.value/3600*SIDEREAL_TO_UT1*u.hourangle + start_lst).to(u.hourangle).value

    def _from_sky_pattern(self, sky_pattern):

        # get alt/az
        hour_angle = self.lst - (sky_pattern.x_coord + self.ra)

        hour_angle_rad = hour_angle.to(u.rad).value
        dec_rad = (sky_pattern.y_coord + self.dec).to(u.rad).value
        lat_rad = self.location.lat.rad

        alt_rad = np.arcsin( np.sin(dec_rad)*sin(lat_rad) + np.cos(dec_rad)*cos(lat_rad)*np.cos(hour_angle_rad) )

        cos_az_rad = (np.sin(dec_rad) - np.sin(alt_rad)*sin(lat_rad)) / (np.cos(alt_rad)*cos(lat_rad))
        cos_az_rad[cos_az_rad > 1] = 1
        cos_az_rad[cos_az_rad < -1] = -1

        az_rad = np.arccos( cos_az_rad )
        mask = np.sin(hour_angle_rad) > 0 
        az_rad[mask] = 2*pi - az_rad[mask]

        return np.degrees(az_rad), np.degrees(alt_rad)

    # TRANSFORMATIONS

    def _norm_angle(self, az):
        # normalize azimuth values so that:
        # 1. starting azimuth is between 0 and 360
        # 2. azmiuth values are between start-180 to start+180 (centered around the start)
        # formula = ((value - low) % diff) + low 

        lowest_az = az[0]%360 - 180
        return (az - lowest_az)%(360) + lowest_az 

    def _true_module_loc(self, module):
        """ Gets the (dist, theta) of the module from the boresight (not necessarily central tube)"""

        if module == 'boresight':
            return 0, 0

        # passed by module identifier or instrument slot name
        if isinstance(module, str):
            try:
                module = self.instrument.get_location(module)
            except ValueError:
                try:
                    module = self.instrument.slots[module]*u.deg
                except KeyError:
                    raise ValueError(f'{module} is not an existing module name or instrument slot')
        else:
            module = [u.Quantity(module[0], u.deg), u.Quantity(module[1], u.deg)]

        dist = module[0].value
        theta = module[1].to(u.rad).value

        # instrument rotation and offset
        instr_x = self.instrument.instr_offset[0].value
        instr_y = self.instrument.instr_offset[1].value
        instr_rot = self.instrument.instr_rot.to(u.rad).value

        # get true module location in terms of x and y
        mod_x = dist*cos(theta)
        mod_y = dist*sin(theta)

        x_offset = mod_x*cos(instr_rot) - mod_y*sin(instr_rot) + instr_x
        y_offset = mod_x*sin(instr_rot) + mod_y*cos(instr_rot) + instr_y

        new_dist = sqrt(x_offset**2 + y_offset**2)
        new_theta = math.degrees(math.atan2(y_offset, x_offset))

        return new_dist, new_theta

    def _transform_to_boresight(self, az1, alt1, dist, theta):

        # convert everything into radians
        dist = math.radians(dist)
        theta = math.radians(theta)
        alt1 = np.radians(alt1)
        az1 = np.radians(az1)

        # getting new elevation
        def func(alt_0, alt_1):
            return sin(alt_0)*cos(dist) + sin(dist)*cos(alt_0)*sin(theta + alt_0) - sin(alt_1)

        alt0 = np.empty(len(alt1))
        guess = alt1[0]
        for i, a1 in enumerate(alt1):
            try:
                a0 = root_scalar(func, args=(a1), x0=guess, bracket=[-pi/2, pi/2], xtol=10**(-6)).root
                guess = a0
            except ValueError:
                print(f'nan value at {i}')
                alt0 = math.nan

            alt0[i]= a0

        # getting new azimuth
        #cos_diff_az0 = ( np.cos(alt0)*cos(dist) - np.sin(alt0)*sin(dist)*np.sin(theta + alt0) )/np.cos(alt1)
        cos_diff_az0 = (cos(dist) - np.sin(alt0)*np.sin(alt1))/(np.cos(alt0)*np.cos(alt1))
        cos_diff_az0[cos_diff_az0 > 1] = 1
        cos_diff_az0[cos_diff_az0 < -1] = -1
        diff_az0 = np.arccos(cos_diff_az0)

        # check if diff_az is positive or negative
        mask = (theta > -alt0 + pi/2) & (theta < -alt0 + 3*pi/2)
        diff_az0[mask] = -diff_az0[mask]
        az0 = az1 - diff_az0

        """# check is dist is dist
        beta = np.arcsin( np.cos(theta + alt0)*np.cos(alt0)/np.cos(alt1) )
        alpha = pi/2 - beta + theta + alt0
        dist_check = np.degrees(np.arcsin( np.cos(alt1)*np.sin(alpha)/np.cos(theta + alt0)  ))
        plt.plot(dist_check)"""

        return self._norm_angle(np.degrees(az0)), np.degrees(alt0)%360

    def _transform_from_boresight(self, az0, alt0, dist, theta):
        
        # convert everything into radians
        dist = math.radians(dist)
        theta = math.radians(theta)
        alt0 = np.radians(alt0)
        az0 = np.radians(az0)

        # find elevation offset
        alt1 = np.arcsin(np.sin(alt0)*cos(dist) + sin(dist)*np.cos(alt0)*np.sin(theta + alt0))

        # find azimuth offset
        sin_az1 = 1/np.cos(alt1) * ( np.cos(alt0)*np.sin(az0)*cos(dist) + np.cos(az0)*np.cos(theta + alt0)*sin(dist) - np.sin(alt0)*np.sin(az0)*sin(dist)*np.sin(theta + alt0) )
        cos_az1 = 1/np.cos(alt1) * ( np.cos(alt0)*np.cos(az0)*cos(dist) - np.sin(az0)*np.cos(theta + alt0)*sin(dist) - np.sin(alt0)*np.cos(az0)*sin(dist)*np.sin(theta + alt0) )
        az1 = np.arctan2(sin_az1, cos_az1)

        return self._norm_angle(np.degrees(az1)), np.degrees(alt1)%360

    def view_module(self, module):
        """
        Parameters
        ------------------------
        module : str or (distance, theta)
            string indicating a module name in the instrument e.g. 'SFH'
            string indicating one of the default slots in the instrument e.g. 'c', 'i1'
            tuple of (distance, theta) indicating module's offset from the center of the instrument

        Returns
        -------------------------
        TelescopePattern 
            a TelescopePattern object where the "boresight" is the path of the provided module
        """

        dist, theta = self._true_module_loc(module)
        az1, alt1 = self._transform_from_boresight(self.az_coord.value, self.alt_coord.value, dist, theta)

        data = {'time_offset': self.time_offset.value, 'lst': self.lst.value, 'az_coord': az1, 'alt_coord': alt1}

        return TelescopePattern(data=data, location=self.location)

    def get_sky_pattern(self) -> SkyPattern:
        """
        Returns
        -------------------------
        SkyPattern
            A SkyPattern object tracing the path of the boresight.
        """

        data = {
            'time_offset': self.time_offset.value, 
            'x_coord': self.ra_coord.value - self.ra_coord[0].value,
            'y_coord': self.dec_coord.value - self.dec_coord[0].value
        }
        return SkyPattern(data=data)

    # SAVING/EXTRACTING DATA

    def save_param(self, param_json=None):
        """
        Parameters
        ----------------------------
        param_json : str or False
            path to intended file location for the parametes
            if None, return it as a dictionary
        
        Returns
        ----------------------
        None or dict
            If path_or_buf is None, returns the resulting json format as a dictionary. Otherwise returns None.
        """

        param_temp = self.param.copy()
        location = param_temp['location']
        param_temp['location'] = {'lat': location.lat.deg, 'lon': location.lon.deg, 'height': location.height.value}

        # save param_json
        if param_json is None:
            return param_temp
        else:
            with open(param_json, 'w') as f:
                json.dump(param_temp, f)

    def save_data(self, path_or_buf=None, columns='default'):
        """
        Save kinematics data of the boresight. 

        Parameters
        ----------------------------
        path_or_buf : str or file handle, default None
            File path or object, if None is provided the result is returned as a dictionary.
        columns : sequence or str, default 'default'
            Columns to write. 
            'default' for ['time_offset', 'lst', 'az_coord', 'alt_coord', 'az_vel', 'alt_vel']
            'all' for ['time_offset', 'az_coord', 'alt_coord', 'az_vel', 'alt_vel', 'vel', 'az_acc', 'alt_acc', 'acc', 'az_jerk', 'alt_jerk', 'jerk', 'lst', 'hour_angle', 'para_angle', 'rot_angle', 'ra_coord', 'dec_coord']
        
        Returns
        ----------------------
        None or dict
            If path_or_buf is None, returns the resulting json format as a dictionary. Otherwise returns None.
        """

        # replace str options
        if columns == 'default':
            columns = ['time_offset', 'lst', 'az_coord', 'alt_coord', 'az_vel', 'alt_vel']
        elif columns == 'all':
            columns = ['time_offset', 'az_coord', 'alt_coord', 'az_vel', 'alt_vel', 'vel', 'az_acc', 'alt_acc', 'acc', 'az_jerk', 'alt_jerk', 'jerk', 'lst', 'hour_angle', 'para_angle', 'rot_angle', 'ra_coord', 'dec_coord']
        
        # generate required data
        data = self.data.copy()
        for col in columns:
            if not col in ['time_offset', 'lst', 'az_coord', 'alt_coord']:
                data[col] = getattr(self, col).value
        
        # save data file 
        if path_or_buf is None:
            return data[columns].to_dict('list')
        else:
            data.to_csv(path_or_buf, columns=columns, index=False)

    # ATTRIBUTES

    def __getattr__(self, attr):

        if attr in self.param.keys():
            if self._param_unit[attr] is u.dimensionless_unscaled:
                return self.param[attr]
            else:
                return self.param[attr]*self._param_unit[attr]
        elif attr in self.data.columns:
            return self.data[attr].to_numpy()*self._data_unit[attr]
        else:
            raise AttributeError(f'attribtue {attr} not found')
    
    @property
    def dec_coord(self):
        lat_rad = self.location.lat.rad
        alt_coord_rad = self.alt_coord.to(u.rad).value
        az_coord_rad = self.az_coord.to(u.rad).value

        dec_rad = np.arcsin( sin(lat_rad)*np.sin(alt_coord_rad) + cos(lat_rad)*np.cos(alt_coord_rad)*np.cos(az_coord_rad) )
        return self._norm_angle(np.degrees(dec_rad))*u.deg

    @property
    def hour_angle(self):
        lat_rad = self.location.lat.rad
        alt_coord_rad = self.alt_coord.to(u.rad).value
        az_coord_rad = self.az_coord.to(u.rad).value
        dec_rad = self.dec_coord.to(u.rad).value

        hrang_rad = np.arccos( (np.sin(alt_coord_rad) - np.sin(dec_rad)*sin(lat_rad)) / (np.cos(dec_rad)*cos(lat_rad)) )
        
        mask = np.sin(az_coord_rad) > 0
        hrang_rad[mask] = 2*pi - hrang_rad[mask]

        return (hrang_rad*u.rad).to(u.hourangle)

    @property
    def ra_coord(self):
        return self._norm_angle((self.lst - self.hour_angle).to(u.deg).value)*u.deg

    @property
    def para_angle(self):
        dec_rad = self.dec_coord.to(u.rad).value
        hour_angle_rad = self.hour_angle.to(u.rad).value
        lat_rad = self.location.lat.rad

        para_angle_deg = np.degrees(np.arctan2( 
            np.sin(hour_angle_rad), 
            np.cos(dec_rad)*tan(lat_rad) - np.sin(dec_rad)*np.cos(hour_angle_rad) 
        ))
        return self._norm_angle(para_angle_deg)*u.deg

    @property
    def rot_angle(self):
        return self._norm_angle((self.para_angle + self.alt_coord).value)*u.deg

    @property
    def az_vel(self):
        return _central_diff(self.az_coord.value, self.sample_interval)*u.deg/u.s

    @property
    def alt_vel(self):
        return _central_diff(self.alt_coord.value, self.sample_interval)*u.deg/u.s

    @property
    def vel(self):
        return np.sqrt(self.az_vel**2 + self.alt_vel**2)

    @property
    def az_acc(self):
        return _central_diff(self.az_vel.value, self.sample_interval)*u.deg/u.s/u.s

    @property
    def alt_acc(self):
        return _central_diff(self.alt_vel.value, self.sample_interval)*u.deg/u.s/u.s
    
    @property
    def acc(self):
        return np.sqrt(self.az_acc**2 + self.alt_acc**2)

    @property
    def az_jerk(self):
        return _central_diff(self.az_acc.value, self.sample_interval)*u.deg/(u.s)**3
    
    @property
    def alt_jerk(self):
        return _central_diff(self.alt_acc.value, self.sample_interval)*u.deg/(u.s)**3
    
    @property
    def jerk(self):
        return np.sqrt(self.az_jerk**2 + self.alt_jerk**2)