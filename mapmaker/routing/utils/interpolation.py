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
    d1 = normalize(d1)
    d2 = normalize(d2)
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
