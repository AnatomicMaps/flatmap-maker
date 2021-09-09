# ===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2020  David Brooks
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
# ===============================================================================

# Copied segments from scaffoldmaker.utils.interpolation.py
# See https://github.com/ABI-Software/scaffoldmaker

# ===============================================================================

from __future__ import division
from enum import Enum
import copy
import math

# ===============================================================================

from mapmaker.routing.utils.maths import magnitude
from mapmaker.routing.utils.maths import set_magnitude
from mapmaker.routing.utils.maths import normalize

# ===============================================================================


gaussXi4 = (
    (-math.sqrt((3.0 + 2.0 * math.sqrt(6.0 / 5.0)) / 7.0) + 1.0) / 2.0,
    (-math.sqrt((3.0 - 2.0 * math.sqrt(6.0 / 5.0)) / 7.0) + 1.0) / 2.0,
    (+math.sqrt((3.0 - 2.0 * math.sqrt(6.0 / 5.0)) / 7.0) + 1.0) / 2.0,
    (+math.sqrt((3.0 + 2.0 * math.sqrt(6.0 / 5.0)) / 7.0) + 1.0) / 2.0)

gaussWt4 = (
    (18.0 - math.sqrt(30.0)) / 72.0,
    (18.0 + math.sqrt(30.0)) / 72.0,
    (18.0 + math.sqrt(30.0)) / 72.0,
    (18.0 - math.sqrt(30.0)) / 72.0)


class DerivativeScalingMode(Enum):
    ARITHMETIC_MEAN = 1
    HARMONIC_MEAN = 2


def compute_cubic_hermite_arc_length(v1, d1, v2, d2, rescale_derivatives):
    """
    Compute arc length between v1 and v2, scaling unit d1 and d2.
    Iterative; not optimised.
    :param d1: Initial derivative at v1.
    :param d2: Initial derivative at v2.
    :param rescale_derivatives: If True, rescale initial d1 and d2 to |v2 - v|
    :return: Arc length.
    """
    if rescale_derivatives:
        last_arc_length = math.sqrt(sum((v2[i] - v1[i]) * (v2[i] - v1[i]) for i in range(len(v1))))
    else:
        last_arc_length = get_cubic_hermite_arc_length(v1, d1, v2, d2)
    d1 = normalise(d1)
    d2 = normalise(d2)
    tol = 1.0E-6
    for iters in range(100):
        d1s = [last_arc_length * d for d in d1]
        d2s = [last_arc_length * d for d in d2]
        arc_length = get_cubic_hermite_arc_length(v1, d1s, v2, d2s)
        if iters > 9:
            arc_length = 0.8 * arc_length + 0.2 * last_arc_length
        if math.fabs(arc_length - last_arc_length) < tol * arc_length:
            return arc_length
        last_arc_length = arc_length
    print('computeCubicHermiteArcLength:  Max iters reached:', iters, '=', arc_length, ', closeness',
          math.fabs(arc_length - last_arc_length))
    return arc_length


def get_cubic_hermite_arc_length(v1, d1, v2, d2):
    """
    Note this is approximate.
    :return: Arc length of cubic curve using 4 point Gaussian quadrature.
    """
    arc_length = 0.0
    for i in range(4):
        dm = interpolate_cubic_hermite_derivative(v1, d1, v2, d2, gaussXi4[i])
        arc_length += gaussWt4[i] * math.sqrt(sum(d * d for d in dm))
    return arc_length


def get_cubic_hermite_arc_length_to_xi(v1, d1, v2, d2, xi):
    """
    Note this is approximate.
    :return: Arc length of cubic curve up to given xi coordinate.
    """
    d1m = [d * xi for d in d1]
    v2m = interpolate_cubic_hermite(v1, d1, v2, d2, xi)
    d2m = interpolate_cubic_hermite_derivative(v1, d1, v2, d2, xi)
    d2m = [d * xi for d in d2m]
    return get_cubic_hermite_arc_length(v1, d1m, v2m, d2m)


