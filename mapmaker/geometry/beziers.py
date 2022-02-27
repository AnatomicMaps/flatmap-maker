#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2020-2022  David Brooks
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

from typing import List, Tuple

#===============================================================================

from beziers.cubicbezier import CubicBezier
from beziers.path import BezierPath
from beziers.point import Point as BezierPoint
from beziers.segment import Segment as BezierSegment

import shapely.geometry

#===============================================================================

def coords_to_point(pt: Tuple[float]) -> BezierPoint:
    return BezierPoint(*pt)

def point_to_coords(pt: BezierPoint) -> Tuple[float]:
    return (pt.x, pt.y)

#===============================================================================

def bezier_sample(bz, num_points=100):
#=====================================
    return [(pt.x, pt.y) for pt in bz.sample(num_points)]

def bezier_to_linestring(bz, num_points=100, offset=0):
#======================================================
    line = shapely.geometry.LineString(bezier_sample(bz, num_points))
    if offset == 0:
        return line
    else:
        return line.parallel_offset(abs(offset), 'left' if offset >= 0 else 'right')

def bezier_segments_to_linestring(segments: List[BezierSegment],
                                  points: int = 100, offset: float = 0) -> shapely.geometry.LineString:
#======================================================================================================
    if len(segments) == 1:
        return bezier_to_linestring(segments[0], points, offset)
    coords = []
    for segment in segments:
        c = bezier_to_linestring(segment, points, offset).coords
        coords.extend(c if offset >= 0 else reversed(c))
    return shapely.geometry.LineString(coords)

def bezier_connect(a: BezierPoint, b: BezierPoint, start_angle: float, end_angle: float = None) -> CubicBezier:
#==============================================================================================================
    # Connect points ``a`` and ``b`` with a Bezier curve with a slope
    # at ``a`` of ``theta`` and a slope at ''b'' of ``pi + theta``.
    d = a.distanceFrom(b)
    if d == 0:
        return
    if end_angle is None:
        end_angle = start_angle
    return CubicBezier(a, a + BezierPoint.fromAngle(start_angle)*d/3,
                       b - BezierPoint.fromAngle(end_angle)*d/3, b)

def closest_time(bz: BezierPath, pt: BezierPoint, steps: int = 100) -> tuple:
#============================================================================
    def subdivide_search(t0, t1, steps):
        closest_d = None
        closest_t = t0
        delta_t = (t1 - t0)/steps
        for step in range(steps+1):
            t = t0 + step*delta_t
            d = bz.pointAtTime(t).distanceFrom(pt)
            if closest_d is None or d < closest_d:
                closest_t = t
                closest_d = d
        return (closest_t, delta_t, closest_d)
    (t, delta_t) = (0.5, 0.5)
    for n in range(4):
        (t, delta_t, closest) = subdivide_search(t - delta_t, t + delta_t, steps)
    return t

def bezier_polygon_intersection(bz: BezierPath, poly: shapely.geometry.Polygon):
    """
    Intersection between a Bezier path and a polygon.
    """

    line = bezier_to_linestring(bz)
    times = [closest_time(bz, coords_to_point((pt.x, pt.y)))
                for pt in line.intersection(poly.boundary).geoms]

#===============================================================================

