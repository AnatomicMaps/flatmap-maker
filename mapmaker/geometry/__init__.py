#===============================================================================
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
#===============================================================================

from math import acos, cos, sin, sqrt, pi as PI
import warnings

#===============================================================================

import numpy as np

import pyproj

import shapely.affinity
import shapely.geometry
from shapely.geometry.base import BaseGeometry
import shapely.ops
import shapely.wkt

import transforms3d

#===============================================================================

from mapmaker.utils import log

# Exports
from .feature_search import FeatureSearch

#===============================================================================

END_MATCH_RATIO = 0.9
ALMOST_TOUCHING = 500
LINE_EXTENSION  = 100

#===============================================================================

def save_geometry(geo, file):
#============================
    with open(file, 'w') as fp:
        fp.write(shapely.wkt.dumps(geo))

#===============================================================================

# Ignore FutureWarning messages from ``pyproj.Proj``.

warnings.simplefilter(action='ignore', category=FutureWarning)

mercator_transformer = pyproj.Transformer.from_proj(
                            pyproj.Proj(init='epsg:3857'),
                            pyproj.Proj(init='epsg:4326'))

warnings.simplefilter(action='default', category=FutureWarning)

def bounds_to_extent(bounds):
#============================
    sw = mercator_transformer.transform(*bounds[:2])
    ne = mercator_transformer.transform(*bounds[2:])
    return (sw[0], sw[1], ne[0], ne[1])

def extent_to_bounds(extent):
#============================
    sw = mercator_transformer.transform(*extent[:2], direction=pyproj.enums.TransformDirection.INVERSE)     # type: ignore
    ne = mercator_transformer.transform(*extent[2:], direction=pyproj.enums.TransformDirection.INVERSE)     # type: ignore
    return (sw[0], sw[1], ne[0], ne[1])

def mercator_transform(geometry):
#================================
    return shapely.ops.transform(mercator_transformer.transform, geometry)

#===============================================================================

class Transform(object):
    def __init__(self, matrix):
        self.__matrix = np.array(matrix)
        self.__shapely_matrix = np.concatenate((self.__matrix[0, 0:2],
                                                self.__matrix[1, 0:2],
                                                self.__matrix[0:2, 2]), axis=None).tolist()

    def __matmul__(self, transform):
        if isinstance(transform, Transform):
            return Transform(self.__matrix@np.array(transform.__matrix))
        else:
            return Transform(self.__matrix@np.array(transform))

    def __str__(self):
        return str(self.__matrix)

    @classmethod
    def Identity(cls):
        return cls(np.identity(3))

    @classmethod
    def scale(cls, scale):
        return cls([[scale, 0, 0], [0, scale, 0], [0, 0, 1]])

    @property
    def matrix(self):
        return self.__matrix

    def flatten(self):
    #=================
        return self.__matrix.flatten()

    def inverse(self):
    #=================
        return Transform(np.linalg.inv(self.__matrix))

    def rotate_angle(self, angle):
    #==============================
        rotation = transforms3d.affines.decompose(self.__matrix)[1]
        theta = acos(rotation[0, 0])
        if rotation[0, 1] >= 0:
            theta = 2*PI - theta
        angle = angle + theta
        while angle >= 2*PI:
            angle -= 2*PI
        return angle

    def scale_length(self, length):
    #==============================
        scaling = transforms3d.affines.decompose(self.__matrix)[2]
        return (abs(scaling[0]*length[0]), abs(scaling[1]*length[1]))

    def transform_extent(self, extent):
    #==================================
        bounds = extent_to_bounds(extent)
        return bounds_to_extent(
            shapely.affinity.affine_transform(shapely.geometry.box(*bounds),
                                              self.__shapely_matrix).bounds)
    def transform_geometry(self, geometry):
    #======================================
       return shapely.affinity.affine_transform(geometry, self.__shapely_matrix)

    def transform_point(self, point) -> tuple[float, float]:
    #=======================================================
        return tuple(self.__matrix@[point[0], point[1], 1.0])[:2]

#===============================================================================

def ellipse_point(a, b, theta):
#==============================
    a_sin_theta = a*sin(theta)
    b_cos_theta = b*cos(theta)
    circle_radius = sqrt(a_sin_theta**2 + b_cos_theta**2)
    return (a*b_cos_theta/circle_radius, b*a_sin_theta/circle_radius)

#===============================================================================

def reflect_point(point, centre):
    return (2.0*centre[0] - point[0], 2.0*centre[1] - point[1])

#===============================================================================

