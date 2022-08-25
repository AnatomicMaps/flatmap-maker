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

from __future__ import annotations

#===============================================================================

from beziers.cubicbezier import CubicBezier
from beziers.path import BezierPath
from beziers.point import Point as BezierPoint
from beziers.segment import Segment as BezierSegment

import shapely.geometry

#===============================================================================

def coords_to_point(pt: tuple[float]) -> BezierPoint:
    return BezierPoint(*pt)

def point_to_coords(pt: BezierPoint) -> tuple[float, float]:
    return (pt.x, pt.y)

#===============================================================================

def width_along_line(geometry, point: BezierPoint, dirn: BezierPoint) -> float:
#==============================================================================
    """
    Find the width of a node by getting the length of the line through an internal
    point in a given direction.
    """
    bounds = geometry.bounds
    max_width = shapely.geometry.Point(*bounds[0:2]).distance(shapely.geometry.Point(*bounds[2:4]))
    line = shapely.geometry.LineString([point_to_coords(point - dirn*max_width),
                                        point_to_coords(point + dirn*max_width)])
    if geometry.intersects(line):
        intersection = geometry.boundary.intersection(line)
        if isinstance(intersection, shapely.geometry.MultiPoint):
            intersecting_points = intersection.geoms
            if len(intersecting_points) == 2:
                return intersecting_points[0].distance(intersecting_points[1])
    return 0

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

def bezier_to_line_coords(bz, num_points=100, offset=0):
#=======================================================
    line = bezier_to_linestring(bz, num_points=num_points, offset=offset)
    if 'Multi' not in line.geom_type:
        return line.coords
    coords = []
    for l in line.geoms:
        coords.extend(l.coords if offset >= 0 else reversed(l.coords))
    return coords

#===============================================================================

def bezier_connect(a: BezierPoint, b: BezierPoint, start_angle: float, end_angle: float = None) -> CubicBezier:
    # Connect points ``a`` and ``b`` with a Bezier curve with a slope
    # at ``a`` of ``theta`` and a slope at ''b'' of ``pi + theta``.
    d = a.distanceFrom(b)
    if d == 0:
        return
    if end_angle is None:
        end_angle = start_angle
    return CubicBezier(a, a + BezierPoint.fromAngle(start_angle)*d/3,
                       b - BezierPoint.fromAngle(end_angle)*d/3, b)

#===============================================================================

def closest_time(bz: BezierSegment | BezierPath, pt: BezierPoint, steps: int = 100) -> float:
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

#===============================================================================

def set_bezier_path_end_to_point(bz_path: BezierPath, point: BezierPoint) -> float:
    segments = bz_path.asSegments()
    # Find path end closest to point
    if point.distanceFrom(bz_path.pointAtTime(0.0)) < point.distanceFrom(bz_path.pointAtTime(1.0)):
        # Start is closest
        segments[0][0] = point
        return 0.0
    else:
        # End is closest
        segments[-1][-1] = point
        return 1.0

#===============================================================================

def split_bezier_path_at_point(bz_path: BezierPath, point: BezierPoint):
    segments = bz_path.asSegments()
    for n, segment in enumerate(segments):
        if (t := closest_time(segment, point)) < 1.0:
            (s0, s1) = segment.splitAtTime(t)
            return (BezierPath.fromSegments(segments[:n] + [s0]),
                    BezierPath.fromSegments([s1] + segments[n+1:]))
    return (bz_path,
            BezierPath.fromSegments(segments[-1].splitAtTime(1.0)[1:]))

#===============================================================================
