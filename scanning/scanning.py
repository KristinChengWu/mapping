"""
TODO
- add other plotting functions
- not using kwargs 
- __init__ check if required combinations of parameters are present
- units of x_coord, y_coord, etc.
- rename pixel_scale
- brush up on docs for functions and classes
"""

# imports
import math
from math import pi, sin, cos, tan, sqrt
import numpy as np
import pandas as pd
from datetime import timezone
from fast_histogram import histogram2d

# astropy imports
import astropy.units as u
from astropy.time import Time, TimeDelta
from astropy.coordinates import SkyCoord, EarthLocation, AltAz
from astropy.convolution import Gaussian2DKernel, convolve_fft

# plotting imports 
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from mpl_toolkits.axes_grid1 import make_axes_locatable
from mpl_toolkits.axes_grid1.anchored_artists import AnchoredSizeBar
from matplotlib.colors import ListedColormap
import matplotlib.dates as mdates

# system imports
import os
import copy

# constants
FYST_LOC = EarthLocation(lat='-22d59m08.30s', lon='-67d44m25.00s', height=5611.8*u.m)

###################################
#       OTHER FUNCTIONS
###################################

def visibility(start_datetime, end_datetime, objects, max_airmass=2, min_elevation=0*u.deg, max_elevation=90*u.deg, freq=10*u.s, x_axis='hour_angle'):

    min_elevation = u.Quantity(min_elevation, u.deg)
    max_elevation = u.Quantity(max_elevation, u.deg)

    # create datetime range between the start and end
    freq = TimeDelta(u.Quantity(freq, u.s)).to_datetime()
    datetime_range = pd.date_range(start_datetime, end_datetime, freq=freq)
    obs_time_range = Time(datetime_range, scale='utc', location=FYST_LOC)

    # freq for rotation angle derivative
    freq_hr = freq.seconds/3600 

    # create plot figures
    fig1 = plt.figure(1)
    ax_elev = plt.subplot2grid((1, 2), (0, 0), fig=fig1)
    ax_airmass = plt.subplot2grid((1, 2), (0, 1), fig=fig1, sharex=ax_elev)

    fig2 = plt.figure(2)
    ax_rot = plt.subplot2grid((1, 2), (0, 0), fig=fig2)
    ax_rot_rate = plt.subplot2grid((1, 2), (0, 1), fig=fig2, sharex=ax_rot)

    ax_hist_ncols = 2
    ax_hist_nrows = math.ceil(len(objects)/ax_hist_ncols)
    fig3, ax_hist = plt.subplots(ax_hist_nrows, ax_hist_ncols, sharex=True, sharey=True)

    ax_list = (ax_elev, ax_airmass, ax_rot, ax_rot_rate)

    # get colormap for hist
    cm = plt.cm.get_cmap('tab20').colors

    max_abs_rot_rate = 0
    for i, obj in enumerate(objects):

        # extract provided ra/dec and transform to alt/az
        dec = u.Quantity(obj[0], u.deg)
        ra = u.Quantity(obj[1], u.hourangle)
        print(f'dec={dec.to(u.deg).value}N ra={ra.to(u.hourangle).value}h')
        obs = SkyCoord(dec=dec, ra=ra).transform_to(AltAz(obstime=datetime_range, location=FYST_LOC))

        # select for points with low air mass and between the elevation range
        mask = (obs.secz <= max_airmass) & (obs.alt.deg > min_elevation.to(u.deg).value)
        mask_max_elev = obs.alt.deg[mask] < max_elevation.to(u.deg).value

        # parallactic and rotation angle
        lst = obs_time_range.sidereal_time('apparent')[mask]
        hour_angle = lst - ra
        hour_angle_rad = hour_angle.to(u.rad).value
        hour_angle_hrang = hour_angle.to(u.hourangle).value
        hour_angle_hrang[hour_angle_hrang > 12] = hour_angle_hrang[hour_angle_hrang > 12] - 24
        mask_hrangle = hour_angle_hrang < 0

        dec_rad = dec.to(u.rad).value
        para_angle = np.arctan2(
            np.sin(hour_angle_rad),
            (cos(dec_rad)*tan(FYST_LOC.lat.rad) - sin(dec_rad)*np.cos(hour_angle_rad))
        )*u.rad
        rot_angle = para_angle + obs.alt[mask]
        rot_angle_deg = rot_angle.to(u.deg).value

        # choose x_axis
        if x_axis == 'hourangle':
            x_values = hour_angle_hrang
            label = f'dec={dec.to(u.deg).value}N'
        elif x_axis == 'time':
            x_values = datetime_range[mask]
            label = f'({round(ra.to(u.hourangle).value)}h {round(dec.to(u.deg).value)}N)'

        # add to plot
        ax_airmass.plot(x_values, obs.secz[mask], label=label)
        ax_elev.plot(x_values, obs.alt.deg[mask], label=label)
        #ax_rot.plot(x_values, rot_angle_deg, label=label)

        # rotation angle 
        center_rot_i = list(hour_angle_hrang).index( max(hour_angle_hrang[mask_hrangle]) )
        low_rot = rot_angle_deg[center_rot_i] - 180
        rot_norm = (rot_angle_deg - low_rot)%360 + low_rot # ((value - low) % diff) + low 

        ax_rot.plot(x_values[mask_max_elev & mask_hrangle], rot_norm[mask_max_elev & mask_hrangle], label=label, color=cm[2*i])
        ax_rot.plot(x_values[mask_max_elev & ~mask_hrangle], rot_norm[mask_max_elev & ~mask_hrangle], color=cm[2*i])
        ax_rot.plot(x_values[~mask_max_elev], rot_norm[~mask_max_elev], color=cm[2*i], ls='dashed')

        # rotation angle rate 
        rot_rate = np.diff(rot_norm, append=math.nan)/freq_hr
        ax_rot_rate.plot(x_values[mask_max_elev & mask_hrangle], rot_rate[mask_max_elev & mask_hrangle], label=label, color=cm[2*i])
        ax_rot_rate.plot(x_values[mask_max_elev & ~mask_hrangle], rot_rate[mask_max_elev & ~mask_hrangle], color=cm[2*i])
        ax_rot_rate.plot(x_values[~mask_max_elev], rot_rate[~mask_max_elev], color=cm[2*i], ls='dashed')

        max_abs_rot_rate = max( max_abs_rot_rate, np.max(abs(rot_rate[mask_max_elev])) )

        # histograms of rotation angle
        ax_hist_row = math.floor(i/ax_hist_ncols)
        ax_hist_col = i%ax_hist_ncols

        a1 = rot_angle_deg[mask_hrangle & mask_max_elev]%90
        a2 = rot_angle_deg[~mask_hrangle & mask_max_elev]%90

        total_seconds = len(a1) + len(a2)
        print('total:', total_seconds)

        ax_hist[ax_hist_row, ax_hist_col].hist(a1, bins=range(0, 91, 1), color=cm[2*i], label='hourangle < 0', weights=np.full(len(a1), 1/total_seconds))
        ax_hist[ax_hist_row, ax_hist_col].hist(a2, bins=range(0, 91, 1), color=cm[2*i+1], label='hourangle >= 0', histtype='step', weights=np.full(len(a2), 1/total_seconds))
        ax_hist[ax_hist_row, ax_hist_col].set(xlabel='Rotation Angle (mod 90) [deg]', ylabel='Fraction of Time', title=label)
        ax_hist[ax_hist_row, ax_hist_col].legend(loc='upper right')
        ax_hist[ax_hist_row, ax_hist_col].grid()
        ax_hist[ax_hist_row, ax_hist_col].xaxis.set_tick_params(labelbottom=True)
        ax_hist[ax_hist_row, ax_hist_col].yaxis.set_tick_params(labelbottom=True)

    max_abs_rot_rate = max(max_abs_rot_rate, 60)

    # handle xticks and other settings of ax

    if x_axis == 'hourangle':
        xlabel = 'Hourangle [hours]'
        xticks = [i for i in range(-12, 13, 3)]
        xtick_labels = [f'{t + 24}h' if t < 0 else f'{t}h' for t in xticks]

        for ax in ax_list:
            ax.set(xticks=xticks, xticklabels=xtick_labels)

        ax_airmass.set_yscale('function', functions=(lambda x: np.log10(x), lambda x: 10**x))
    
    elif x_axis == 'time':
        xlabel = f'Time from {datetime_range[-1].strftime("%Y-%m-%d")} [UTC]'
        xlim=(datetime_range[0], datetime_range[-1])

        for ax in ax_list:
            ax.set(xlim=xlim)

        fig1.gca().xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        fig2.gca().xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))

    ax_airmass.set(
        title='Airmass for Visible Objects (airmass < 2) at FYST', xlabel=xlabel, 
        ylabel='Airmass', ylim=( max(1.001, 1/cos(pi/2 - max_elevation.to(u.rad).value)) , max_airmass)
    )
    ax_airmass.invert_yaxis()
    ax_airmass.axhline(1/cos(pi/2 - math.radians(75)), ls='dashed', color='black')

    ax_elev.set(
        title='Elevation for Visible Objects (airmass < 2) at FYST', xlabel=xlabel,
        ylabel='Elevation [deg]', ylim=(min_elevation.to(u.deg).value, min(max_elevation.to(u.deg).value, 87))
    )
    ax_elev.set_yticks(np.append(ax_elev.get_yticks(), 75))
    ax_elev.axhline(75, ls='dashed', color='black')

    ax_rot.set(title='Rotation Angle for Visible Objects (airmass < 2) at FYST', xlabel=xlabel, ylabel='Rotation Angle [deg]')

    ax_rot_rate.set(
        title='Rotation Angle Rate for Visible Objects (airmass < 2) at FYST', xlabel=xlabel, 
        ylabel='Rotation Angle Rate [deg/hr]', ylim=(-max_abs_rot_rate, max_abs_rot_rate)
    )
    ax_rot_rate.axhline(15, ls=':', color='black')
    ax_rot_rate.axhline(-15, ls=':', color='black')
    ax_rot_rate.set_yticks(np.append(ax_rot_rate.get_yticks(), [-15, 15]))

    # secondary axis for azimuthal scale factor

    def transform(x):
        np.seterr(invalid='ignore', divide='ignore')
        new_x = 1/np.sin(np.arccos(1/x))
        mask = np.isinf(new_x)
        new_x[mask] = math.nan
        np.seterr(invalid='warn', divide='warn')
        return new_x

    def inverse(x):
        np.seterr(invalid='ignore', divide='ignore')
        new_x = 1/np.cos(np.arcsin(1/x)) 
        mask = np.isinf(new_x)
        new_x[mask] = math.nan
        np.seterr(invalid='warn', divide='warn')
        return new_x

    ax_airmass_right = ax_airmass.secondary_yaxis('right', functions=(transform, inverse))
    ax_airmass_right.set(ylabel='Azimuthal Scale Factor')
    ax_airmass_right.set_yticks([1.2, 1.5, 2, 2.5, 3, 4])

    ax_elev_right = ax_elev.secondary_yaxis('right', functions=( lambda x: 1/np.cos(np.radians(x)), lambda x: np.degrees(np.arccos(1/x)) ))
    ax_elev_right.set(ylabel='Azimuthal Scale Factor')
    ax_elev_right.set_yticks([1.2, 2, 3, 4, 5, 6, 15])

    # final touchups to axis

    ax_airmass.legend(loc='lower right')
    ax_elev.legend(loc='lower right')

    ax_rot.legend(loc='lower right')
    ax_rot_rate.legend(loc='lower right')

    for ax in ax_list:
        ax.grid()

    fig1.tight_layout()
    fig2.tight_layout()
    fig3.tight_layout()

    plt.show()