def extend_(p0, p1):
#===================
    """
    Extend the line through ``p0`` and ``p1`` by ``extension``
    past ``p1`` and return the new end point
    """
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    l = sqrt(dx*dx + dy*dy)
    scale = LINE_EXTENSION/l if l != 0 else 1.0
    if l == 0:
        log.error('ZERO extension of divider...')
    p = (p1[0] + scale*dx, p1[1] + scale*dy)
    return p

def extend_line(geometry):
#=========================
    if geometry.geom_type != 'LineString':
        return geometry
    coords = list(geometry.coords)
    if len(coords) == 2:
        return shapely.geometry.LineString([extend_(coords[1], coords[0]),
                                            extend_(coords[0], coords[1])])
    else:
        coords[0] = extend_(coords[2], coords[0])
        coords[-1] = extend_(coords[-3], coords[-1])
        return shapely.geometry.LineString(coords)

#===============================================================================

class LineMatcher(object):
    def __init__(self, first_line):
        self._previous = shapely.geometry.LineString(first_line)
        self._coords = []

    @property
    def coords(self):
        return self._coords

    @property
    def line(self):
        return shapely.geometry.LineString(self._coords)

    @property
    def previous(self):
        return self._previous

    def extend(self, line):
        pt = self._previous.intersection(line)
        if not pt.is_empty:
            where = self._previous.project(pt, True)
            if where >= END_MATCH_RATIO:   # Near previous's end
                self._coords.extend(shapely.ops.substring(self._previous, 0, where, True).coords)
                where = line.project(pt, True)
                if where <= (1.0 - END_MATCH_RATIO):
                    self._previous = shapely.ops.substring(line, where, 1, True)
                elif where >= END_MATCH_RATIO:
                    self._previous = shapely.geometry.LineString(reversed(shapely.ops.substring(line, 0, where, True).coords))
            else:
                return False
        else:
            # Find which line end is closest to previous's end
            end = self._previous.boundary.geoms[1]
            if end.distance(line.boundary.geoms[0]) <= ALMOST_TOUCHING:
                self._coords.extend(self._previous.coords)
                self._previous = line
            elif end.distance(line.boundary.geoms[1]) <= ALMOST_TOUCHING:
                self._coords.extend(self._previous.coords)
                self._previous = shapely.geometry.LineString(reversed(line.coords))
            else:
                return False
        return True

#===============================================================================

def make_boundary(lines):
    line_matcher = LineMatcher(lines[0])
    remainder = lines[1:]
    while len(remainder) > 0:
        for (n, line) in enumerate(remainder):
            if line_matcher.extend(line):
                del remainder[n]
                break
            else:
                if n == (len(remainder) - 1):
                    raise ValueError("Boundary segment doesn't have a close neighbour")
    if line_matcher.extend(lines[0]):
        coords = line_matcher.coords
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        return shapely.geometry.Polygon(coords).buffer(0)
    else:
        raise ValueError("Final boundary segment doesn't have a close neighbour")

#===============================================================================

def extend_divider(divider, end_point, nearest_point):
    bdy = divider.boundary
    coords = list(divider.coords)
    if end_point.distance(bdy.geoms[0]) < 0.001:
        if coords[0] != nearest_point.coords[0]:
            coords.insert(0, nearest_point.coords[0])
        coords.insert(0, extend_(coords[1], coords[0]))
    elif end_point.distance(bdy.geoms[1]) < 0.001:
        if coords[-1] != nearest_point.coords[0]:
            coords.append(nearest_point.coords[0])
        coords.append(extend_(coords[-2], coords[-1]))
    return shapely.geometry.LineString(coords)

def endpoint(point, line):
    bdy = line.boundary
    return (point.distance(bdy[0]) < 0.001
         or point.distance(bdy[1]) < 0.001)

#===============================================================================

