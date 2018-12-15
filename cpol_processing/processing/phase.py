"""
Codes for correcting the differential phase and estimating KDP.

@title: phase
@author: Valentin Louf <valentin.louf@monash.edu>
@institutions: Monash University and the Australian Bureau of Meteorology
@date: 20/11/2017

.. autosummary::
    :toctree: generated/

    check_phidp
    fix_phidp_from_kdp
    phidp_bringi
    phidp_giangrande
    unfold_raw_phidp

TODO: Implement correction of PHIDP using region based as preprocessing for unfolding.
"""
# Python Standard Library
import copy

# Other Libraries
import pyart
import scipy
import netCDF4
import numpy as np

from scipy import integrate, ndimage
from csu_radartools import csu_kdp

from pyart.correct.phase_proc import smooth_and_trim_scan
from sklearn.linear_model import LinearRegression
from sklearn.isotonic import IsotonicRegression


def fix_phidp_from_kdp(phidp, kdp, r, gatefilter):
    """
    Correct PHIDP and KDP from spider webs.

    Parameters
    ==========
    r:
        Radar range.
    gatefilter:
        Gate filter.
    kdp_name: str
        Differential phase key name.
    phidp_name: str
        Differential phase key name.

    Returns:
    ========
    phidp: ndarray
        Differential phase array.
    """
    kdp[gatefilter.gate_excluded] = 0
    kdp[(kdp < -4)] = 0
    kdp[kdp > 15] = 0
    interg = integrate.cumtrapz(kdp, r, axis=1)

    phidp[:, :-1] = interg / (len(r))
    return phidp, kdp


def phidp_bringi(radar, gatefilter, unfold_phidp_name="PHI_UNF", ncp_name="NCP",
                 rhohv_name="RHOHV_CORR", refl_field='DBZ'):
    """
    Compute PHIDP and KDP Bringi.

    Parameters
    ==========
    radar:
        Py-ART radar data structure.
    gatefilter:
        Gate filter.
    unfold_phidp_name: str
        Differential phase key name.
    refl_field: str
        Reflectivity key name.

    Returns:
    ========
    phidpb: ndarray
        Bringi differential phase array.
    kdpb: ndarray
        Bringi specific differential phase array.
    """
    dp = radar.fields[unfold_phidp_name]['data'].copy()
    dz = radar.fields[refl_field]['data'].copy().filled(-9999)

    try:
        if np.nanmean(dp[gatefilter.gate_included]) < 0:
            dp += 90
    except ValueError:
        pass

    # Extract dimensions
    rng = radar.range['data']
    azi = radar.azimuth['data']
    dgate = rng[1] - rng[0]
    [R, A] = np.meshgrid(rng, azi)

    # Compute KDP bringi.
    kdpb, phidpb, _ = csu_kdp.calc_kdp_bringi(dp, dz, R / 1e3, gs=dgate, bad=-9999, thsd=12, window=3.0, std_gate=11)

    # Mask array
    phidpb = np.ma.masked_where(phidpb == -9999, phidpb)
    kdpb = np.ma.masked_where(kdpb == -9999, kdpb)

    # Get metadata.
    phimeta = pyart.config.get_metadata("differential_phase")
    phimeta['data'] = phidpb
    kdpmeta = pyart.config.get_metadata("specific_differential_phase")
    kdpmeta['data'] = kdpb

    return phimeta, kdpmeta


def phidp_giangrande(radar, gatefilter, refl_field='DBZ', ncp_field='NCP',
                     rhv_field='RHOHV_CORR', phidp_field='PHIDP'):
    """
    Phase processing using the LP method in Py-ART. A LP solver is required,

    Parameters:
    ===========
    radar:
        Py-ART radar structure.
    gatefilter:
        Gate filter.
    refl_field: str
        Reflectivity field label.
    ncp_field: str
        Normalised coherent power field label.
    rhv_field: str
        Cross correlation ration field label.
    phidp_field: str
        Differential phase label.

    Returns:
    ========
    phidp_gg: dict
        Field dictionary containing processed differential phase shifts.
    kdp_gg: dict
        Field dictionary containing recalculated differential phases.
    """
    #  Preprocessing
    unfphidict = pyart.correct.dealias_region_based(
        radar, gatefilter=gatefilter, vel_field=phidp_field, nyquist_vel=90)

    phi = radar.fields[phidp_field]['data']
    if phi.max() - phi.min() <= 200:  # 180 degrees plus some margin for noise...
        half_phi = True
    else:
        half_phi = False

    vflag = np.zeros_like(phi)
    vflag[gatefilter.gate_excluded] = -3
    # unfphi, vflag = filter_data(phi, vflag, 90, 180, 40)
    unfphi = unfphidict['data']

    try:
        if np.nanmean(phi[gatefilter.gate_included]) < 0:
            unfphi += 90
    except ValueError:
        pass

    if half_phi:
        unfphi *= 2

    unfphi[vflag == -3] = 0

    # unfphi['data'][unfphi['data'] >= 340] = np.NaN
    radar.add_field_like(phidp_field, 'PHIDP_TMP', unfphi)
    # Pyart version 1.10.
    phidp_gg, kdp_gg = pyart.correct.phase_proc_lp(radar,
                                                   0.0,
                                                   # gatefilter=gatefilter,
                                                   LP_solver='cylp',
                                                   ncp_field=ncp_field,
                                                   refl_field=refl_field,
                                                   rhv_field=rhv_field,
                                                   phidp_field='PHIDP_TMP')

    radar.fields.pop('PHIDP_TMP')
    phidp_gg.pop('valid_min')

    if half_phi:
        unfphi['data'] /= 2
        phidp_gg['data'] /= 2
        kdp_gg['data'] /= 2

    phidp_gg['data'], kdp_gg['data'] = fix_phidp_from_kdp(phidp_gg['data'],
                                                          kdp_gg['data'],
                                                          radar.range['data'],
                                                          gatefilter)

    try:
        radar.fields.pop('unfolded_differential_phase')
    except Exception:
        pass

    return phidp_gg, kdp_gg