###################################
#            HITMAP
###################################

class Hitmap():

    pixel_analysis = False
    param = dict()
    
    def __init__(self, scan, **kwargs):

        # --- UNPACK ARGUMENTS ---

        self._scan = scan

        # mandatory parameters 
        self.param['plate_scale'] = u.Quantity(kwargs.get('plate_scale', 52*u.arcsec), u.arcsec)
        self.param['pixel_scale'] = u.Quantity(kwargs.get('pixel_scale', 10*u.arcsec), u.arcsec)
        self.param['det_rot'] = u.Quantity(kwargs.get('det_rot', 0*u.deg), u.deg)

        self.param['max_acc'] = u.Quantity(kwargs['max_acc'], u.deg/u.s/u.s) if 'max_acc' in kwargs.keys() else None
        self.param['convolve'] = kwargs.get('convolve', False)
        self.param['pols_on'] = kwargs.get('pols_on', True) 
        self.param['norm_time'] = kwargs.get('norm_time', False)

        # analysis of pixel(s)
        self.param['norm_pxan'] = kwargs.get('norm_pxan', False)

        if 'pixel_list' in kwargs.keys() or 'x_lim' in kwargs.keys(): 
            self.pixel_analysis = True

            if 'pixel_list' in kwargs.keys():
                self.param['x_lim'] = None
                self.param['y_lim'] = None
                self.param['pixel_list'] = kwargs['pixel_list']
            else:
                self.param['pixel_list'] = None
                self.param['x_lim'] = kwargs['x_lim']
                self.param['y_lim'] = kwargs['y_lim']

        # analysis of smaller sub-section 
        self.param['mini_size'] = kwargs.get('mini_size')

        # --- PRE-PROCESSING --- 
        
        # get mapping of detector elements
        self.det_elem =  self._get_det_elements()

        # get mask for valid data
        self.validity_mask = self._get_valid_data()

        # hitmap preprocessing for both the kept and removed hitmaps
        max_pixel = u.Quantity(kwargs['max_pixel'], u.arcsec).value if 'max_pixel' in kwargs.keys() else None
        self.max_pixel, num_bins, x_range_pxan, y_range_pxan, dividing_factor = self._hitmap_preprocessing(max_pixel)
        hitmap_kwargs = {'x_range_pxan': x_range_pxan, 'y_range_pxan': y_range_pxan, 'dividing_factor': dividing_factor}

        # --- HITMAP ---

        # kept hits
        x_coord = self.scan.x_coord.to(u.arcsec).value[self.validity_mask]
        y_coord = self.scan.y_coord.to(u.arcsec).value[self.validity_mask]
        rot_angle = self.scan.rot_angle[self.validity_mask]
        self.hist, self.det_hist, self.time_hist = self._generate_hitmap(x_coord, y_coord, rot_angle, num_bins, **hitmap_kwargs)

        # removed hits
        x_coord = self.scan.x_coord.to(u.arcsec).value[~self.validity_mask]
        y_coord = self.scan.y_coord.to(u.arcsec).value[~self.validity_mask]
        rot_angle = self.scan.rot_angle[~self.validity_mask]
        self.hist_rem, self.det_hist_rem, self.time_hist_rem = self._generate_hitmap(x_coord, y_coord, rot_angle, num_bins, **hitmap_kwargs)

    # GENERATING HITMAP/HIST STUFF

    def _get_det_elements(self):

        ROOT = os.path.abspath(os.path.dirname(__file__))
        PIXELPOS_FILES = ['pixelpos1.txt', 'pixelpos2.txt', 'pixelpos3.txt']
        PIXELPOS_FILES = [os.path.join(ROOT, 'data', f) for f in PIXELPOS_FILES]

        # get pixel positions
        x_pixel = np.array([])
        y_pixel = np.array([])

        for f in PIXELPOS_FILES:
            x, y = np.loadtxt(f, unpack=True)
            x_pixel = np.append(x_pixel, x)
            y_pixel = np.append(y_pixel, y)
        num_elem_in_wafer = int(len(x)/3)

        # convert from meters to arcsec
        dist_btwn_detectors = math.sqrt((x_pixel[0] - x_pixel[1])**2 + (y_pixel[0] - y_pixel[1])**2)
        plate_scale_arcsec = self.plate_scale.to(u.arcsec).value
        x_pixel = x_pixel/dist_btwn_detectors*plate_scale_arcsec
        y_pixel = y_pixel/dist_btwn_detectors*plate_scale_arcsec

        # map polarizations to first wafer
        p = np.empty(num_elem_in_wafer)
        polar = False
        for i in range(1, num_elem_in_wafer+1):
            p[i-1] = polar
            polar = polar if i%24 == 0 else not polar # FIXME change as frequency changes
            
        # convert to corresponding angle 
        p1 = 45*p # 0 = 0, 1 = 45
        p2 = -45*p + 60 # 4 = 60, 5 = 15
        p3 = 45*p + 30 # 2 = 30, 3 = 75

        pol = np.append(p1, np.append(p2, p3))
        pol = np.tile(pol, 3)

        # get specific polarizations
        if not self.pols_on is True: # all polarizations are on
            if isinstance(self.pols_on, int):
                mask = pol == self.pols_on
            else:
                mask = np.in1d(pol, self.pols_on)
            
            x_pixel = x_pixel[mask]
            y_pixel = y_pixel[mask]
            pol = pol[mask]
        
        return pd.DataFrame({'x_pixel': x_pixel, 'y_pixel': y_pixel, 'pol': pol})
    
    def _get_valid_data(self):
        
        # remove points with high acceleration
        if self.max_acc is None:
            mask = np.full(len(self.scan.x_coord), True)
        else:
            x_acc = self.scan.x_acc.to(u.deg/u.s/u.s).value
            y_acc = self.scan.y_acc.to(u.deg/u.s/u.s).value
            total_acc = np.sqrt(x_acc**2 + y_acc**2)
            mask = total_acc < self.max_acc.to(u.deg/u.s/u.s).value

        return mask

    def _hitmap_preprocessing(self, max_pixel):

        # find the distance from the center of the pixel location that is farthest away 
        x_pixel = self.x_pixel.to(u.arcsec).value
        y_pixel = self.y_pixel.to(u.arcsec).value
        farthest_det_elem = max(np.sqrt(x_pixel**2 + y_pixel**2))

        # find the distance from the center of the farthest timestamp 
        # use the diagonal for extra space 
        x_coord = self.scan.x_coord.to(u.arcsec).value
        y_coord = self.scan.y_coord.to(u.arcsec).value
        farthest_ts = max(np.sqrt(x_coord**2 + y_coord**2))

        # get params for bin edges
        pixel_scale = self.pixel_scale.to(u.arcsec).value
        if max_pixel is None:
            max_pixel = math.ceil((farthest_det_elem + farthest_ts)/pixel_scale)*pixel_scale
        num_bins = int(2*max_pixel/pixel_scale)

        # set up for pixel analysis
        x_range_pxan = None
        y_range_pxan = None
        dividing_factor = None

        if self.pixel_analysis:

            # rectangular area of pixels
            if self.pixel_list is None:
                x_range_pxan = [ (self.x_lim[0]*pixel_scale, self.x_lim[1]*pixel_scale) ]
                y_range_pxan = [ (self.y_lim[0]*pixel_scale, self.y_lim[1]*pixel_scale) ]
                if self.norm_pxan:
                    dividing_factor = int((self.x_lim[0] - self.x_lim[1])*(self.y_lim[0] - self.y_lim[1]))

            # discrete list of pixels
            else:
                x_range_pxan = []
                y_range_pxan = []
                for px in self.pixel_list:
                    x_min = px[0]*pixel_scale
                    y_min = px[1]*pixel_scale
                    x_range_pxan.append((x_min, x_min + pixel_scale))
                    y_range_pxan.append((y_min, y_min + pixel_scale))
                dividing_factor = len(x_range_pxan)
            
        return max_pixel*u.arcsec, num_bins, x_range_pxan, y_range_pxan, dividing_factor

    def _generate_hitmap(self, x_coord, y_coord, rot_angle, num_bins, **kwargs):
        max_pixel = self.max_pixel.to(u.arcsec).value

        x_range_pxan = kwargs['x_range_pxan']
        y_range_pxan = kwargs['y_range_pxan']
        dividing_factor = kwargs['dividing_factor']

        # get detector elements
        x_pixel = self.x_pixel.to(u.arcsec).value
        y_pixel = self.y_pixel.to(u.arcsec).value
        num_det_elem = len(x_pixel)

        num_ts = len(x_coord)
        print('num_ts =', num_ts,'num_det_elem =', num_det_elem)

        # initialize histograms to returned
        hist = np.zeros((num_bins, num_bins))
        det_hist = np.zeros(num_det_elem)
        time_hist = np.zeros(num_ts)

        # this section if for removed hits (if there are none)
        if num_ts == 0:
            if self.pixel_analysis:
                return hist, det_hist, time_hist
            else:
                return hist, None, None

        """
        # get direction of motion
        dx_coord = np.diff(x_coord, prepend=math.nan)
        dy_coord = np.diff(y_coord, prepend=math.nan)

        np.seterr(divide='ignore')
        motion_angle = np.arctan(dy_coord/dx_coord)
        np.seterr(divide='warn')
        """
        
        # APPLY HISTOGRAM

        det_rot = self.det_rot.to(u.rad).value
        rot_angle = rot_angle.to(u.rad).value
        #pol = np.radians(self.pol)

        # Divide process into chunks to abide by memory limits

        MEM_LIMIT = 8*10**7 
        chunk_ts = math.floor(MEM_LIMIT/num_det_elem)
        for chunk in range(math.ceil(num_ts/chunk_ts)):

            # initialize empty arrays (rows of ts and cols of det elements) to store hits 
            if (chunk+1)*chunk_ts <= num_ts:
                num_rows = chunk_ts
            else:
                num_rows = num_ts - chunk*chunk_ts

            all_x_coords = np.empty((num_rows, num_det_elem))
            all_y_coords = np.empty((num_rows, num_det_elem))

            # range of ts to loop over
            start = chunk*chunk_ts
            end = start + num_rows
            print('start:', start, 'end:', end)

            # add all hits from the detector elements at each ts 
            for i, x_coord1, y_coord1, rot1 in zip(range(num_rows), x_coord[start:end], y_coord[start:end], rot_angle[start:end]):
                all_x_coords[i] = x_coord1 + x_pixel*cos(rot1 + det_rot) + y_pixel*sin(rot1 + det_rot)
                all_y_coords[i] = y_coord1 - x_pixel*sin(rot1 + det_rot) + y_pixel*cos(rot1 + det_rot)

            hist += histogram2d(all_x_coords, all_y_coords, range=[[-max_pixel, max_pixel], [-max_pixel, max_pixel]], bins=[num_bins, num_bins])

            # apply pixel(s) analysis
            if self.pixel_analysis:
                mask = False
                for x_range, y_range in zip(x_range_pxan, y_range_pxan):
                    mask = mask | ( (all_x_coords >= x_range[0]) & (all_x_coords < x_range[1]) & (all_y_coords >= y_range[0]) & (all_y_coords < y_range[1]) )

                det_hist += np.count_nonzero(mask, axis=0)
                time_hist[start:end] = np.count_nonzero(mask, axis=1)

        # Convolution
        pixel_scale = self.pixel_scale.to(u.arcsec).value
        if self.convolve:
            stddev = (50/pixel_scale)/np.sqrt(8*np.log(2))
            kernel = Gaussian2DKernel(stddev)
            hist = convolve_fft(hist, kernel, boundary='fill', fill_value=0)
        
        # Normalize for pixel analysis
        if self.norm_pxan:
            det_hist = det_hist/dividing_factor
            time_hist = time_hist/dividing_factor
        
        # Normalize for time
        if self.norm_time:
            total_time = self.scan.time_offset[-1].to(u.s).value + self.scan.sample_interval.to(u.s).value
            hist = hist/total_time
            det_hist = det_hist/total_time
            time_hist = time_hist/total_time

        if not self.pixel_analysis:
            det_hist = time_hist = None

        return hist, det_hist, time_hist

    # PLOTS 

    def hitmap(self, total_max=None, kept_max=None, rem_max=None, mini_size=None):

        hist_sum = sum(self.hist.flatten())
        hist_rem_sum = sum(self.hist_rem.flatten())
        print(f'Total Hits: {hist_sum + hist_rem_sum}, Kept Hits: {hist_sum}')

        fig = plt.figure(1)
        hit_per_str = 'px/s' if self.norm_time else 'px'

        pixel_scale = self.pixel_scale.to(u.deg).value
        max_pixel = self.max_pixel.to(u.deg).value
        num_bins = int(2*max_pixel/pixel_scale)
        x_edges = np.linspace(-max_pixel, max_pixel, num_bins, endpoint=False)
        y_edges = np.linspace(-max_pixel, max_pixel, num_bins, endpoint=False)

        # --- HISTOGRAMS ---

        # reference FoV
        if self.scan.scan_type == 'pong':
            width = self.scan.width.to(u.deg).value
            height = self.scan.height.to(u.deg).value
            field = patches.Rectangle((-width/2, -height/2), width=width, height=height, linewidth=1, edgecolor='r', facecolor='none') 
        elif self.scan.scan_type == 'daisy':
            R0 = self.scan.R0.to(u.deg).value
            field = patches.Circle((0, 0), R0, linewidth=1, edgecolor='r', facecolor='none')

        # Combined Histogram
        ax1 = plt.subplot2grid((4, 4), (0, 0), rowspan=3, fig=fig)
        hist_comb = self.hist + self.hist_rem
        pcm = ax1.imshow(hist_comb.T, extent=[-max_pixel, max_pixel, -max_pixel, max_pixel], vmin=0, vmax=total_max, interpolation='nearest', origin='lower')
        ax1.set_aspect('equal', 'box')
        ax1.set(xlabel='x offset (deg)', ylabel='y offset (deg)')
        ax1.set_title(f'Total hits/{hit_per_str}')

        ax1.add_patch(copy.copy(field))
        ax1.axvline(x=0, c='black')
        ax1.axhline(y=0, c='black')

        divider = make_axes_locatable(ax1)
        cax1 = divider.append_axes("bottom", size="3%", pad=0.5)
        fig.colorbar(pcm, cax=cax1, orientation='horizontal')

        # Kept Histogram
        ax2 = plt.subplot2grid((4, 4), (0, 1), rowspan=3, fig=fig, sharex=ax1, sharey=ax1)
        pcm = ax2.imshow(self.hist.T, extent=[-max_pixel, max_pixel, -max_pixel, max_pixel], vmin=0, vmax=kept_max, interpolation='nearest', origin='lower')
        ax2.set_aspect('equal', 'box')
        ax2.set(xlabel='x offset (deg)', ylabel='y offset (deg)')
        ax2.set_title(f'Kept hits/{hit_per_str}')

        ax2.add_patch(copy.copy(field))
        ax2.axvline(x=0, c='black')
        ax2.axhline(y=0, c='black')

        divider = make_axes_locatable(ax2)
        cax2 = divider.append_axes("bottom", size="3%", pad=0.5)
        fig.colorbar(pcm, cax=cax2, orientation='horizontal')

        # Removed Histogram
        ax3 = plt.subplot2grid((4, 4), (0, 2), rowspan=3, fig=fig, sharex=ax1, sharey=ax1)
        pcm = ax3.imshow(self.hist_rem.T, extent=[-max_pixel, max_pixel, -max_pixel, max_pixel], vmin=0, vmax=rem_max, interpolation='nearest', origin='lower')
        ax3.set_aspect('equal', 'box')
        ax3.set(xlabel='x offset (deg)', ylabel='y offset (deg)')
        ax3.set_title(f'Removed hits/{hit_per_str}')

        ax3.add_patch(copy.copy(field))
        ax3.axvline(x=0, c='black')
        ax3.axhline(y=0, c='black')

        divider = make_axes_locatable(ax3)
        cax3 = divider.append_axes("bottom", size="3%", pad=0.5)
        fig.colorbar(pcm, cax=cax3, orientation='horizontal')

        # mini map
        if not mini_size is None:
            mini_size = u.Quantity(mini_size, u.deg).value
            field_mini = patches.Rectangle((-mini_size/2, -mini_size/2), mini_size, mini_size, linewidth=1, edgecolor='r', facecolor='none', ls='dashed')
            ax1.add_patch(copy.copy(field_mini))
            ax2.add_patch(copy.copy(field_mini))
            ax3.add_patch(copy.copy(field_mini))

        # --- DETECTOR ELEMENTS AND PATH ----

        det_rot = self.det_rot.to(u.rad).value
        x_pixel = self.x_pixel.to(u.deg).value
        y_pixel = self.y_pixel.to(u.deg).value

        ax4 = plt.subplot2grid((4, 4), (0, 3), rowspan=3, sharex=ax1, sharey=ax1, fig=fig)
        ax4.scatter(self.scan.x_coord.to(u.deg).value, self.scan.y_coord.to(u.deg).value, color='red', s=0.01, alpha=0.1)
        ax4.scatter(x_pixel*cos(det_rot) + y_pixel*sin(det_rot), -x_pixel*sin(det_rot) + y_pixel*cos(det_rot), s=0.05)

        ax4.set_aspect('equal', 'box')
        ax4.set(xlabel='x offset (deg)', ylabel='y offset (deg)')
        ax4.set_title('Pixel Positions')
        divider = make_axes_locatable(ax4)
        cax4 = divider.append_axes("bottom", size="3%", pad=0.5)
        cax4.axis('off')

        # --- BIN PLOTS ---

        # bin line plot (#1)
        ax5 = plt.subplot2grid((4, 4), (3, 0), colspan=2, fig=fig)
        bin_index = round(max_pixel/pixel_scale)
        bin_edge = x_edges[bin_index]
        y_values = self.hist[bin_index]
        y_values_rem = self.hist_rem[bin_index]

        ax5.plot(y_edges, y_values, label='Kept hits', drawstyle='steps')
        ax5.plot(y_edges, y_values_rem, label='Removed hits', drawstyle='steps')
        ax5.plot(y_edges, y_values + y_values_rem, label='Total hits', drawstyle='steps', color='black')

        if self.scan.scan_type == 'pong':
            ax5.axvline(x=-width/2, c='r')
            ax5.axvline(x=width/2, c='r') 

        ax5.set(ylabel=f'Hits/{hit_per_str}', xlabel='y offset (deg)', ylim=(0, total_max))
        ax5.set_title(f'Hit count in x={round(bin_edge, 3)} to x={round(bin_edge+pixel_scale, 3)} bin', fontsize=12)
        ax5.legend(loc='upper right')

        # bin line plot (#2)
        ax6 = plt.subplot2grid((4, 4), (3, 2), colspan=2, fig=fig)
        bin_index = round(max_pixel/pixel_scale/2)
        bin_edge = x_edges[bin_index]
        y_values = self.hist[bin_index]
        y_values_rem = self.hist_rem[bin_index]

        ax6.plot(y_edges, y_values, label='Kept hits', drawstyle='steps')
        ax6.plot(y_edges, y_values_rem, label='Removed hits', drawstyle='steps')
        ax6.plot(y_edges, y_values + y_values_rem, label='Total hits', drawstyle='steps', color='black')

        if self.scan.scan_type == 'pong':
            ax6.axvline(x=-width/2, c='r')
            ax6.axvline(x=width/2, c='r') 

        ax6.set(ylabel=f'Hits/{hit_per_str}', xlabel='y offset (deg)', ylim=(0, total_max))
        ax6.set_title(f'Hit count in x={round(bin_edge, 3)} to x={round(bin_edge+pixel_scale, 3)} bin', fontsize=12)
        ax6.legend(loc='upper right')

        fig.tight_layout()
        plt.show()

    def detector_polarization(self):
        all_pol = np.array([0, 15, 30, 45, 60, 75])
        n_pol = len(all_pol)

        x_pixel = self.x_pixel.to(u.deg).value
        y_pixel = self.y_pixel.to(u.deg).value

        p_det = plt.subplot2grid((2, 2), (0, 0), rowspan=2)
        cm = ListedColormap(['purple', 'yellow', 'blue', 'green', 'black', 'red'])
        sc = p_det.scatter(x_pixel, y_pixel, c=self.pol, cmap=cm, s=5)
        p_det.set_aspect('equal', 'box')
        p_det.set(xlabel='x offset (deg)', ylabel='y offset (deg)', title='Map of Polarization in Detector Array')

        cbar = plt.colorbar(sc, fraction=0.046, pad=0.04)
        tick_locs = (all_pol + 7.5)*(n_pol-1)/n_pol
        cbar.set_ticks(tick_locs)
        cbar.set_ticklabels(all_pol)
        cbar.ax.set_ylabel('Crosshair Rotation [deg]')
        plt.show()

    def pxan_det(self):
        assert(self.pixel_analysis)

        fig_det = plt.figure(1)
        hit_per_str = 'px/s' if self.norm_time else 'px'
        max_hits = math.ceil(max(self.det_hist + self.det_hist_rem))

        # --- DETECTOR HITMAP ---

        cm = plt.cm.get_cmap('viridis')

        x_pixel = self.x_pixel.to(u.deg).value
        y_pixel = self.y_pixel.to(u.deg).value

        # plot detector elem (total)
        det1 = plt.subplot2grid((2, 2), (0, 0), fig=fig_det)
        sc = det1.scatter(x_pixel, y_pixel, c=self.det_hist+self.det_hist_rem, cmap=cm, vmin=0, vmax=max_hits, s=15)
        fig_det.colorbar(sc, ax=det1, orientation='horizontal')
        det1.set_aspect('equal', 'box')
        det1.set(xlabel='x offset (deg)', ylabel='y offset (deg)')
        det1.set_title(f'Total hits/{hit_per_str}')

        # plot detector elem (kept)
        det2 = plt.subplot2grid((2, 2), (0, 1), fig=fig_det, sharex=det1, sharey=det1)
        sc = det2.scatter(x_pixel, y_pixel, c=self.det_hist, cmap=cm, vmin=0, vmax=max_hits, s=15)
        fig_det.colorbar(sc, ax=det2, orientation='horizontal')
        det2.set_aspect('equal', 'box')
        det2.set(xlabel='x offset (deg)', ylabel='y offset (deg)')
        det2.set_title('Kept hits per pixel')

        # scale bar
        if self.scan.scan_type == 'pong':
            spacing = round(self.scan.spacing.to(u.deg).value, 3)
            scalebar = AnchoredSizeBar(det1.transData, spacing, label=f'{spacing} deg spacing', loc=1, pad=0.5, borderpad=0.5, sep=5)
            det1.add_artist(scalebar)
            scalebar = AnchoredSizeBar(det1.transData, spacing, label=f'{spacing} deg spacing', loc=1, pad=0.5, borderpad=0.5, sep=5)
            det2.add_artist(scalebar)

        # ---- PLOTTING DETECTOR HISTOGRAM ----

        bins_det_hist = np.arange(1, max_hits+1, 1)

        # total
        det_hist1 = plt.subplot2grid((2, 2), (1, 0), fig=fig_det)
        det_hist1.hist(self.det_hist+self.det_hist_rem, bins=bins_det_hist, edgecolor='black', linewidth=1)
        det_hist1.set(xlabel='# of hits (excluding 0)', ylabel='# of detectors', title='Total Hits')
        
        # kept
        det_hist2 = plt.subplot2grid((2, 2), (1, 1), sharex=det_hist1, sharey=det_hist1, fig=fig_det)
        det_hist2.hist(self.det_hist, bins=bins_det_hist, edgecolor='black', linewidth=1)
        det_hist2.set(xlabel='# of hits (excluding 0)', ylabel='# of detectors', title='Kept Hits')

        fig_det.tight_layout()
        plt.show()

    def pxan_pol(self):
        assert(self.pixel_analysis)

        fig_pol = plt.figure(5)
        all_pol = np.array([0, 15, 30, 45, 60, 75])
        n_pol = len(all_pol)

        # --- DETECTOR PLOT ---

        x_pixel = self.x_pixel.to(u.deg).value
        y_pixel = self.y_pixel.to(u.deg).value

        p_det = plt.subplot2grid((2, 2), (0, 0), rowspan=2, fig=fig_pol)
        cm = cm = ListedColormap(['purple', 'yellow', 'blue', 'green', 'black', 'red'])
        sc = p_det.scatter(x_pixel, y_pixel, c=self.pol, cmap=cm, s=5)
        p_det.set_aspect('equal', 'box')
        p_det.set(xlabel='x offset (deg)', ylabel='y offset (deg)', title='Polarization Map')

        cbar = plt.colorbar(sc)
        tick_locs = (all_pol + 7.5)*(n_pol-1)/n_pol
        cbar.set_ticks(tick_locs)
        cbar.set_ticklabels(all_pol)

        # --- POLARIZATION HISTOGRAM ---

        pol_hits = []
        pol_hits_rem = []
        for p in all_pol:
            mask = self.pol == p
            pol_hits.append(sum(self.det_hist[mask]))
            pol_hits_rem.append(sum(self.det_hist_rem[mask]))
        
        pol_hits = np.array(pol_hits)
        pol_hits_rem = np.array(pol_hits_rem)
        print('pol hits:', sum(pol_hits), sum(pol_hits_rem))

        # Total hits 
        p1 = plt.subplot2grid((2, 2), (0, 1), fig=fig_pol)
        p1.hist(all_pol, bins=(-7.5, 7.5, 22.5, 37.5, 52.5, 67.5, 82.5), weights=pol_hits + pol_hits_rem, edgecolor='black', linewidth=1)
        p1.set(xlabel='Polarization', ylabel='# of hits', title='Total Hits')
        p1.set_aspect('auto')
        p1.set_xticks(all_pol)

        # Kept hits
        p2 = plt.subplot2grid((2, 2), (1, 1), sharex=p1, sharey=p1, fig=fig_pol)
        p2.hist(all_pol, bins=(-7.5, 7.5, 22.5, 37.5, 52.5, 67.5, 82.5), weights=pol_hits, edgecolor='black', linewidth=1)
        p2.set(xlabel='Polarization', ylabel='# of hits', title='Kept Hits')
        p2.set_aspect('auto')
        p2.set_xticks(all_pol)

        fig_pol.tight_layout()
        plt.show()

    def pxan_time(self):
        assert(self.pixel_analysis)

        fig_time = plt.figure(1)
        max_time = math.ceil(max(self.scan.time_offset.to(u.s).value))

        times = self.scan.time_offset.to(u.s).value[self.validity_mask]
        times_rem = self.scan.time_offset.to(u.s).value[~self.validity_mask]

        # --- 1 SEC HISTOGRAMS ---
    
        bins_time = range(0, max_time+1, 1)

        # total
        time1_tot = plt.subplot2grid((2, 2), (0, 0), fig=fig_time)
        time1_tot.hist(np.append(times, times_rem), bins=bins_time, weights=np.append(self.time_hist, self.time_hist_rem))
        time1_tot.set(xlabel='Time Offset (s)', ylabel='# of hits', title='Total Hits')

        # kept
        time1_kept = plt.subplot2grid((2, 2), (0, 1), sharex=time1_tot, sharey=time1_tot, fig=fig_time)
        time1_kept.hist(times, bins=bins_time, weights=self.time_hist)
        time1_kept.set(xlabel='Time Offset (s)', ylabel='# of hits', title='Kept Hits')

        # --- 10 SEC HISTOGRAMS ---
    
        bins_time = range(0, max_time+10, 10)

        # total
        time2_tot = plt.subplot2grid((2, 2), (1, 0), fig=fig_time)
        time2_tot.hist(np.append(times, times_rem), bins=bins_time, weights=np.append(self.time_hist, self.time_hist_rem))
        time2_tot.set(xlabel='Time Offset (s)', ylabel='# of hits', title='Total Hits')

        # kept
        time2_kept = plt.subplot2grid((2, 2), (1, 1), sharex=time2_tot, sharey=time2_tot, fig=fig_time)
        time2_kept.hist(times, bins=bins_time, weights=self.time_hist)
        time2_kept.set(xlabel='Time Offset (s)', ylabel='# of hits', title='Kept Hits')

        fig_time.tight_layout()
        plt.show()

    def pol_hist(self):
        
        # all polarization options
        all_pol = np.array([0, 15, 30, 45, 60, 75])

        # rotation angle as the detector moves
        rot_angle = self.scan.rot_angle.to(u.deg).value
        det_rot = self.det_rot.to(u.deg).value

        # get polarization combined with rotation angle
        pol_dict = dict()
        for det_pol in all_pol:
            pol_dict[det_pol] = (det_pol - rot_angle - det_rot)%90

        num_pol = len(all_pol)
        num_det_elem_per_pol = len(self.pol)/num_pol
        print(f'Total Hits: {len(rot_angle)*num_pol*num_det_elem_per_pol}')

        # --- PLOTTING ---

        fig = plt.figure(1)
        ax = plt.subplot2grid((1, 1), (0, 0), fig=fig)
        ax.grid()
        ax.set(xlabel='Polarization Angle [deg]', ylabel='# of Hits', title='Histogram of Polarization + Field Rotation')

        for p in all_pol:
            ax.hist(pol_dict[p], bins=90*4, range=(0, 90), weights=[num_det_elem_per_pol]*len(rot_angle), label=f'{p}$^\circ$')

        ax.legend(loc='upper right', title='Initial Polarization')
        plt.show()        

    # GETTER FUNCTIOSN

    @property
    def x_pixel(self): # list of angle-like
        return self.det_elem['x_pixel'].to_numpy()*u.arcsec

    @property
    def y_pixel(self): # list of angle-like
        return self.det_elem['y_pixel'].to_numpy()*u.arcsec
    
    @property
    def pol(self): # list of int
        return self.det_elem['pol'].to_numpy()

    @property
    def scan(self):
        return self._scan

    @property
    def plate_scale(self): # angle-like
        return self.param['plate_scale']

    @property
    def pixel_scale(self): # angle-like
        return self.param['pixel_scale']
    
    @property
    def det_rot(self): # angle-like
        return self.param['det_rot']

    @property
    def max_acc(self): # speed-like or None
        return self.param['max_acc']

    @property
    def convolve(self): # bool
        return self.param['convolve']

    @property
    def pols_on(self): # list of int, True, or int
        return self.param['pols_on']
        
    @property
    def norm_time(self): # bool
        return self.param['norm_time']

    @property
    def norm_pxan(self): # bool
        return self.param['norm_pxan']

    @property
    def x_lim(self): # (int, int) or None
        return self.param['x_lim']
    
    @property
    def y_lim(self): # (int, int) or None
        return self.param['y_lim']

    @property
    def pixel_list(self): # list of (int, int) or None
        return self.param['pixel_list']
    