def get_cubic_hermite_curves_point_at_arc_distance(nx, nd, arc_distance):
    """
    Get the coordinates, derivatives at distance along cubic Hermite curves.
    Supplied derivatives are used i.e. not rescaled to arc length.
    Note this is approximate.
    :param nx: Coordinates of nodes along curves.
    :param nd: Derivatives of nodes along curves.
    :param arc_distance: Distance along curves.
    :return: coordinates, derivatives, element index, xi; clamped to first or last nx if distance is beyond curves
    """
    elements_count = len(nx) - 1
    assert elements_count > 0, 'getCubicHermiteCurvesPointAtArcDistance.  Invalid number of points'
    if arc_distance < 0.0:
        return nx[0], nd[0], 0, 0.0
    length = 0.0
    xi_delta = 1.0E-6
    xi_tol = 1.0E-6
    for e in range(elements_count):
        part_distance = arc_distance - length
        v1 = nx[e]
        d1 = nd[e]
        v2 = nx[e + 1]
        d2 = nd[e + 1]
        arc_length = get_cubic_hermite_arc_length(v1, d1, v2, d2)
        if part_distance <= arc_length:
            xi_last = 100.0
            xi = part_distance / arc_length
            dxi_limit = 0.1
            for iter in range(100):
                xi_last = xi
                dist = get_cubic_hermite_arc_length_to_xi(v1, d1, v2, d2, xi)
                distp = get_cubic_hermite_arc_length_to_xi(v1, d1, v2, d2, xi + xi_delta)
                distm = get_cubic_hermite_arc_length_to_xi(v1, d1, v2, d2, xi - xi_delta)
                if (xi - xi_delta) < 0.0:
                    distm = -distm
                dxi_ddist = 2.0 * xi_delta / (distp - distm)
                dxi = dxi_ddist * (part_distance - dist)
                # print('iter',iter,'xi',xi,'--> dist',dist,'dxi',dxi,'dxi_limit',dxi_limit)
                if dxi > dxi_limit:
                    dxi = dxi_limit
                elif dxi < -dxi_limit:
                    dxi = -dxi_limit
                xi += dxi
                if math.fabs(xi - xi_last) <= xi_tol:
                    # print('converged xi',xi)
                    return interpolate_cubic_hermite(v1, d1, v2, d2, xi), interpolate_cubic_hermite_derivative(v1, d1,
                                                                                                               v2,
                                                                                                               d2,
                                                                                                               xi), e, xi
                if iter in [4, 10, 25, 62]:
                    dxi_limit *= 0.5
            print('getCubicHermiteCurvesPointAtArcDistance Max iters reached:', iter, ': e', e, ', xi', xi,
                  ', closeness', math.fabs(dist - part_distance))
            return v2, d2, e, xi
        length += arc_length
    return nx[-1], nd[-1], elements_count - 1, 1.0


def interpolate_cubic_hermite(v1, d1, v2, d2, xi):
    """
    Get values of cubic Hermite interpolated from v1, d1 to v2, d2.
    :param v1, v2: Values at xi = 0.0 and xi = 1.0, respectively.
    :param d1, d2: Derivatives w.r.t. xi at xi = 0.0 and xi = 1.0, respectively.
    :param xi: Position in curve, nominally in [0.0, 1.0].
    :return: List of interpolated values at xi.
    """
    xi2 = xi * xi
    xi3 = xi2 * xi
    f1 = 1.0 - 3.0 * xi2 + 2.0 * xi3
    f2 = xi - 2.0 * xi2 + xi3
    f3 = 3.0 * xi2 - 2.0 * xi3
    f4 = -xi2 + xi3
    return [(f1 * v1[i] + f2 * d1[i] + f3 * v2[i] + f4 * d2[i]) for i in range(len(v1))]


