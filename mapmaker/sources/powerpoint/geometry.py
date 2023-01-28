#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019 - 2022  David Brooks
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

import math

#===============================================================================

# https://simoncozens.github.io/beziers.py/index.html
from beziers.cubicbezier import CubicBezier
from beziers.path import BezierPath
from beziers.point import Point as BezierPoint
from beziers.quadraticbezier import QuadraticBezier

from pptx.shapes.base import BaseShape as PptxShape
import shapely.geometry
from svgwrite.path import Path as SvgPath

#===============================================================================

from mapmaker.geometry import ellipse_point, Transform
from mapmaker.geometry.beziers import bezier_sample
from mapmaker.geometry.arc_to_bezier import bezier_segments_from_arc_endpoints, tuple2
from mapmaker.utils import log

from .formula import Geometry, radians_from_st_angle
from .presets import DRAWINGML
from .transform import DrawMLTransform

#===============================================================================

def get_shape_geometry(shape: PptxShape, transform: Transform, properties=None):
#===============================================================================
##
## Returns shape's geometry as `shapely` object.
##
    closed = False
    coordinates = []
    bezier_segments = []
    pptx_geometry = Geometry(shape)
    svg_path = SvgPath(id=shape.shape_id, fill='none', class_='non-scaling-stroke')
    for path in pptx_geometry.path_list:
        bbox = (shape.width, shape.height) if path.w is None or path.h is None else (path.w, path.h)
        T = transform@DrawMLTransform(shape, bbox)

        current_point = []
        first_point = None
        moved = False

        for c in path.getchildren():
            if   c.tag == DRAWINGML('arcTo'):
                (wR, hR) = ((pptx_geometry.attrib_value(c, 'wR'),
                             pptx_geometry.attrib_value(c, 'hR')))
                stAng = radians_from_st_angle(pptx_geometry.attrib_value(c, 'stAng'))
                swAng = radians_from_st_angle(pptx_geometry.attrib_value(c, 'swAng'))
                p1 = ellipse_point(wR, hR, stAng)
                p2 = ellipse_point(wR, hR, stAng + swAng)
                pt = (current_point[0] - p1[0] + p2[0],
                      current_point[1] - p1[1] + p2[1])
                large_arc_flag = 1 if swAng >= math.pi else 0
                segs = bezier_segments_from_arc_endpoints(tuple2(wR, hR),
                                    0, large_arc_flag, 1,
                                    tuple2(*current_point), tuple2(*pt),
                                    T)
                bezier_segments.extend(segs)
                coordinates.extend(bezier_sample(BezierPath.fromSegments(segs)))
                phi = math.degrees(T.rotate_angle(0))
                sweep_angle = 1 if abs(phi) <= 90 else 0
                svg_path.push('A', *T.scale_length((wR, hR)),
                                   phi, large_arc_flag, sweep_angle,
                                   *T.transform_point(pt))
                current_point = pt

            elif c.tag == DRAWINGML('close'):
                if first_point is not None and current_point != first_point:
                    coordinates.append(T.transform_point(first_point))
                svg_path.push('Z')
                closed = True
                first_point = None
                # Close current pptx_geometry and start a new one...

            elif c.tag == DRAWINGML('cubicBezTo'):
                coords = [BezierPoint(*T.transform_point(current_point))]
                svg_coords = []
                for p in c.getchildren():
                    pt = pptx_geometry.point(p)
                    xy = T.transform_point(pt)
                    coords.append(BezierPoint(*xy))
                    svg_coords.extend(xy)
                    current_point = pt
                bz = CubicBezier(*coords)
                bezier_segments.append(bz)
                coordinates.extend(bezier_sample(bz))
                svg_path.push('C', *svg_coords)

            elif c.tag == DRAWINGML('lnTo'):
                if moved:
                    coordinates.append(T.transform_point(current_point))
                    moved = False
                pt = pptx_geometry.point(c.pt)
                xy = T.transform_point(pt)
                coordinates.append(xy)
                svg_path.push('L', *xy)
                current_point = pt

            elif c.tag == DRAWINGML('moveTo'):
                moved = True
                pt = pptx_geometry.point(c.pt)
                xy = T.transform_point(pt)
                svg_path.push('M', *xy)
                if first_point is None:
                    first_point = pt
                current_point = pt

            elif c.tag == DRAWINGML('quadBezTo'):
                coords = [BezierPoint(*T.transform_point(current_point))]
                svg_coords = []
                for p in c.getchildren():
                    pt = pptx_geometry.point(p)
                    xy = T.transform_point(pt)
                    coords.append(BezierPoint(*T.transform_point(pt)))
                    svg_coords.extend(xy)
                    current_point = pt
                bz = QuadraticBezier(*coords)
                bezier_segments.append(bz)
                coordinates.extend(bezier_sample(bz))
                svg_path.push('Q', *svg_coords)

            else:
                log.warning('Unknown path element: {}'.format(c.tag))

    if len(coordinates) and properties is not None and properties.get('closed', False):
        # We return a polygon if flagged as `closed`
        coordinates.append(coordinates[0])
        closed = True

    if properties is not None:
        properties['bezier-segments'] = bezier_segments
        properties['closed'] = closed
        properties['shape-kind'] = pptx_geometry.shape_kind
        properties['svg-element'] = svg_path

    if len(coordinates) == 0:
        return None
    elif closed:
        return shapely.geometry.Polygon(coordinates).buffer(0)
    else:
        return shapely.geometry.LineString(coordinates)

#===============================================================================