###################################
#         SCAN PATTERNS
###################################

class ScanPattern():

    scan_type = None
    _default_folder = None
    _default_param_csv = None

    _param_unit = None
    _param_default = None

    has_setting = False
    setting_param = dict()

    def __init__(self, data_csv=None, param_csv=None, **kwargs):

        # pass data by a csv file 
        if not data_csv is None:

            # find default parameter csv file 
            if param_csv is None:
                if os.path.isfile(os.path.join(self._default_folder, self._default_param_csv)):
                    param_csv = os.path.join(self._default_folder, self._default_param_csv)
                elif os.path.isfile(self._default_param_csv):
                    param_csv = self._default_param_csv
                else:
                    raise ValueError('No file_path to param_csv given and none found in current working directory.')

            # check data_csv in cwd as well as default folder
            if not os.path.isfile(data_csv) and os.path.isfile(os.path.join(self._default_folder, data_csv)):
                data_csv = os.path.join(self._default_folder, data_csv)
            
            # extract data and parameters
            self.data = pd.read_csv(data_csv, index_col=False)
            kwargs_uncleaned = pd.read_csv(param_csv, index_col='file_name').loc[os.path.basename(data_csv)].to_dict()

            kwargs = dict()
            for unclean_param_name in kwargs_uncleaned.keys():
                param_name = unclean_param_name.split(' ')[0]

                if param_name == 'time0':
                    self.setting_param['time0'] = kwargs_uncleaned[unclean_param_name]
                elif param_name in ('ra', 'dec', 'alt'):
                    self.setting_param[param_name] = kwargs_uncleaned[unclean_param_name]*u.deg
                else:
                    kwargs[param_name] = kwargs_uncleaned[unclean_param_name]

            # set self.has_setting
            self.has_setting = 'az_coord' in self.data.columns

        # initialize parameters with their corresponding unit
        for param_name in self._param_unit.keys():
            param_value = kwargs[param_name] if param_name in kwargs.keys() else self._param_default[param_name]
            kwargs[param_name] = u.Quantity(param_value, self._param_unit[param_name])

        self.param = kwargs

        # generate data from parameters
        if data_csv is None:
            self.data = self._generate_scan()

    def to_csv(self, data_csv, param_csv=None, with_param_file=True):
        """
        Save generated data into a csv file and its associated parameters. 

        Parameters
        -----------------
        data_csv : str
            File path you want to save data into. 
        param_csv : str, defaults to finding/making a default paramter file 
            File path to parameter file 
        with_param_file : bool, defaults to True
            Whether to place the data file in the same directory as param_csv (True) or cwd (False)
        """

        common_path = os.path.join(self._default_folder, self._default_param_csv)

        if param_csv is None:

            # check if param file already exists
            if os.path.isfile(self._default_param_csv):
                param_csv = self._default_param_csv
            elif os.path.isfile(common_path):
                param_csv = common_path
           
            # make a new param file
            else:
                if not os.path.isdir(self._default_folder):
                    os.mkdir(self._default_folder)

                #param_file_unit = {param_name: [str(self._param_unit[param_name])] for param_name in self._param_unit.keys()}
                #param_file_unit['file_name'] = ['']
                #pd.DataFrame(param_file_unit).to_csv(common_path, index=False)
                pd.DataFrame(columns=['file_name']).to_csv(common_path, index=False)
                print(f'Created new parameter file: {param_csv}')

                param_csv = common_path
        
        # save data csv file next to the param file 
        if with_param_file:
            if not os.path.dirname(param_csv) == os.path.dirname(data_csv):
                data_csv = os.path.join(os.path.dirname(param_csv), data_csv)
            
        # UPDATE PARAM FILE

        param_df = pd.read_csv(param_csv, index_col='file_name')
        base_name = os.path.basename(data_csv)

        # base scan pattern parameters
        for p in self.param.keys():
            param_df.loc[base_name, p + f' ({str(self._param_unit[p])})'] = self.param[p].value

        # parameters for the setting
        if self.setting_param:
            param_df.loc[base_name, 'ra (deg)'] = self.setting_param['ra'].value
            param_df.loc[base_name, 'dec (deg)'] = self.setting_param['dec'].value
            param_df.loc[base_name, 'alt (deg)'] = self.setting_param['alt'].value
            param_df.loc[base_name, 'time0'] = self.setting_param['time0']

        param_df.to_csv(param_csv)
        print(f'Updated parameter file {param_csv}')

        # SAVE DATA FILE
        self.data.to_csv(data_csv, index=False)
        print(f'Saved data to {data_csv}')    

    def _central_diff(self, a):
        h = self.sample_interval.to(u.s).value
        new_a = [(a[1] - a[0])/h]
        for i in range(1, len(a)-1):
            new_a.append( (a[i+1] - a[i-1])/(2*h) )
        new_a.append( (a[-1] - a[-2])/h )
        return np.array(new_a)

    # INITIALIZE SETTING

    @u.quantity_input(dec='angle', lat='angle', ha='angle')
    def _find_altitude(self, dec, lat, ha):
        dec = dec.to(u.rad).value
        lat = lat.to(u.rad).value
        ha = ha.to(u.rad).value
        sin_alt = sin(dec)*sin(lat) + cos(dec)*cos(lat)*cos(ha)
        return math.asin(sin_alt)*u.rad
        
    def set_setting(self, **kwargs):
        """ 
        Finding the AZ/ALT coordinates given a specific set of parameters. 
        Some formulas from http://www.stargazing.net/kepler/altaz.html
        
        Possible Inputs:
            ra, dec, location, date, alt (limited range)
            ra, dec, location, datetime

        Parameters
        ---------------------------------
        **kwargs
        ra : angle-like
            Right ascension of object
            If no units specified, defaults to deg
        dec : angle-like
            Declination of object
            If no units specified, defaults to deg
        location : astropy.coordinates.EarthLocation, defaults to FYST FIXME add option to provide lat/lon/height and record it
            Location of observation/telescope
        
        alt : angle-like, optional
            Desired approximate initial altitude
            If no units specified, defaults to deg
        date : str or date-like, optional 
            Initial date of observation (UTC) FIXME add option to specify timezone
        moving_up : bool, defaults to True
            Whether to choose path such that object is moving up in altitude

        datetime : str or datetime-like, optional
            Initial datetime of observation (UTC) FIXME add option to specify timezone
        """

        self.has_setting = True
        self.setting_param = {'ra': u.Quantity(kwargs['ra'], u.deg), 'dec': u.Quantity(kwargs['dec'], u.deg)}

        ra_rad = self.setting_param['ra'].to(u.rad).value
        dec_rad = self.setting_param['dec'].to(u.rad).value
        location = kwargs.get('location', FYST_LOC)

        # Given altitude and date
        if 'alt' in kwargs.keys():
            self.setting_param['alt'] = u.Quantity(kwargs['alt'], u.deg)

            # determine possible hour angles
            alt_rad = self.setting_param['alt'].to(u.rad).value
            lat_rad = location.lat.rad
            cos_ha = (sin(alt_rad) - sin(dec_rad)*sin(lat_rad)) / (cos(dec_rad)*cos(lat_rad))
            try:
                ha_rad = math.acos(cos_ha)
            except ValueError as e:
                raise ValueError('Altitude is not possible at provided RA, declination, and latitude.') from e
                # FIXME list range of possible altitudes

            # choose hour angle
            moving_up = kwargs.get('moving_up', True)
            ha1_delta = self._find_altitude(dec_rad*u.rad, lat_rad*u.rad, ha_rad*u.rad + 1*u.deg) - self._find_altitude(dec_rad*u.rad, lat_rad*u.rad, ha_rad*u.rad)
            ha1_up = True if ha1_delta > 0 else False

            ha2_delta = self._find_altitude(dec_rad*u.rad, lat_rad*u.rad, -ha_rad*u.rad + 1*u.deg) - self._find_altitude(dec_rad*u.rad, lat_rad*u.rad, -ha_rad*u.rad)
            ha2_up = True if ha2_delta > 0 else False
            assert(ha1_up != ha2_up)

            if (moving_up and ha2_up) or (not moving_up and ha1_up):
                ha_rad = -ha_rad 

            # find ut (universal time after midnight of chosen date) 
            lon_deg = location.lon.deg
            date = kwargs['date'] # FIXME check that it's date, not datetime

            time0 = Time(date, scale='utc')
            num_days = (time0 - Time(2000, format='jyear')).value # days from J2000
            lst_deg = math.degrees(ha_rad + ra_rad)
            ut = (lst_deg - 100.46 - 0.98564*num_days - lon_deg)/15
            time0 = pd.Timestamp(date, tzinfo=timezone.utc) + pd.Timedelta(ut%24, 'hour')
        
        # Given datetime
        elif 'datetime' in kwargs.keys():
            time0 = Time(kwargs['datetime'], scale='utc')

        # Required inputs not present
        else:
            raise ValueError('Required inputs are not given.')

        # -----------------------------------
        # ----------- GENERAL ---------------
        # -----------------------------------

        # apply datetime to time_offsets
        time0_str = time0.strftime("%Y-%m-%d %H:%M:%S.%f%z")
        self.setting_param['time0'] = time0_str

        df_datetime = pd.to_timedelta(self.data['time_offset'], unit='sec') + time0

        # convert to altitude/azimuth
        ra_deg = self.setting_param['ra'].to(u.deg).value
        dec_deg = self.setting_param['dec'].to(u.deg).value

        x_coord = self.x_coord.to(u.deg) + ra_deg*u.deg
        y_coord = self.y_coord.to(u.deg) + dec_deg*u.deg

        obs = SkyCoord(ra=x_coord, dec=y_coord, frame='icrs')
        print('Converting to altitude/azimuth...')
        obs = obs.transform_to(AltAz(obstime=df_datetime, location=location))
        print('...Converted!')

        # set starting altitude if not already set
        if not 'alt' in self.setting_param.keys():
            self.setting_param['alt'] = obs.alt.deg[0]*u.deg

        # get parallactic angle and rotation angle
        obs_time = Time(df_datetime, scale='utc', location=location)
        lst_deg = obs_time.sidereal_time('apparent').deg
        hour_angles_rad = (lst_deg*u.deg - ra_deg*u.deg).to(u.rad).value
        dec_rad = self.setting_param['dec'].to(u.rad).value

        para_deg = np.degrees(np.arctan2( 
            np.sin(hour_angles_rad), 
            cos(dec_rad)*tan(location.lat.rad) - sin(dec_rad)*np.cos(hour_angles_rad) 
        ))
        rot_deg = para_deg + obs.alt.deg

        hour_angles_hrang = [hr - 24 if hr > 12 else hr for hr in hour_angles_rad*u.rad.to(u.hourangle)]

        # populate dataframe (all using deg except for hourangle)
        self.data['az_coord'] = obs.az.deg
        self.data['alt_coord'] = obs.alt.deg
        self.data['az_vel'] = self._central_diff(obs.az.deg)
        self.data['alt_vel'] = self._central_diff(obs.alt.deg)
        self.data['az_acc'] = self._central_diff(self.data['az_vel'].to_numpy())
        self.data['alt_acc'] = self._central_diff(self.data['alt_vel'].to_numpy())
        self.data['az_jerk'] = self._central_diff(self.data['az_acc'].to_numpy())
        self.data['alt_jerk'] = self._central_diff(self.data['az_acc'].to_numpy())
        self.data['hour_angle'] = hour_angles_hrang # in hourangle 
        self.data['para_angle'] = para_deg
        self.data['rot_angle'] = rot_deg

    # PLOT

    def plot_coord_elevation_rot(self):

        fig = plt.figure(1)
        ax_coord = plt.subplot2grid((1, 2), (0, 0), fig=fig)
        ax_elevation = plt.subplot2grid((1, 2), (0, 1), fig=fig)

        x_coord = self.x_coord.to(u.deg).value
        y_coord = self.y_coord.to(u.deg).value
        rot_angle = self.rot_angle.to(u.deg).value
        time_offset = self.time_offset.to(u.s).value
        elevation =  self.data['alt_coord'].to_numpy()
    
        # Scan Pattern
        ax_coord.plot(x_coord, y_coord, linewidth=1)
        ax_coord.set_aspect('equal', 'box')
        ax_coord.set(xlabel='Right Ascension [deg]', ylabel='Declination [deg]', title='RA/DEC')
        ax_coord.grid()

        # Elevation & Rot Angle
        ax_elevation.plot(time_offset, elevation, label='Elevation', linewidth=3)
        ax_elevation.set(xlabel='Time Offset [s]', ylabel='Elevation [deg]', title=f'Elevation and Rotation Angle vs. Time')
        ax_elevation.grid()
        ax_elevation.legend(loc='upper left')

        ax_rot_angle = ax_elevation.twinx()
        ax_rot_angle.plot(time_offset, rot_angle, label='Rotation Angle', color='tab:orange', ls='dashed')
        ax_rot_angle.set(ylabel='Rotation Angle [deg]')
        ax_rot_angle.legend(loc='upper right')

        fig.tight_layout()
        plt.show()

    def plot(self, graphs=['coord', 'coord-time', 'vel', 'acc', 'jerk']):
        
        if 'coord' in graphs:
            fig_coord, ax_coord = plt.subplots(1, 2)
            ax_coord[0].plot(self.data['x_coord'], self.data['y_coord'], linewidth=0.5)
            ax_coord[0].set_aspect('equal', 'box')
            ax_coord[0].set(xlabel='Right Ascension Offset [deg]', ylabel='Declination Offset [deg]', title='RA/DEC')
            ax_coord[0].grid()
            if self.scan_type == 'daisy':
                n=100
                circle1_x = [math.cos(2*pi/n*x)*self.R0 for x in range(0,n+1)]
                circle1_y = [math.sin(2*pi/n*x)*self.R0 for x in range(0,n+1)]
                ax_coord[0].plot(circle1_x, circle1_y, linewidth=2, color='r', ls='--', label='R0')

                circle1_x = [math.cos(2*pi/n*x)*self.Ra for x in range(0,n+1)]
                circle1_y = [math.sin(2*pi/n*x)*self.Ra for x in range(0,n+1)]
                ax_coord[0].plot(circle1_x, circle1_y, linewidth=2, color='r', label='Ra')
                
                ax_coord[0].legend(loc='upper right')

            if self.has_setting:
                ax_coord[1].plot(self.data['az_coord'], self.data['alt_coord'])
                ax_coord[1].set_aspect('equal', 'box')
                ax_coord[1].set(xlabel='Azimuth [deg]', ylabel='Altitude [deg]', title=f'AZ/ALT')
                ax_coord[1].grid()

            fig_coord.tight_layout()

        if 'coord-time' in graphs:
            fig_coord_time, ax_coord_time = plt.subplots(2, 1, sharex=True, sharey=True)

            ax_coord_time[0].plot(self.data['time_offset'], self.data['x_coord'], label='RA')
            ax_coord_time[0].plot(self.data['time_offset'], self.data['y_coord'], label='DEC')
            ax_coord_time[0].legend(loc='upper right')
            ax_coord_time[0].set(xlabel='time offset (s)', ylabel='Position offset (deg)', title=f'Position')
            ax_coord_time[0].grid()
            ax_coord_time[0].xaxis.set_tick_params(labelbottom=True)

            if self.has_setting:
                ax_coord_time[1].plot(self.data['time_offset'], (self.data['az_coord'] - self.data.loc[0, 'az_coord'])*cos(pi/6), label='Azimuth')
                ax_coord_time[1].plot(self.data['time_offset'], self.data['alt_coord'] - self.data.loc[0, 'alt_coord'], label='Elevation')
                #ax_coord_time[1].plot(self.data['time_offset'], self.data['alt_coord'], label='Elevation')
                ax_coord_time[1].legend(loc='upper right')
                ax_coord_time[1].set(xlabel='Time Offset [s]', ylabel='Position [deg]', title=f'AZ/ALT')
                ax_coord_time[1].grid()

            fig_coord_time.tight_layout()
        
        if 'vel' in graphs:
            fig_vel, ax_vel = plt.subplots(2, 1, sharex=True, sharey=True)

            total_vel = np.sqrt(self.data['x_vel']**2 + self.data['y_vel']**2)
            ax_vel[0].plot(self.data['time_offset'], total_vel, label='Total', c='black', ls='dashed', alpha=0.25)
            ax_vel[0].plot(self.data['time_offset'], self.data['x_vel'], label='RA')
            #ax_vel[0].plot(self.data['time_offset'], self.data['y_vel'], label='DEC')
            ax_vel[0].legend(loc='upper right')
            ax_vel[0].set(xlabel='time offset (s)', ylabel='velocity (deg/s)', title=f'Velocity')
            ax_vel[0].grid()
            ax_vel[0].xaxis.set_tick_params(labelbottom=True)

            if self.has_setting:
                total_vel = np.sqrt(self.data['az_vel']**2 + self.data['alt_vel']**2)
                ax_vel[1].plot(self.data['time_offset'], total_vel, label='Total', c='black', ls='dashed', alpha=0.25)
                ax_vel[1].plot(self.data['time_offset'], self.data['az_vel'], label='AZ')
                ax_vel[1].plot(self.data['time_offset'], self.data['alt_vel'], label='ALT')
                ax_vel[1].legend(loc='upper right')
                ax_vel[1].set(xlabel='time offset (s)', ylabel='velocity (deg/s)', title=f'AZ/ALT')
                ax_vel[1].grid()

            fig_vel.tight_layout()
        
        if 'acc' in graphs:
            fig_acc, ax_acc = plt.subplots(2, 1, sharex=True, sharey=True)

            total_acc = np.sqrt(self.data['x_acc']**2 + self.data['y_acc']**2)
            ax_acc[0].plot(self.data['time_offset'], total_acc, label='Total', c='black', ls='dashed', alpha=0.25)
            ax_acc[0].plot(self.data['time_offset'], self.data['x_acc'], label='RA')
            #ax_acc[0].plot(self.data['time_offset'], self.data['y_acc'], label='DEC')
            ax_acc[0].legend(loc='upper right')
            ax_acc[0].set(xlabel='time offset (s)', ylabel='acceleration (deg/s^2)', title=f'Acceleration')
            ax_acc[0].grid()
            ax_acc[0].xaxis.set_tick_params(labelbottom=True)

            if self.has_setting:
                total_acc = np.sqrt(self.data['az_acc']**2 + self.data['alt_acc']**2)
                ax_acc[1].plot(self.data['time_offset'], total_acc, label='Total', c='black', ls='dashed', alpha=0.25)
                ax_acc[1].plot(self.data['time_offset'], self.data['az_acc'], label='AZ')
                ax_acc[1].plot(self.data['time_offset'], self.data['alt_acc'], label='ALT')
                ax_acc[1].legend(loc='upper right')
                ax_acc[1].set(xlabel='time offset (s)', ylabel='acceleration (deg/s^2)', title=f'AZ/ALT')
                ax_acc[1].grid()

            fig_acc.tight_layout()

        if 'jerk' in graphs:
            fig_jerk, ax_jerk = plt.subplots(2, 1, sharex=True, sharey=True)

            total_jerk = np.sqrt(self.data['x_jerk']**2 + self.data['y_jerk']**2)
            ax_jerk[0].plot(self.data['time_offset'], self.data['x_jerk'], label='RA')
            #ax_jerk[0].plot(self.data['time_offset'], self.data['y_jerk'], label='DEC')
            ax_jerk[0].plot(self.data['time_offset'], total_jerk, label='Total', c='black', ls='dashed', alpha=0.25)
            ax_jerk[0].legend(loc='upper right')
            ax_jerk[0].set(xlabel='time offset (s)', ylabel='Jerk (deg/s^2)', title=f'Jerk')
            ax_jerk[0].grid()
            ax_jerk[0].xaxis.set_tick_params(labelbottom=True)

            if self.has_setting:
                total_jerk = np.sqrt(self.data['az_jerk']**2 + self.data['alt_jerk']**2)
                ax_jerk[1].plot(self.data['time_offset'], self.data['az_jerk'], label='AZ')
                ax_jerk[1].plot(self.data['time_offset'], self.data['alt_jerk'], label='ALT')
                ax_jerk[1].plot(self.data['time_offset'], total_jerk, label='Total', c='black', ls='dashed', alpha=0.25)
                ax_jerk[1].legend(loc='upper right')
                ax_jerk[1].set(xlabel='time offset (s)', ylabel='Jerk (deg/s^2)', title=f'AZ/ALT')
                ax_jerk[1].grid()

            fig_jerk.tight_layout()
        
        if 'quiver' in graphs:
            fig_quiver, ax_quiver = plt.subplots(1, 2, sharex=True, sharey=True)
            subsample = 50
            endpoint = None

            # --- ACCELERATION ---

            # plot acc
            total_acc = np.sqrt(self.data['x_acc']**2 + self.data['y_acc']**2).to_numpy()
            ax_quiver[0].plot(self.data['x_coord'], self.data['y_coord'], alpha=0.25, color='black')
            pcm = ax_quiver[0].quiver(
                self.data['x_coord'].to_numpy()[:endpoint:subsample], self.data['y_coord'].to_numpy()[:endpoint:subsample], 
                self.data['x_acc'].to_numpy()[:endpoint:subsample], self.data['y_acc'].to_numpy()[:endpoint:subsample],
                total_acc[:endpoint:subsample], #clim=(0, 1)
            )
            ax_quiver[0].set_aspect('equal', 'box')
            ax_quiver[0].set(xlabel='Map height [deg]', ylabel='Map width [deg]', title='RA/DEC acc [deg/s^2]')

            # colorbar acc
            divider = make_axes_locatable(ax_quiver[0])
            cax = divider.append_axes("right", size="3%", pad=0.5)
            fig_quiver.colorbar(pcm, cax=cax)

            # --- JERK ---

            # get jerk
            self.data['x_jerk'] = self._central_diff(self.data['x_acc'].to_numpy(), self.sample_interval)
            self.data['y_jerk'] = self._central_diff(self.data['y_acc'].to_numpy(), self.sample_interval)
            total_jerk = np.sqrt(self.data['x_jerk']**2 + self.data['y_jerk']**2).to_numpy()

            # plot jerk
            ax_quiver[1].plot(self.data['x_coord'], self.data['y_coord'], alpha=0.25, color='black')
            pcm = ax_quiver[1].quiver(
                self.data['x_coord'].to_numpy()[:endpoint:subsample], self.data['y_coord'].to_numpy()[:endpoint:subsample], 
                self.data['x_jerk'].to_numpy()[:endpoint:subsample], self.data['y_jerk'].to_numpy()[:endpoint:subsample]/3600,
                total_jerk[:endpoint:subsample], #clim=(0, 1)
            )
            ax_quiver[1].set_aspect('equal', 'box')
            ax_quiver[1].set(xlabel='Map height [deg]', ylabel='Map width [deg]', title='RA/DEC jerk [deg/s^3]')

            # colorbar
            divider = make_axes_locatable(ax_quiver[1])
            cax = divider.append_axes("right", size="3%", pad=0.5)
            fig_quiver.colorbar(pcm, cax=cax)
            
            fig_quiver.tight_layout()

        plt.show()

    # GETTERS

    @property
    def time_offset(self):
        return self.data['time_offset'].to_numpy()*u.s

    @property
    def x_coord(self):
        return self.data['x_coord'].to_numpy()*u.deg

    @property
    def y_coord(self):
        return self.data['y_coord'].to_numpy()*u.deg

    @property
    def x_acc(self):
        return self.data['x_acc'].to_numpy()*u.deg/u.s/u.s
    
    @property
    def y_acc(self):
        return self.data['y_acc'].to_numpy()*u.deg/u.s/u.s

    @property
    def rot_angle(self):
        return self.data['rot_angle'].to_numpy()*u.deg

    @property
    def az_coord(self):
        return self.data['az_coord'].to_numpy()*u.deg
    
    @property
    def alt_coord(self):
        return self.data['alt_coord'].to_numpy()*u.deg