def connect_dividers(dividers, debug):
    connectors = []
    for n in range(len(dividers) - 1):
        divider1 = dividers[n]
        for m in range(n + 1, len(dividers)):
            divider2 = dividers[m]
            if divider1.boundary.is_empty and divider2.boundary.is_empty:
                nearest = shapely.ops.nearest_points(divider1, divider2)
                distance = nearest[0].distance(nearest[1])
                if 0 < distance <= ALMOST_TOUCHING:
                    connectors.append(extend_line(shapely.geometry.LineString(nearest)))
                    if debug: print(n, m, 'both rings: connect...')
            elif divider1.boundary.is_empty or divider2.boundary.is_empty:
                if divider1.boundary.is_empty:  # and not divider2.boundary.is_empty
                    half = shapely.ops.substring(divider2, 0.0, 0.5, True)
                    if not half.crosses(divider1):
                        endpoint = divider2.boundary.geoms[0]
                        nearest = shapely.ops.nearest_points(endpoint, divider1)
                        distance = nearest[0].distance(nearest[1])
                        if distance <= ALMOST_TOUCHING:
                            dividers[m] = extend_divider(divider2, nearest[0], nearest[1])
                            divider2 = dividers[m]
                            if debug: print(n, m, '1st is ring: extend 2nd start...')
                    half = shapely.ops.substring(divider2, 0.5, 1.0, True)
                    if not half.crosses(divider1):
                        endpoint = divider2.boundary.geoms[1]
                        nearest = shapely.ops.nearest_points(endpoint, divider1)
                        distance = nearest[0].distance(nearest[1])
                        if distance <= ALMOST_TOUCHING:
                            dividers[m] = extend_divider(divider2, nearest[0], nearest[1])
                            divider2 = dividers[m]
                            if debug: print(n, m, '1st is ring: extend 2nd end...')
                else:   # not divider1.boundary.is_empty and divider2.boundary.is_empty
                    half = shapely.ops.substring(divider1, 0.0, 0.5, True)
                    if not half.crosses(divider2):
                        endpoint = divider1.boundary.geoms[0]
                        nearest = shapely.ops.nearest_points(endpoint, divider2)
                        distance = nearest[0].distance(nearest[1])
                        if distance <= ALMOST_TOUCHING:
                            dividers[n] = extend_divider(divider1, nearest[0], nearest[1])
                            divider1 = dividers[n]
                            if debug: print(n, m, '2nd is ring: extend 1st start...')
                    half = shapely.ops.substring(divider1, 0.5, 1.0, True)
                    if not half.crosses(divider2):
                        endpoint = divider1.boundary.geoms[1]
                        nearest = shapely.ops.nearest_points(endpoint, divider2)
                        distance = nearest[0].distance(nearest[1])
                        if distance <= ALMOST_TOUCHING:
                            dividers[n] = extend_divider(divider1, nearest[0], nearest[1])
                            divider1 = dividers[n]
                            if debug: print(n, m, '2nd is ring: extend 1st end...')
            else:       # not divider1.boundary.is_empty and not divider2.boundary.is_empty
                # Order matters, process divider1 before divider2
                half = shapely.ops.substring(divider1, 0.0, 0.5, True)
                if not half.crosses(divider2):
                    endpoint = divider1.boundary.geoms[0]
                    nearest = shapely.ops.nearest_points(endpoint, divider2)
                    distance = nearest[0].distance(nearest[1])
                    if distance <= ALMOST_TOUCHING:
                        dividers[n] = extend_divider(divider1, nearest[0], nearest[1])
                        divider1 = dividers[n]
                        if debug: print(n, m, 'no rings: extend 1st start...')
                half = shapely.ops.substring(divider1, 0.5, 1.0, True)
                if not half.crosses(divider2):
                    endpoint = divider1.boundary.geoms[1]
                    nearest = shapely.ops.nearest_points(endpoint, divider2)
                    distance = nearest[0].distance(nearest[1])
                    if distance <= ALMOST_TOUCHING:
                        dividers[n] = extend_divider(divider1, nearest[0], nearest[1])
                        divider1 = dividers[n]
                        if debug: print(n, m, 'no rings: extend 1st end...')
                half = shapely.ops.substring(divider2, 0.0, 0.5, True)
                if not half.crosses(divider1):
                    endpoint = divider2.boundary.geoms[0]
                    nearest = shapely.ops.nearest_points(endpoint, divider1)
                    distance = nearest[0].distance(nearest[1])
                    if distance <= ALMOST_TOUCHING:
                        dividers[m] = extend_divider(divider2, nearest[0], nearest[1])
                        divider2 = dividers[m]
                        if debug: print(n, m, 'no rings: extend 2nd start...')
                half = shapely.ops.substring(divider2, 0.5, 1.0, True)
                if not half.crosses(divider1):
                    endpoint = divider2.boundary.geoms[1]
                    nearest = shapely.ops.nearest_points(endpoint, divider1)
                    distance = nearest[0].distance(nearest[1])
                    if distance <= ALMOST_TOUCHING:
                        dividers[m] = extend_divider(divider2, nearest[0], nearest[1])
                        divider2 = dividers[m]
                        if debug: print(n, m, 'no rings: extend 2nd end...')
    return dividers + connectors

#===============================================================================

def normalised_coords(rectangle: BaseGeometry):
    centroid = rectangle.centroid.coords[0]
    coords = rectangle.exterior.coords[:-1]
    top_right = None
    y_max = None
    for n in range(len(coords)):
        if coords[n][0] > centroid[0]:
            if top_right is None or coords[n][1] > y_max:
                top_right = n
                y_max = coords[n][1]
    return np.roll(coords, -top_right, axis=0)  # type: ignore

#===============================================================================
