"""
Codes for correcting and estimating attenuation on ZH and ZDR.

@title: attenuation
@author: Valentin Louf <valentin.louf@monash.edu>
@institutions: Monash University and the Australian Bureau of Meteorology
@date: 19/12/2018

.. autosummary::
    :toctree: generated/

    correct_attenuation_zdr
    correct_attenuation_zh_pyart
"""
# Other Libraries
import pyart
import numpy as np


def correct_gaseous_attenuation(radar):
    """
    Adjust for gaseous attenuation from Doviak and Zrnic note tempgas is in dB,
    elevation in degrees and r in km! Equation valid only for elevation < 10 deg
    and r < 200 km. Right now only doing for tropic atmosphere according to
    Doviak and Zrnic's book; for C-band we can increase the attenuation by a
    FACTOR OF 1.2.

    Note: Doviak and Zrnic's fit is for standard atmosphere (atten by oxygen
    and water vapor. Their equation is at S-band. The factor of 1.2  is a good
    approximation for C-band! Water vapor atten may have to increased in tropics
    or over ocean.
    """
    r = radar.range['data'] / 1000
    theta = radar.elevation['data']

    R, TH = np.meshgrid(r, theta)

    atten_gas = np.zeros(TH.shape)
    pos = TH <= 10

    tempgas1 = 0.4 + 3.45 * np.exp(-TH / 1.8)
    tempgas2 = 27.8 + 154 * np.exp(-TH / 2.2)
    atten_gas = 1.2 * tempgas1 * (1 - np.exp(-R / tempgas2))  # 1.2 factor for C-band 1.0 for S-band.
    atten_gas[~pos] = 0

    atten_meta = dict()
    atten_meta['long_name'] = 'atmospheric_gases_attenuation'
    atten_meta['units'] = 'dB'
    atten_meta['description'] = 'Doviak and Zrnic eq 3.19 p 44.'
    atten_meta['valid_min'] = 0
    atten_meta['_FillValue'] = -9999
    atten_meta['data'] = atten_gas

    return atten_meta


def correct_attenuation_zdr(radar, zdr_name='ZDR_CORR', phidp_name='PHIDP_VAL', alpha=0.016):
    """
    Correct attenuation on differential reflectivity. KDP_GG has been
    cleaned of noise, that's why we use it.

    V. N. Bringi, T. D. Keenan and V. Chandrasekar, "Correcting C-band radar
    reflectivity and differential reflectivity data for rain attenuation: a
    self-consistent method with constraints," in IEEE Transactions on Geoscience
    and Remote Sensing, vol. 39, no. 9, pp. 1906-1915, Sept. 2001.
    doi: 10.1109/36.951081

    Parameters:
    ===========
        radar:
            Py-ART radar structure.
        zdr_name: str
            Differential reflectivity field name.
        kdp_name: str
            KDP field name.

    Returns:
    ========
        zdr_corr: array
            Attenuation corrected differential reflectivity.
    """
    zdr = radar.fields[zdr_name]['data'].copy()
    phi = radar.fields[phidp_name]['data'].copy()

    # Z-PHI coefficient from Bringi et al. 2001
    zdr_meta = pyart.config.get_metadata('differential_reflectivity')
    zdr_meta['description'] = 'Attenuation corrected differential reflectivity using Bringi et al. 2001.'
    zdr_meta['data'] = zdr + 0.016 * phi

    return zdr_meta


def correct_attenuation_zh_pyart(radar, refl_field='DBZ', ncp_field='NCP',
                                 rhv_field='RHOHV_CORR', phidp_field='PHIDP_GG'):
    """
    Correct attenuation on reflectivity using Py-ART tool.

    Parameters:
    ===========
    radar:
        Py-ART radar structure.
    refl_name: str
        Reflectivity field name.
    kdp_name: str
        KDP field name.

    Returns:
    ========
    atten_meta: dict
        Specific attenuation.
    zh_corr: array
        Attenuation corrected reflectivity.
    """
    # Compute attenuation
    atten_meta, zh_corr = pyart.correct.calculate_attenuation(radar, 0,
                                                              rhv_min=0.3,
                                                              refl_field=refl_field,
                                                              ncp_field=rhv_field,
                                                              rhv_field=rhv_field,
                                                              phidp_field=phidp_field)

    return atten_meta, zh_corr