class CurvyPong(ScanPattern):
    """
    The Curvy Pong pattern allows for an approximation of a Pong pattern while avoiding 
    sharp turnarounds at the vertices. 
    
    See "The Impact of Scanning Pattern Strategies on Uniform Sky Coverage of Large Maps" 
    (SCUBA Project SC2/ANA/S210/008) for details of implementation. 

    Paramters
    -------------------------
    data_csv : string
        File path to data file
    param_csv : string, optional, defaults to finding default parameter file
        File path to parameter file

    **kwargs 
    num_term : int, optional
        Number of terms in the triangle wave expansion 
    width, height : angle-like, optional
        Width and height of field of view
        If no units specified, defaults to deg
    spacing : angle-like, optional
        Space between adjacent (parallel) scan lines in the Pong pattern
        If no units specified, defaults to deg
    velocity : angle/time-like, optional
        Target magnitude of the scan velocity excluding turn-arounds
        If no units specified, defaults to deg/s
    angle : angle-like, optional, defaults to 0 deg
        Position angle of the box in the native coordinate system
        If no units specified, defaults to deg
    sample_interval : time, optional, defaults to 400 Hz
        Time between read-outs 
        If no units specified, defaults to s
    """

    scan_type = 'pong'
    _default_folder = 'curvy_pong'
    _default_param_csv = 'curvy_pong_params.csv'

    _param_default = {'num_term': 5, 'angle': 0*u.deg, 'sample_interval': 1/400*u.s}
    _param_unit = {
        'num_term': u.dimensionless_unscaled,
        'width': u.deg, 'height': u.deg, 'spacing': u.deg,
        'velocity': u.deg/u.s, 'angle': u.deg, 'sample_interval': u.s
    }

    def _generate_scan(self):
        
        # unpack parameters
        num_term = self.num_term
        width = self.width.to(u.deg).value
        height = self.height.to(u.deg).value
        spacing = self.spacing.to(u.deg).value
        velocity = self.velocity.to(u.deg/u.s).value
        sample_interval = self.sample_interval.to(u.s).value
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

        vavg = velocity
        peri_x = x_numvert * vert_spacing * 2 / vavg
        peri_y = y_numvert * vert_spacing * 2 / vavg
        period = x_numvert * y_numvert * vert_spacing * 2 / vavg

        pongcount = math.ceil(period/sample_interval)
        amp_x = x_numvert * vert_spacing / 2
        amp_y = y_numvert * vert_spacing / 2
        
        # Calculate the grid positions and apply rotation angle. Load
        # data into a dataframe.    

        data = { data_col: np.empty(pongcount) for data_col in ['time_offset', 'x_coord', 'y_coord', 'x_vel', 'y_vel', 'x_acc', 'y_acc', 'x_jerk', 'y_jerk']}

        t_count = 0
        for i in range(pongcount):
            x_pos, x_vel, x_acc, x_jerk = self._fourier_expansion(num_term, amp_x, t_count, peri_x)
            y_pos, y_vel, y_acc, y_jerk = self._fourier_expansion(num_term, amp_y, t_count, peri_y)

            data['x_coord'][i] = x_pos*cos(angle) - y_pos*sin(angle)
            data['y_coord'][i] = x_pos*sin(angle) + y_pos*cos(angle)
            data['x_vel'][i] = x_vel*cos(angle) - y_vel*sin(angle)
            data['y_vel'][i] = x_vel*sin(angle) + y_vel*cos(angle)
            data['x_acc'][i] = x_acc*cos(angle) - y_acc*sin(angle)
            data['y_acc'][i] = x_acc*sin(angle) + y_acc*cos(angle)
            data['x_jerk'][i] = x_jerk*cos(angle) - y_jerk*sin(angle)
            data['y_jerk'][i] = x_jerk*sin(angle) + y_jerk*cos(angle)

            data['time_offset'][i] = t_count
            t_count += sample_interval
        
        return pd.DataFrame(data)
    
    def _fourier_expansion(self, num_term, amp, t_count, peri):
        N = num_term*2 - 1
        a = (8*amp)/(pi**2)
        b = 2*pi/peri

        pos = vel = acc = jer = 0
        for n in range(1, N+1, 2):
            c = math.pow(-1, (n-1)/2)/n**2 
            pos += c * sin(b*n*t_count)
            vel += c*n * cos(b*n*t_count)
            acc += c*n**2 * sin(b*n*t_count)
            jer += c*n**3 * cos(b*n*t_count)

        pos *= a
        vel *= a*b
        acc *= -a*b**2
        jer *= -a*b**3
        return pos, vel, acc, jer

    @property
    def num_term(self):
        return int(self.param['num_term'].value)

    @property
    def width(self):
        return self.param['width']

    @property
    def height(self):
        return self.param['height']
    
    @property
    def spacing(self):
        return self.param['spacing']

    @property
    def velocity(self):
        return self.param['velocity']
    
    @property
    def angle(self):
        return self.param['angle']

    @property
    def sample_interval(self):
        return self.param['sample_interval']