def interpolate_sample_cubic_hermite(v, d, pe, pxi, psf):
    """
    Partner function to sampleCubicHermiteCurves for interpolating additional variables with
    cubic Hermite basis, at the element indexes, xi coordinates and xi scaling returned from that function.
    Note: this does not work for sampleCubicHermiteCurves with arcLengthDerivatives = False.
    :param v, d: List of values and derivatives to interpolate, either scalar or sequence-of-scalar.
    len(v) == len(d) == number of elements in + 1.
    :param pe, pxi: List if integer element indexes and real xi coordinates giving sample positions into v to
    interpolate linearly. len(pe) == len(pxi) == number of values out.
    Indexes in pe start at 0, and are not checked; sample_cubic_hermite_curve() guarantees these are valid for
    the number of elements passed to it.
    :param psf: List of scale factors dxi(old)/dxi(new). Length same as pe, pxi. Used to convert derivatives
    from old to new xi spacing.
    :return: List of interpolated values, list of interpolated derivatives; scalar or vector as for v, d.
    """
    assert (len(v) > 1) and (len(d) == len(v)), 'interpolate_sample_cubic_hermite. Invalid values v, d'
    values_count_out = len(pe)
    assert (values_count_out > 0) and (
            len(pxi) == values_count_out), 'interpolate_sample_cubic_hermite. Invalid element, xi'
    v_out = []
    d_out = []
    if isinstance(v[0], Sequence):
        for n in range(values_count_out):
            e = pe[n]
            v1 = v[e]
            d1 = d[e]
            v2 = v[e + 1]
            d2 = d[e + 1]
            v_out.append(interpolate_cubic_hermite(v1, d1, v2, d2, pxi[n]))
            d_out.append([psf[n] * d for d in interpolate_cubic_hermite_derivative(v1, d1, v2, d2, pxi[n])])
    else:
        for n in range(values_count_out):
            e = pe[n]
            v1 = [v[e]]
            d1 = [d[e]]
            v2 = [v[e + 1]]
            d2 = [d[e + 1]]
            v_out.append(interpolate_cubic_hermite(v1, d1, v2, d2, pxi[n])[0])
            d_out.append(psf[n] * interpolate_cubic_hermite_derivative(v1, d1, v2, d2, pxi[n])[0])
    return v_out, d_out


def interpolate_sample_linear(v, pe, pxi):
    """
    Partner function to sampleCubicHermiteCurves for linearly interpolating additional variables based on the
    element indexes and element xi coordinates returned from that function.
    :param v: List of scalar values or sequence-of-values to interpolate. len(v) == number of elements in + 1.
    :param pe, pxi: List if integer element indexes and real xi coordinates giving sample positions into v to
    interpolate linearly. len(pe) == len(pxi) == number of values out.
    Indexes in pe start at 0, and are not checked; sample_cubic_hermite_curve() guarantees these are valid for
    the number of elements passed to it.
    :return: List of interpolated values, scalar or vector as for v.
    """
    assert len(v) > 1, 'interpolateSampleLinear. Invalid values v: not enough data'
    values_count_out = len(pe)
    assert (values_count_out > 0) and (len(pxi) == values_count_out), 'interpolate_sample_linear. Invalid element, xi'
    v_out = []
    if isinstance(v[0], Sequence):
        v_len = len(v[0])
        for n in range(values_count_out):
            wp = pxi[n]
            wm = 1.0 - wp
            vp = v[pe[n] + 1]
            vm = v[pe[n]]
            v_out.append([(wm * vm[c] + wp * vp[c]) for c in range(v_len)])
    else:
        for n in range(values_count_out):
            wp = pxi[n]
            wm = 1.0 - wp
            v_out.append(wm * v[pe[n]] + wp * v[pe[n] + 1])
    return v_out


def interpolate_cubic_hermite_derivative(v1, d1, v2, d2, xi):
    """
    Get derivatives of cubic Hermite interpolated from v1, d1 to v2, d2.
    :param v1, v2: Values at xi = 0.0 and xi = 1.0, respectively.
    :param d1, d2: Derivatives w.r.t. xi at xi = 0.0 and xi = 1.0, respectively.
    :param xi: Position in curve, nominally in [0.0, 1.0].
    :return: List of interpolated derivatives at xi.
    """
    xi2 = xi * xi
    f1 = -6.0 * xi + 6.0 * xi2
    f2 = 1.0 - 4.0 * xi + 3.0 * xi2
    f3 = 6.0 * xi - 6.0 * xi2
    f4 = -2.0 * xi + 3.0 * xi2
    return [(f1 * v1[i] + f2 * d1[i] + f3 * v2[i] + f4 * d2[i]) for i in range(len(v1))]


def interpolate_lagrange_hermite_derivative(v1, v2, d2, xi):
    """
    Get derivative at xi for quadratic Lagrange-Hermite interpolation to from v1 to v2, d2.
    :return: List of derivatives w.r.t. xi at xi.
    """
    df1 = -2.0 + 2.0 * xi
    df2 = 2.0 - 2.0 * xi
    df3 = -1.0 + 2.0 * xi
    return [(v1[c] * df1 + v2[c] * df2 + d2[c] * df3) for c in range(len(v1))]