def _compute_kdp_from_phidp(r, phidp, window_len=35):
    """
    Compute KDP from PHIDP using Sobel filter. This is coming from pyart.

    Parameters:
    ===========
    r: ndarray
        Radar range.
    phidp: ndarray
        PhiDP field.
    window_len: int
        Size of the window for the Sobel filter.

    Returns:
    ========
    kdp_meta: dict
        KDP dictionary field.
    """
    sobel = 2. * np.arange(window_len) / (window_len - 1.0) - 1.0
    sobel = sobel / (abs(sobel).sum())
    sobel = sobel[::-1]
    gate_spacing = (r[1] - r[0]) / 1000.
    kdp = (scipy.ndimage.filters.convolve1d((phidp), sobel, axis=1) / ((window_len / 3) * 2 * gate_spacing))
    kdp_meta = pyart.config.get_metadata('specific_differential_phase')
    kdp_meta['data'] = kdp

    return kdp_meta


def valentin_phase_processing(radar, gatefilter, phidp_name='PHIDP', bounds=[0, 360]):
    """
    Differential phase processing using machine learning technique.

    Parameters:
    ===========
    radar: struct
        Py-ART radar object structure.
    gatefilter: GateFilter
        Py-ART GateFilter object.
    phidp_name: str
        Name of the differential phase field.
    bounds: list
        Bounds, in degree, for PHIDP (0, 360).

    Returns:
    ========
        phitot: dict
            Processed differential phase.
    """
    # Check if PHIDP is in a 180 deg or 360 deg interval.
    if phi.max() - phi.min() <= 200:  # 180 degrees plus some margin for noise...
        half_phi = True
        nyquist = 90
        cutoff = 80
    else:
        half_phi = False
        nyquist = 180
        cutoff = 160

    scale_phi = True
    try:
        if np.nanmean(radar.fields[phidp_name]['data'][gatefilter.gate_included][:, :50]) > 0:
            scale_phi = False
    except Exception:
        pass

    # Dealiasing PHIDP using velocity dealiasing technique.
    unfphidict = pyart.correct.dealias_region_based(radar, gatefilter=gatefilter,
                                                    vel_field=phidp_name, nyquist_vel=nyquist)
    unfphi = unfphidict['data'].copy()
    if half_phi:
        unfphi *= 2
    if scale_phi:
        unfphi += 90

    # Remove noise
    unfphi[(unfphi < 0) | (radar.fields[phidp_name]['data'] > cutoff)] = np.NaN

    phitot = np.zeros_like(unfphi) + np.NaN
    unfphi[gatefilter.gate_excluded] = np.NaN
    nraymax = unfphi.shape[0]
    x = radar.range['data']

    for ray in range(0, nraymax):
        nposm, nposp = 1, 1
        if ray == 0:
            nposm = 0
        if ray == nraymax - 1:
            nposp = 0

        # Taking the average the direct neighbours of each ray.
        y = np.nanmean(unfphi[(ray - nposm): (ray + nposp), :], axis=0)
        y[x < 5e3] = np.NaN  # Close to the radar is always extremly noisy

        y = np.ma.masked_invalid(y)
        pos = ~y.mask

        x_nomask = x[pos].filled(np.NaN)
        y_nomask = y[pos].filled(np.NaN)

        # Machine learning stuff.
        ir = IsotonicRegression(bounds[0], bounds[1])
        y_fit = ir.fit_transform(x_nomask, y_nomask - y_nomask.min())

        phitot[ray, pos] = y_fit - y_fit.min()
        phitot[ray, x < 5e3] = 0

    if half_phi:
        phitot /= 2

    phi_unfold = pyart.config.get_metadata('differential_phase')
    phi_unfold['data'] = phitot
    return phitot