class Daisy(ScanPattern):
    """
    See "CV Daisy - JCMT small area scanning patter" (JCMT TCS/UN/005) for details of implementation. 

    Parameters
    -----------------------------------
    velocity : angle-like/time-like
        Constant velocity (CV) for scan to go at. 
    start_acc : angle-like/time-like^2
        Acceleration at start of pattern
    R0 : angle-like
        Radius R0
    Rt : angle-like
        Turn radius
    Ra : angle-like
        Avoidance radius
    T : time-like
        Total time of the simulation
    sample_interval : time-like [default 400 Hz]
        Time step
    y_offset : angle-like
        start offset in y [default 0"]
    """

    scan_type = 'daisy'
    _default_folder = 'daisy'
    _default_param_csv = 'daisy_params.csv'

    _param_default = {'sample_interval': 1/400*u.s, 'y_offset': 0*u.deg}
    _param_unit = {
        'velocity': u.deg/u.s, 'start_acc': u.deg/u.s/u.s, 
        'R0': u.deg, 'Rt': u.deg, 'Ra': u.deg,
        'T': u.s, 'sample_interval': u.s, 'y_offset': u.deg
    }
        
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
        x_vel = np.empty(N)
        y_vel = np.empty(N)
        
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
            x_vel[step] = speed*vx
            y_vel[step] = speed*vy

        # --- END OF ALGORITHM ---

        # Compute arrays for plotting 
        #x_vel = self._central_diff(xval)
        x_acc = self._central_diff(x_vel)
        x_jerk = self._central_diff(x_acc)

        #y_vel = self._central_diff(yval)
        y_acc = self._central_diff(y_vel)
        y_jerk = self._central_diff(y_acc)

        """
        ax = -2*xval[1: -1] + xval[0:-2] + xval[2:] # numerical acc in x 
        ay = -2*yval[1: -1] + yval[0:-2] + yval[2:] # numerical acc in y 
        x_acc = np.append(np.array([0]), ax/dt/dt)
        y_acc = np.append(np.array([0]), ay/dt/dt)
        x_acc = np.append(x_acc, 0)
        y_acc = np.append(y_acc, 0)
        x_jerk = self._central_diff(x_acc)
        y_jerk = self._central_diff(y_acc)
        """

        return pd.DataFrame({
            'time_offset': np.arange(0, T, dt), 
            'x_coord': x_coord/3600, 'y_coord': y_coord/3600, 
            'x_vel': x_vel/3600, 'y_vel': y_vel/3600,
            'x_acc': x_acc/3600, 'y_acc': y_acc/3600,
            'x_jerk': x_jerk/3600, 'y_jerk': y_jerk/3600
        })

    @property
    def velocity(self):
        return self.param['velocity']
    
    @property
    def start_acc(self):
        return self.param['start_acc']

    @property
    def R0(self):
        return self.param['R0']
    
    @property
    def Rt(self):
        return self.param['Rt']
    
    @property
    def Ra(self):
        return self.param['Ra']

    @property
    def T(self):
        return self.param['T']

    @property
    def sample_interval(self):
        return self.param['sample_interval']

    @property
    def y_offset(self):
        return self.param['y_offset']