def interpolate_hermite_lagrange_derivative(v1, d1, v2, xi):
    """
    Get derivative at xi for quadratic Hermite-Lagrange interpolation from v1, d1 to v2.
    :return: List of derivatives w.r.t. xi at xi.
    """
    df1 = -2.0 * xi
    df2 = 1 - 2.0 * xi
    df3 = 2.0 * xi
    return [(v1[c] * df1 + d1[c] * df2 + v2[c] * df3) for c in range(len(v1))]


def magnitude(v):
    """
    return: scalar magnitude of vector v
    """
    return math.sqrt(sum(c * c for c in v))


def normalise(v):
    """
    :return: vector v normalised to unit length
    """
    if v == [0., 0., 0.] or v < [0., 0., 0.]:
        v = [1., 1., 1.]
    mag = math.sqrt(sum(c * c for c in v))
    return [c / mag for c in v]


def sample_cubic_hermite_curves(nx, nd1, elements_count_out,
                                add_length_start=0.0, add_length_end=0.0,
                                length_fraction_start=1.0, length_fraction_end=1.0,
                                element_length_start_end_ratio=1.0, arc_length_derivatives=False):
    """
    Get systematically spaced points and derivatives over cubic Hermite interpolated
    curves with nodes nx and derivatives nd1. The first element uses the first two nodes.
    :param nx: Coordinates of nodes along curves.
    :param nd1: Derivatives of nodes along curves.
    :param add_length_start, add_length_end: Extra length to add to start and end elements.
    :param length_fraction_start, length_fraction_end: Fraction of mid element length for
        start and end elements. Can use in addition to add_lengths: If length_fraction
        is 0.5 and add_lengths is derivative/2.0 can blend into known derivative at start
        or end.
    :param element_length_start_end_ratio: Start/end element length ratio, with lengths
        smoothly varying in between. Requires at least 2 elements. Applied in proportion
        to length_fraction_start, length_fraction_end.
    :param arc_length_derivatives: If True each cubic section is rescaled to arc length.
    If False (default), derivatives and distances are used as supplied.
    :return: px[], pd1[], pe[], pxi[], psf[], where pe[] and pxi[] are lists of element indices and
    and xi locations in the 'in' elements to pass to partner interpolateSample functions. psf[] is
    a list of scale factors for converting derivatives from old to new xi coordinates: dxi(old)/dxi(new).
    """
    elements_count_in = len(nx) - 1
    assert (elements_count_in > 0) and (len(nd1) == (elements_count_in + 1)) and \
           (elements_count_out > 0), 'sampleCubicHermiteCurves.  Invalid arguments'
    lengths = [0.0]
    nd1a = []
    nd1b = []
    length = 0.0
    for e in range(elements_count_in):
        if arc_length_derivatives:
            arc_length = compute_cubic_hermite_arc_length(nx[e], nd1[e], nx[e + 1], nd1[e + 1],
                                                          rescale_derivatives=True)
            nd1a.append(set_magnitude(nd1[e], arc_length))
            nd1b.append(set_magnitude(nd1[e + 1], arc_length))
        else:
            arc_length = get_cubic_hermite_arc_length(nx[e], nd1[e], nx[e + 1], nd1[e + 1])
        length += arc_length
        lengths.append(length)
    proportion_end = 2.0 / (element_length_start_end_ratio + 1)
    proportion_start = element_length_start_end_ratio * proportion_end
    if elements_count_out == 1:
        element_length_mid = length
    else:
        element_length_mid = (length - add_length_start - add_length_end) / \
                             (
                                     elements_count_out - 2.0 + proportion_start * length_fraction_start + proportion_end * length_fraction_end)
    element_length_proportion_start = proportion_start * length_fraction_start * element_length_mid
    element_length_proportion_end = proportion_end * length_fraction_end * element_length_mid
    # get smoothly varying element lengths, not accounting for start and end
    if (elements_count_out == 1) or (element_length_start_end_ratio == 1.0):
        element_lengths = [element_length_mid] * elements_count_out
    else:
        element_lengths = []
        for e_out in range(elements_count_out):
            xi = e_out / (elements_count_out - 1)
            element_lengths.append(((1.0 - xi) * proportion_start + xi * proportion_end) * element_length_mid)
    # get middle derivative magnitudes
    node_derivative_magnitudes = [None] * (elements_count_out + 1)  # start and end determined below
    for n in range(1, elements_count_out):
        node_derivative_magnitudes[n] = 0.5 * (element_lengths[n - 1] + element_lengths[n])
    # fix end lengths:
    element_lengths[0] = add_length_start + element_length_proportion_start
    element_lengths[-1] = add_length_end + element_length_proportion_end
    # print('\nsampleCubicHermiteCurves:')
    # print('  element_lengths', element_lengths, 'addLengthStart', addLengthStart, 'addLengthEnd', addLengthEnd)
    # print('  sum lengths', sum(element_lengths), 'vs. length', length, 'diff', sum(element_lengths) - length)
    # set end derivatives:
    if elements_count_out == 1:
        node_derivative_magnitudes[0] = node_derivative_magnitudes[1] = element_lengths[0]
    else:
        node_derivative_magnitudes[0] = element_lengths[0] * 2.0 - node_derivative_magnitudes[1]
        node_derivative_magnitudes[-1] = element_lengths[-1] * 2.0 - node_derivative_magnitudes[-2]

    px = []
    pd1 = []
    pe = []
    pxi = []
    psf = []
    distance = 0.0
    e = 0
    for e_out in range(elements_count_out):
        while e < elements_count_in:
            if distance < lengths[e + 1]:
                part_distance = distance - lengths[e]
                if arc_length_derivatives:
                    xi = part_distance / (lengths[e + 1] - lengths[e])
                    x = interpolate_cubic_hermite(nx[e], nd1a[e], nx[e + 1], nd1b[e], xi)
                    d1 = interpolate_cubic_hermite_derivative(nx[e], nd1a[e], nx[e + 1], nd1b[e], xi)
                else:
                    x, d1, _eIn, xi = get_cubic_hermite_curves_point_at_arc_distance(nx[e:e + 2], nd1[e:e + 2],
                                                                                     part_distance)
                if magnitude(d1) <= 0.:
                    sf = 1.
                    pd1.append([1. * d for d in d1])
                else:
                    sf = node_derivative_magnitudes[e_out] / magnitude(d1)
                    pd1.append([sf * d for d in d1])

                px.append(x)
                pe.append(e)
                pxi.append(xi)
                psf.append(sf)
                break
            e += 1
        distance += element_lengths[e_out]
    e = elements_count_in
    e_out = elements_count_out
    xi = 1.0
    d1 = nd1[e]

    if magnitude(d1) == 0.0 or magnitude(d1) < 0.0:
        d1 = [1., 1., 1.]
    sf = node_derivative_magnitudes[e_out] / magnitude(d1)
    px.append(nx[e])
    pd1.append([sf * d for d in d1])
    pe.append(e - 1)
    pxi.append(xi)
    psf.append(sf)
    return px, pd1, pe, pxi, psf


