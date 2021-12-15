# imports
import math
import json
import warnings

import numpy as np
import pandas as pd
from scipy.constants import speed_of_light
import astropy.units as u

""" 
- what if polarization is in alternate direction?
"""

#####################
#   CAMERA MODULE
#####################

class Module():
    """
    Class for a single camera module (e.g. EoRSpec, CMBPol, SFH). Each module 
    consists of three wafers/detector arrays. Each wafter contains three rhombuses. 

    Attributes
    ------------------
    x : ndarray in astropy.units.Quantity (deg)
        x offsets of detector pixel positions.
    y : ndarray in astropy.units.Quantity (deg)
        y offsets of detector pixel positions.

    """

    _data_unit = {'x': u.deg, 'y': u.deg, 'pol': u.deg, 'rhombus': u.dimensionless_unscaled, 'wafer': u.dimensionless_unscaled, 'pixel_num': u.dimensionless_unscaled}

    def __init__(self, data=None, **kwargs) -> None:
        """
        Create a camera module either through:
            | option1 : Module(data)
            | option2 : Module(freq=, F_lambda=)
            | option3 : Module(wavelength=, F_lambda=)

        Parameters
        --------------------
        data : str; dict or pandas.DataFrame
            If str, a file path to a csv file. 
            Must have columns: x, y (deg). Recommended to have columns: pol (deg), rhombus, and wafer. 
        
        Keyword Arguments
        -------------------
        freq : float or sequence; default unit GHz
            Center of frequency band.
            If each wafer is different (such as EoRSpec), pass a three-length list like [freq1, freq2, freq3].
        wavelength : float or sequence; default unit micron
            Intended wavelength of light.
            If each wafer is different (such as EoRSpec), pass a three-length list like [wavelength1, wavelength2, wavelength3].
        F_lambda : float; default 1.2
            Factor for spacing between individual detectors.
        """

        # -- OPTION 1 --
        if not data is None:

            # using an existing Module object 
            if isinstance(data, str):
                self._data = pd.read_csv(data, index_col=False)
            # passing a dictionary (likely from Instrument class)
            else:
                self._data = pd.DataFrame(data)

            # check for certain columns inside

            for col in ['pol', 'rhombus', 'wafer']:
                if not col in self._data.columns:
                    warnings.warn(f'column {col} not in data, marking all columns values for {col} as 0')
                    self._data[col] = 0

            if not 'pixel_num' in self._data.columns:
                self._data['pixel_num'] = self._data.index
            
            data_columns = ['pixel_num', 'x', 'y', 'pol', 'rhombus', 'wafer']
            self._data = self._data[data_columns]
            self._ang_res = self._find_ang_res()

        # -- OPTION 2 --
        else:

            # check F_lambda
            F_lambda = kwargs.pop('F_lambda', 1.2)
            if F_lambda <= 0:
                raise ValueError(f'F_lambda = {F_lambda} must be positive')

            # get freq
            if 'freq' in kwargs.keys():
                freq = u.Quantity(kwargs.pop('freq'), u.Hz*10**9).value
            elif 'wavelength' in kwargs.keys():
                wavelength = u.Quantity(kwargs.pop('wavelength'), u.micron).to(u.m).value
                freq = speed_of_light/wavelength/10**9
            else:
                raise ValueError('cannot create Module without one of file, freq, or wavelength')

            if kwargs:
                raise ValueError(f'unneccary keywords passed: {kwargs}')

            self._ang_res, self._data = self._generate_module(freq, F_lambda)        

    # INITIALIZATION    

    def _find_ang_res(self):
        ang_res = []
        for wafer in np.unique(self._data['wafer']):
            temp_dict = self._data[self._data['wafer'] == wafer].iloc[0:2].loc[:, ['x', 'y']].to_dict('list')
            ang_res.append( math.sqrt( (temp_dict['x'][0] - temp_dict['x'][1])**2 + (temp_dict['y'][0] - temp_dict['y'][1])**2 ) )
        
        if math.isclose(ang_res[0], ang_res[1]) and math.isclose(ang_res[0], ang_res[2]):
            return ang_res[0]
        else:
            return ang_res

    def _waferpixelpos(self, p, numrows, numcols, numrhombus, centeroffset):
        """Obtains pixel positions in a wafer, origin centered at wafer center"""

        theta_axes = 2*np.pi/numrhombus # 120 degree offset between the row and column axes of each rhombus
        numpixels = numrows*numcols*numrhombus # number of total pixels on a detector wafer
        pixelpos = np.zeros((numpixels, 4)) # array for storing all pixel x and y coordinates, polarizations, and rhombus
        count = 0 # counter for pixel assignment to rows in the pixelpos array
        rhombusaxisarr = np.arange(0, 2*np.pi, theta_axes) # the 3 rhombus axes angles when drawn from the center of detector

        # Calculate pixel positions individually in a nested loop
        # Note there are more efficient ways of doing this, but nested for loops is probably most flexible for changes
        for i, pol in zip( range(numrhombus), ((45, 0), (-45, 60), (45, 30)) ):

            # convert polarizations to deg
            pm = pol[0]
            pc = pol[1]

            # For each rhombus, determine the angle that it is rotated about the origin,
            # and the position of the pixel nearest to the origin
            rhombusaxis = rhombusaxisarr[i]
            x0 = centeroffset*np.cos(rhombusaxis)
            y0 = centeroffset*np.sin(rhombusaxis)

            # Inside each rhombus iterate through each pixel by deterimining the row position,
            # and then counting 24 pixels by column along each row
            for row in np.arange(numrows):
                xrowstart = x0 + row * p*np.cos(rhombusaxis-theta_axes/2)
                yrowstart = y0 + row * p*np.sin(rhombusaxis-theta_axes/2)
                for col in np.arange(numcols):
                    x = xrowstart + col * p*np.cos(rhombusaxis+theta_axes/2)
                    y = yrowstart + col * p*np.sin(rhombusaxis+theta_axes/2)
                    pixelpos[count, :] = x, y, (count%2)*pm + pc, i
                    count = count + 1

        return pixelpos

    def _generate_module(self, center_freq, F_lambda=1.2):
        """
        Generates the pixel positions of a module centered at a particular frequency, based 
        off of code from the eor_spec_models package. The numerical values in the code are
        based off of the parameters for a detector array centered at 280 GHz. 
        """

        # --- SETUP ---

        # λ/D in rad (D = 6m, diameter of the telescope)

        if isinstance(center_freq, int) or isinstance(center_freq, float):
            center1 = center2 = center3 = center_freq
            ang_res = ang_res1 = ang_res2 = ang_res3 = F_lambda*math.degrees((3*10**8)/(center_freq*10**9)/6)
        elif len(center_freq) == 3:
            center1 = center_freq[0]
            center2 = center_freq[1]
            center3 = center_freq[2]

            ang_res1 = F_lambda*math.degrees((3*10**8)/(center1*10**9)/6)
            ang_res2 = F_lambda*math.degrees((3*10**8)/(center2*10**9)/6)
            ang_res3 = F_lambda*math.degrees((3*10**8)/(center3*10**9)/6)
            ang_res = [ang_res1, ang_res2, ang_res3]
        else:
            raise ValueError(f'freq {center_freq} is invalid')

        # Each detector wafer is 72mm from the center of the focal plane
        # Let wafer 1 be shifted in +x by 72mm,
        # and wafer 2 and 3 be rotated to 120, 240 degrees from the x-axis respectively

        waferoffset = 72*10**-3 # distance from focal plane center to wafer center
        waferangles = [0, 2*np.pi/3, 4*np.pi/3] # the wafer angle offset from the x-axis

        # Wafer 1 
        ratio1 = 280/center1
        p1 = 2.75*10**-3 * ratio1 # pixel spacing (pitch)
        numrows1 = int(24 /ratio1) # number of rows in a rhombus
        numcols1 = int(24 /ratio1) # number of columns in a rhombus
        numrhombus1 = 3 # number of rhombuses on a detector wafer
        pixeloffset1 = 1.5*2.75*10**-3 # distance of nearest pixel from center of the wafer
        numpixels1 = numrows1*numcols1*numrhombus1 # number of total pixels on a detector wafer

        # Wafer 2
        ratio2 = 280/center2
        p2 = 2.75*10**-3 *ratio2 
        numrows2 = int(24 /ratio2) 
        numcols2 = int(24 /ratio2) 
        numrhombus2 = 3 
        pixeloffset2 = 1.5*2.75*10**-3 
        numpixels2 = numrows2*numcols2*numrhombus2

        # Wafer 3
        ratio3 = 280/center3
        p3 = 2.75*10**-3 *ratio3 
        numrows3 = int(24 /ratio3) 
        numcols3 = int(24 /ratio3) 
        numrhombus3 = 3 
        pixeloffset3 = 1.5*2.75*10**-3 
        numpixels3 = numrows3*numcols3*numrhombus3

        # --- DETECTOR PLANE PIXEL POSITIONS ---

        # Obtain pixel coordinates for a wafer with above parameters
        pixelcoords1 = self._waferpixelpos(p1,numrows1,numcols1,numrhombus1,pixeloffset1)
        pixelcoords2 = self._waferpixelpos(p2,numrows2,numcols2,numrhombus2,pixeloffset2)
        pixelcoords3 = self._waferpixelpos(p3,numrows3,numcols3,numrhombus3,pixeloffset3)
        
        ### Detector Array 1

        # wafer center coordinate, relative to center of the detector
        offsetarray1 = [waferoffset*np.cos(waferangles[0]), waferoffset*np.sin(waferangles[0])]

        # pixel coordinates, relative to center of the detector
        pixelcoords1[:,0] = pixelcoords1[:,0] + offsetarray1[0]
        pixelcoords1[:,1] = pixelcoords1[:,1] + offsetarray1[1]

        ### Detector Array 2
        offsetarray2 = [waferoffset*np.cos(waferangles[1]), waferoffset*np.sin(waferangles[1])]
        pixelcoords2[:,0] = pixelcoords2[:,0] + offsetarray2[0]
        pixelcoords2[:,1] = pixelcoords2[:,1] + offsetarray2[1]

        ### Detector Array 3
        offsetarray3 = [waferoffset*np.cos(waferangles[2]), waferoffset*np.sin(waferangles[2])]
        pixelcoords3[:,0] = pixelcoords3[:,0] + offsetarray3[0]
        pixelcoords3[:,1] = pixelcoords3[:,1] + offsetarray3[1]

        # --- CLEAN UP ---

        # turn to deg 
        pixelcoords1[: , 0] = pixelcoords1[: , 0]/p1*ang_res1
        pixelcoords2[: , 0] = pixelcoords2[: , 0]/p2*ang_res2
        pixelcoords3[: , 0] = pixelcoords3[: , 0]/p3*ang_res3

        pixelcoords1[: , 1] = pixelcoords1[: , 1]/p1*ang_res1
        pixelcoords2[: , 1] = pixelcoords2[: , 1]/p2*ang_res2
        pixelcoords3[: , 1] = pixelcoords3[: , 1]/p3*ang_res3

        # mark rhombuses
        pixelcoords2[:, 3] = pixelcoords2[:, 3] + 3
        pixelcoords3[:, 3] = pixelcoords3[:, 3] + 6

        # mark wafers
        pixelcoords1 = np.hstack( (pixelcoords1, [[0]]*numpixels1) )
        pixelcoords2 = np.hstack( (pixelcoords2, [[1]]*numpixels2) )
        pixelcoords3 = np.hstack( (pixelcoords3, [[2]]*numpixels3) )

        # save to data frame 
        data = pd.DataFrame(
            np.append(np.append(pixelcoords1, pixelcoords2, axis=0), pixelcoords3, axis=0), 
            columns=['x', 'y', 'pol', 'rhombus', 'wafer']
        ).astype({'pol': np.int16, 'rhombus': np.uint8, 'wafer': np.uint8})
        data['pixel_num'] = data.index

        return ang_res, data

    # HELD DATA

    def save_data(self, path_or_buf=None, columns='all'):
        """
        Write Module object to csv file.

        Parameters
        ----------------------
        path_or_buf : str, file handle or None; default None
            File path or object, if None is provided the result is returned as a dictionary.
        columns : sequence or str, default 'all'
            Columns to write. 
            'all' is ['pixel_num', 'x', 'y', 'pol', 'rhombus', 'wafer']

        Returns
        ----------------------
        None or dict
            If path_or_buf is None, returns the resulting csv format as a dictionary. Otherwise returns None.
        """

        # checking columns
        if columns == 'all':
            columns = ['pixel_num', 'x', 'y', 'pol', 'rhombus', 'wafer']
        
        # write to path_or_buf
        if path_or_buf is None:
            return self._data[columns].to_dict('list')
        else:
            self._data.to_csv(path_or_buf, columns=columns, index=False)

    # ATTRIBUTES

    # data : x, y, pol, rhombus, wafer
    def __getattr__(self, attr):
        if attr in self._data.columns:
            if self._data_unit[attr] is u.dimensionless_unscaled:
                return self._data[attr].to_numpy()
            else:
                return self._data[attr].to_numpy()*self._data_unit[attr]
        else:
            raise AttributeError(f'invalid attribute {attr}')

    @property
    def ang_res(self):
        """
        (astropy.units.Quantity (deg) or list): Angular resolution, if multiple frequencies or wavelengths were provided, this will be a three-length sequence.  
        """
        return self._ang_res*u.deg
    

# some standard modules 
CMBPol = Module(freq=350)
SFH = Module(freq=860)
EoRSpec = Module(freq=[262.5, 262.5, 367.5])
Mod280 = Module(freq=280)

#######################
#     INSTRUMENT
#######################

class Instrument():
    """
    A configurable instrument that holds modules. 
    """

    slots = dict()

    def __init__(self, data=None, instr_offset=(0, 0), instr_rot=0) -> None:
        """
        Initialize a filled Instrument:
            option 1: Instrument(data) 
        or an empty Intrument:
            option 2: Instrument(instr_offset, instr_rot)

        Parameters
        -----------------------------
        data : str or dict
            File path to json file or dict object. Overwrites instr_offset and instr_rot. In degrees unit. 
        instr_offset : (angle-like, angle-like), default (0, 0), default unit deg
            offset of the instrument from the boresight
        instr_rot : angle-like, default 0, default unit deg
            CCW rotation of the instrument
        """

        # config file is passed
        if not data is None:

            if isinstance(data, str):
                with open(data, 'r') as f:
                    config = json.load(f)
            elif isinstance(data, dict):
                config = data
            else:
                TypeError('data')

            self._instr_offset = config['instr_offset']
            self._instr_rot = config['instr_rot']

            # populate modules
            self._modules = dict()
            for identifier in config['modules'].keys():
                self._modules[identifier] = {prop: config['modules'][identifier].pop(prop) for prop in ('dist', 'theta', 'mod_rot')}
                self._modules[identifier]['module'] = Module(config['modules'][identifier])

        # empty instrument
        else:
            self._instr_offset = u.Quantity(instr_offset, u.deg).value
            self._instr_rot = u.Quantity(instr_rot, u.deg).value
            
            # initialize empty dictionary of module objects 
            self._modules = dict()
    
    def __repr__(self) -> str:
        instr_repr = f'instrument: offset {self.instr_offset}, rotation {self.instr_rot}\n------------------------------------'

        if len(self._modules) == 0:
            instr_repr += '\nempty'
        else:
            for identifier in self._modules.keys():
                instr_repr +=  "\n" + f"{identifier} \n (r, theta) = {(self._modules[identifier]['dist'], self._modules[identifier]['theta'])}, rotation = {self._modules[identifier]['mod_rot']}"
        
        return instr_repr

    def _check_identifier(func):
        def wrapper(self, identifier, *args, **kwargs):
            if not identifier in self._modules.keys():
                raise ValueError(f'identifier {identifier} is not valid')
            return func(self, identifier, *args, **kwargs)
        return wrapper

    # CHANGING INSTRUMENT CONFIGURATION

    def add_module(self, module, location, mod_rot=0, identifier=None) -> None:
        """
        Add a module.

        Parameters
        -------------------------
        module : Module or str
            A Module object or one of the default options ['CMBPol', 'SFH', 'EoRSpec', 'Mod280']
        location : (distance, theta) or str, default unit deg
            A tuple containing the module location from the center in polar coordinates (deg)
            or one of the default options ['c', 'i1', 'i2', 'o1', 'o2', etc] (see Ebina 2021 for picture)
        mod_rot : deg, default 0, default unit deg
            CCW rotation of the module
        idenitifier : str or None
            Name of the module. 
            If user chose a default module option, then this identifier will be its corresponging name unless otherwise specified. 
        """

        # if a default option of module was chosen
        if isinstance(module, str):
            if identifier is None:
                identifier = module

            if module == 'CMBPol':
                module = CMBPol
            elif module == 'SFH':
                module = SFH
            elif module == 'EoRSpec':
                module = EoRSpec
            elif module == 'Mod280':
                module = Mod280
            else:
                raise ValueError(f'module {module} is not a valid option')

        elif not isinstance(identifier, str):
            raise ValueError('Identifier string must be passed')

        # if a default option for location was chosen
        if isinstance(location, str):
            location = self.slots[location]
        else:
            location = u.Quantity(location, u.deg).value

        # change module rotation
        mod_rot = u.Quantity(mod_rot, u.deg).value
        
        # if identifier is already a module that's saved
        if identifier in self._modules.keys():
            warnings.warn(f'Module {identifier} already exists. Overwriting it...')

        self._modules[identifier] = {'module': module, 'dist': location[0], 'theta': location[1], 'mod_rot': mod_rot}

    @_check_identifier
    def change_module(self, identifier, new_location=None, new_mod_rot=None, new_identifier=None) -> None:
        """
        Change a module.

        Parameters
        -------------------------
        idenitifier : str
            Name of the module to change. 
        new_location : (distance, theta) or str, default unit deg, optional
            A tuple containing the module location from the center in polar coordinates (deg)
            or one of the default options ['c', 'i1', 'i2', 'o1', 'o2', etc] (see Ebina 2021 for picture)
        new_mod_rot : deg, default unit deg, optional
            CCW rotation of the module
        new_identifier : str, optional
            New name of the module. 
        """
    
        if new_identifier is None and new_location is None and new_mod_rot is None:
            warnings.warn(f'Nothing has changed for {identifier}.')
            return

        # rename identifier
        if not new_identifier is None:
            self._modules[new_identifier] = self._modules.pop(identifier)
            identifier = new_identifier

        # change location
        if not new_location is None:
            if isinstance(new_location, str):
                new_location = self.slots[new_location]
            else:
                if new_location[0] is None:
                    new_location[0] = self._modules[identifier]['dist']
                if new_location[1] is None:
                    new_location[1] = self._modules[identifier]['theta']
                new_location = u.Quantity(new_location, u.deg).value
                
            self._modules[identifier]['dist'] = new_location[0]
            self._modules[identifier]['theta'] = new_location[1]

        # change module rotation
        if not new_mod_rot is None:
            self._modules[identifier]['mod_rot'] = u.Quantity(new_mod_rot, u.deg).value

    @_check_identifier
    def delete_module(self, identifier) -> None:
        """
        Delete a module. 

        Parameters
        -------------------------
        idenitifier : str
            Name of the module. 
        """
        self._modules.pop(identifier)

    # GETTERS 

    def save_data(self, path_or_buf=None):
        """
        Saves as a dictionary like 
        {   'instr_offset': , 
            'instr_rot': , 
            'modules':  {
                module_name: {'pixel_num':, 'dist':, 'theta':, 'mod_rot':, 'x': ,'y':, 'pol':, 'rhombus', 'wafer'},
            }
        }

        Parameters
        -------------
        path_or_buf : str or file handle, default None
            File path or object, if None is provided the result is returned as a dict.

        Returns
        ----------------------
        None or dict
            If path_or_buf is None, returns the resulting json format as a dictionary. Otherwise returns None.
        """

        # organize the configuration 
        config = {'instr_offset': list(self.instr_offset.value), 'instr_rot': self.instr_rot.value, 'modules': dict()}

        for identifier in self._modules.keys():
            config['modules'][identifier] = {
                'dist': self._modules[identifier]['dist'], 
                'theta': self._modules[identifier]['theta'],
                'mod_rot': self._modules[identifier]['mod_rot'],
                'pixel_num': [int(x) for x in self._modules[identifier]['module'].pixel_num],
                'x': list(self._modules[identifier]['module'].x.value),
                'y': list(self._modules[identifier]['module'].y.value),
                'pol': list(self._modules[identifier]['module'].pol.value),
                'rhombus': [int(x) for x in self._modules[identifier]['module'].rhombus],
                'wafer': [int(x) for x in self._modules[identifier]['module'].wafer]
            }
        
        # push configuration 
        if path_or_buf is None:
            return config
        else:
            with open(path_or_buf, 'w') as f:
                json.dump(config, f)
    
    @_check_identifier
    def get_module(self, identifier, with_rot=False) -> Module:
        """
        Return a Module object. 
        
        Parameters
        -------------------------
        idenitifier : str
            Name of the module. 
        with_rot : bool, default False
            Whether to apply instrument and module rotation to the returned Module. 
        
        Returns
        --------------------------
        Module 
            The Module object to be returned. 
        """

        if with_rot:
            data = self._modules[identifier]['module'].save_data()
            x = np.array(data['x'])
            y = np.array(data['y'])
            mod_rot = self.get_mod_rot(identifier).to(u.rad).value
            instr_rot = self.instr_rot.to(u.rad).value

            data['x'] = x*math.cos(mod_rot + instr_rot) - y*math.sin(mod_rot + instr_rot)
            data['y'] = x*math.sin(mod_rot + instr_rot) + y*math.cos(mod_rot + instr_rot)
            return Module(data)
        else:
            return self._modules[identifier]['module']

    @_check_identifier
    def get_dist(self, identifier) -> u.Quantity:
        """
        Parameters
        -------------------------
        idenitifier : str
            Name of the module. 

        Returns
        u.Quantity
            Distance of module from the center of the instrument (not boresight) in u.deg. 
        """
        return self._modules[identifier]['dist']*u.deg
    
    @_check_identifier
    def get_theta(self, identifier) -> u.Quantity:
        """
        Parameters
        -------------------------
        idenitifier : str
            Name of the module. 

        Returns
        u.Quantity
            Angle of module from the center of the instrument (not boresight) in u.deg. 
        """
        return self._modules[identifier]['theta']*u.deg
    
    @_check_identifier
    def get_mod_rot(self, identifier) -> u.Quantity:
        """
        Parameters
        -------------------------
        idenitifier : str
            Name of the module. 

        Returns
        u.Quantity
            Rotation of module from the center of the instrument (not boresight) in u.deg. 
        """
        return self._modules[identifier]['mod_rot']*u.deg

    @_check_identifier
    def get_location(self, identifier) -> u.Quantity:
        """
        Parameters
        -------------------------
        idenitifier : str
            Name of the module. 

        Returns
        (dist, theta)
            Location of module from the center of the instrument (not boresight) in u.deg. 
        """
        return [self._modules[identifier]['dist'], self._modules[identifier]['theta']]*u.deg

    @property
    def instr_offset(self):
        return self._instr_offset*u.deg
    
    @property
    def instr_rot(self):
        return self._instr_rot*u.deg
    
    @property
    def slots(self):
        return self.slots.copy()

    @property
    def modules(self):
        return self.modules.copy()

    # SETTERS

    @instr_offset.setter
    def instr_offset(self, value):
        self._instr_offset = u.Quantity(value, u.deg).value

    @instr_rot.setter
    def instr_rot(self, value):
        self.instr_rot = u.Quantity(value, u.deg).value

class ModCam(Instrument): 
    slots = {'c': (0, 0)}

class PrimeCam(Instrument):

    # default configuration of optics tubes at 0 deg elevation 
    # in terms of (radius from center [deg], angle [deg])
    _default_ir = 1.78
    slots = {
        'c': (0, 0), 
        'i1': (_default_ir, -90), 'i2': (_default_ir, -30), 'i3': (_default_ir, 30), 'i4': (_default_ir, 90), 'i5': (_default_ir, 150), 'i6': (_default_ir, -150),
    }
    