def smooth_cubic_hermite_derivatives_line(nx, nd1,
                                          fix_all_directions=False,
                                          fix_start_derivative=False, fix_end_derivative=False,
                                          fix_start_direction=False, fix_end_direction=False,
                                          magnitude_scaling_gode=DerivativeScalingMode.ARITHMETIC_MEAN,
                                          instrument=False):
    """
    Modifies derivatives nd1 to be smoothly varying and near arc length.
    Values are treated as being in a line.
    Assumes initial derivatives are zero or reasonable.
    Where directions are smoothed the weighted/harmonic mean is used.
    :param nx: List of coordinates of nodes along curves.
    :param nd1: List of derivatives of nodes along curves.
    :param fix_all_directions: Set to True to only smooth magnitudes, otherwise both direction and magnitude are adjusted.
    :param fixStartDerivative, fix_end_derivative: Set to True to fix derivative direction and magnitude at respective end.
    :param fixStartDirection, fix_end_direction: Set to True to fix direction at respective end.
    Redundant if fixAllDirections or respective fixStart/EndDerivative is True.
    :param magnitude_scaling_gode: A value from enum DerivativeScalingMode specifying
    expression used to get derivative magnitude from adjacent arc lengths.
    :return: Modified nd1
    """
    nodes_count = len(nx)
    elements_count = nodes_count - 1
    assert elements_count > 0, 'smoothCubicHermiteDerivativesLine.  Too few nodes/elements'
    assert len(nd1) == nodes_count, 'smoothCubicHermiteDerivativesLine.  Mismatched number of derivatives'
    arithmetic_mean_magnitude = magnitude_scaling_gode is DerivativeScalingMode.ARITHMETIC_MEAN
    assert arithmetic_mean_magnitude or (magnitude_scaling_gode is DerivativeScalingMode.HARMONIC_MEAN), \
        'smoothCubicHermiteDerivativesLine. Invalid magnitude scaling mode'
    md1 = copy.copy(nd1)
    components_count = len(nx[0])
    component_range = range(components_count)
    if elements_count == 1:
        # special cases for one element
        if not (
                fix_start_derivative or fix_end_derivative or fix_start_direction or fix_end_direction or fix_all_directions):
            # straight line
            delta = [(nx[1][c] - nx[0][c]) for c in component_range]
            return [delta, copy.deepcopy(delta)]
        if fix_all_directions or (fix_start_direction and fix_end_direction):
            # fixed directions, equal magnitude
            arc_length = compute_cubic_hermite_arc_length(nx[0], nd1[0], nx[1], nd1[1], rescale_derivatives=True)
            return [set_magnitude(nd1[0], arc_length), set_magnitude(nd1[1], arc_length)]
    tol = 1.0E-6
    if instrument:
        print('iter 0', md1)
    for iter in range(100):
        lastmd1 = copy.copy(md1)
        arc_lengths = [get_cubic_hermite_arc_length(nx[e], md1[e], nx[e + 1], md1[e + 1]) for e in
                       range(elements_count)]
        # start
        if not fix_start_derivative:
            if fix_all_directions or fix_start_direction:
                mag = 2.0 * arc_lengths[0] - magnitude(lastmd1[1])
                md1[0] = set_magnitude(nd1[0], mag) if (mag > 0.0) else [0.0, 0.0, 0.0]
            else:
                md1[0] = interpolate_lagrange_hermite_derivative(nx[0], nx[1], lastmd1[1], 0.0)
        # middle
        for n in range(1, nodes_count - 1):
            nm = n - 1
            if not fix_all_directions:
                # get mean of directions from point n to points (n - 1) and (n + 1)
                np = n + 1
                dirm = [(nx[n][c] - nx[nm][c]) for c in component_range]
                dirp = [(nx[np][c] - nx[n][c]) for c in component_range]
                # mean weighted by fraction towards that end, equivalent to harmonic mean
                arc_lengthmp = arc_lengths[nm] + arc_lengths[n]
                wm = arc_lengths[n] / arc_lengthmp
                wp = arc_lengths[nm] / arc_lengthmp
                md1[n] = [(wm * dirm[c] + wp * dirp[c]) for c in component_range]
            if arithmetic_mean_magnitude:
                mag = 0.5 * (arc_lengths[nm] + arc_lengths[n])
            else:  # harmonicMeanMagnitude
                mag = 2.0 / (1.0 / arc_lengths[nm] + 1.0 / arc_lengths[n])
            md1[n] = set_magnitude(md1[n], mag)
        # end
        if not fix_end_derivative:
            if fix_all_directions or fix_end_direction:
                mag = 2.0 * arc_lengths[-1] - magnitude(lastmd1[-2])
                md1[-1] = set_magnitude(nd1[-1], mag) if (mag > 0.0) else [0.0, 0.0, 0.0]
            else:
                md1[-1] = interpolate_hermite_lagrange_derivative(nx[-2], lastmd1[-2], nx[-1], 1.0)
        if instrument:
            print('iter', iter + 1, md1)
        dtol = tol * sum(arc_lengths) / len(arc_lengths)
        for n in range(nodes_count):
            for c in component_range:
                if math.fabs(md1[n][c] - lastmd1[n][c]) > dtol:
                    break
            else:
                continue
            break
        else:
            if instrument:
                print('smoothCubicHermiteDerivativesLine converged after iter:', iter + 1)
            return md1

    cmax = 0.0
    for n in range(nodes_count):
        for c in component_range:
            cmax = max(cmax, math.fabs(md1[n][c] - lastmd1[n][c]))
    closeness = cmax / dtol
    print('smoothCubicHermiteDerivativesLine max iters reached:', iter + 1, ', cmax = ', round(closeness, 2),
          'x tolerance')
    return md1

# def set_magnitude(v, mag):
#     """
#     return: Vector v with magnitude set to mag.
#     """
#     if v == [0., 0., 0.] or v < [0., 0., 0.]:
#         v = [1., 1., 1.]
#     scale = mag / math.sqrt(sum(c * c for c in v))
#     return [c * scale for c in v]
