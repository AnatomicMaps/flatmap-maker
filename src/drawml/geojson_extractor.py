#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019  David Brooks
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

import json
import math
import os

#===============================================================================

# https://simoncozens.github.io/beziers.py/index.html
from beziers.cubicbezier import CubicBezier
from beziers.point import Point as BezierPoint
from beziers.quadraticbezier import QuadraticBezier

import mercantile

import numpy as np

#===============================================================================

from .arc_to_bezier import cubic_beziers_from_arc, tuple2
from .extractor import GeometryExtractor, SlideToLayer, Transform
from .extractor import ellipse_point
from .formula import Geometry, radians
from .presets import DML

#===============================================================================

METRES_PER_EMU = 0.1   ## This to become a command line parameter...
                       ## Or in a specification file...

"""
5.  Bounding Box

   A GeoJSON object MAY have a member named "bbox" to include
   information on the coordinate range for its Geometries, Features, or
   FeatureCollections.  The value of the bbox member MUST be an array of
   length 2*n where n is the number of dimensions represented in the
   contained geometries, with all axes of the most southwesterly point
   followed by all axes of the more northeasterly point.  The axes order
   of a bbox follows the axes order of geometries.

   The "bbox" values define shapes with edges that follow lines of
   constant longitude, latitude, and elevation.

   Example of a 2D bbox member on a Feature:

   {
       "type": "Feature",
       "bbox": [-10.0, -10.0, 10.0, 10.0],
       "geometry": {
           "type": "Polygon",
           "coordinates": [
               [
                   [-10.0, -10.0],
                   [10.0, -10.0],
                   [10.0, 10.0],
                   [-10.0, -10.0]
               ]
           ]
       }
       //...
   }

   Example of a 2D bbox member on a FeatureCollection:

   {
       "type": "FeatureCollection",
       "bbox": [100.0, 0.0, 105.0, 1.0],
       "features": [
       //...
       ]
   }

   Example of a 3D bbox member with a depth of 100 meters:

   {
       "type": "FeatureCollection",
       "bbox": [100.0, 0.0, -100.0, 105.0, 1.0, 0.0],
       "features": [
       //...
       ]
   }

"""

def lat_lon_bounds(coords):
    bounds = []
    for i in (0, 1):
        sorted_coords = sorted(coords, key=lambda x:x[i])
        bounds.append((sorted_coords[0][i], sorted_coords[-1][i]))
    return [bounds[0][0], bounds[1][0], bounds[0][1], bounds[1][1]]

def bounding_box(geometry):
    if geometry['type'] == 'Polygon':
        return lat_lon_bounds(geometry['coordinates'][0])
    elif geometry['type'] == 'LineString':
        return lat_lon_bounds(geometry['coordinates'])

#===============================================================================

def transform_point(transform, point):
    return (transform@[point[0], point[1], 1.0])[:2]

def metres_to_lon_lat(point):
    return mercantile.lnglat(*point)

def points_to_lon_lat(points):
    return [ metres_to_lon_lat(pt) for pt in points ]

def transform_bezier_samples(transform, bz):
    samples = 100
    return [transform_point(transform, (pt.x, pt.y)) for pt in bz.sample(samples)]

#===============================================================================

class MakeGeoJsonLayer(SlideToLayer):
    def __init__(self, extractor, slide, slide_number):
        super().__init__(extractor, slide, slide_number)
        self._transform = extractor.transform

    def process(self):
        self._features = []
        self.process_shape_list(self._slide.shapes, self._transform)
        self._feature_collection = {
            'type': 'FeatureCollection',
            'id': self.layer_id,
            'creator': 'pptx2geo',        # Add version
            'features': self._features,
            'properties': {
                'id': self.layer_id,
                'description': self.description
            }
        }

    def get_output(self):
        return self._feature_collection

    def save(self, filename=None):
        if filename is None:
            filename = os.path.join(self.options.output_dir, '{}.json'.format(self.layer_id))
        with open(filename, 'w') as output_file:
            json.dump(self._feature_collection, output_file)

    def process_group(self, group, transform):
        self.process_shape_list(group.shapes, transform@Transform(group).matrix())

    def process_shape(self, shape, transform):
        feature = {
            'type': 'Feature',
            'id': shape.shape_id,          # Only unique within slide...
            'properties': {
                'id': shape.unique_id
            }
        }
        geometry = {}
        coordinates = []

        pptx_geometry = Geometry(shape)
        for path in pptx_geometry.path_list:
            bbox = (shape.width, shape.height) if path.w is None or path.h is None else (path.w, path.h)
            T = transform@Transform(shape, bbox).matrix()

            moved = False
            first_point = None
            current_point = None
            closed = False

            for c in path.getchildren():
                if   c.tag == DML('arcTo'):
                    wR = pptx_geometry.attrib_value(c, 'wR')
                    hR = pptx_geometry.attrib_value(c, 'hR')
                    stAng = radians(pptx_geometry.attrib_value(c, 'stAng'))
                    swAng = radians(pptx_geometry.attrib_value(c, 'swAng'))
                    p1 = ellipse_point(wR, hR, stAng)
                    p2 = ellipse_point(wR, hR, stAng + swAng)
                    pt = (current_point[0] - p1[0] + p2[0],
                          current_point[1] - p1[1] + p2[1])
                    large_arc_flag = 1 if swAng >= math.pi else 0
                    beziers = cubic_beziers_from_arc(tuple2(wR, hR), 0, large_arc_flag, 1,
                                                     tuple2(*current_point), tuple2(*pt))
                    for bz in beziers:
                        coordinates.extend(transform_bezier_samples(T, bz))
                    current_point = pt

                elif c.tag == DML('close'):
                    if first_point is not None and current_point != first_point:
                        coordinates.append(transform_point(T, first_point))
                    closed = True
                    first_point = None
                    # Close current pptx_geometry and start a new one...

                elif c.tag == DML('cubicBezTo'):
                    coords = [BezierPoint(*current_point)]
                    for p in c.getchildren():
                        pt = pptx_geometry.point(p)
                        coords.append(BezierPoint(*pt))
                        current_point = pt
                    bz = CubicBezier(*coords)
                    coordinates.extend(transform_bezier_samples(T, bz))

                elif c.tag == DML('lnTo'):
                    pt = pptx_geometry.point(c.pt)
                    if moved:
                        coordinates.append(transform_point(T, current_point))
                        moved = False
                    coordinates.append(transform_point(T, pt))
                    current_point = pt

                elif c.tag == DML('moveTo'):
                    pt = pptx_geometry.point(c.pt)
                    if first_point is None:
                        first_point = pt
                    current_point = pt
                    moved = True

                elif c.tag == DML('quadBezTo'):
                    coords = [BezierPoint(*current_point)]
                    for p in c.getchildren():
                        pt = pptx_geometry.point(p)
                        coords.append(BezierPoint(*pt))
                        current_point = pt
                    bz = QuadraticBezier(*coords)
                    coordinates.extend(transform_bezier_samples(T, bz))

                else:
                    print('Unknown path element: {}'.format(c.tag))

        lat_lon = points_to_lon_lat(coordinates)
        if closed:
            geometry['type'] = 'Polygon'
            geometry['coordinates'] = [ lat_lon ]
        else:
            geometry['type'] = 'LineString'
            geometry['coordinates'] = lat_lon

        feature['geometry'] = geometry

        bbox = bounding_box(geometry)
        feature['properties']['bbox'] = ','.join([str(x) for x in bbox])

        self._features.append(feature)
        self._map_features.append({
          'id': shape.unique_id,
          'type': geometry['type']
        })
        return feature

#===============================================================================

class GeoJsonExtractor(GeometryExtractor):
    def __init__(self, pptx, options):
        super().__init__(pptx, options)
        self._LayerMaker = MakeGeoJsonLayer
        self._transform = np.array([[METRES_PER_EMU,               0, 0],
                                    [             0, -METRES_PER_EMU, 0],
                                    [             0,               0, 1]])@np.array([[1, 0, -self._slide_size[0]/2.0],
                                                                                     [0, 1, -self._slide_size[1]/2.0],
                                                                                     [0, 0,                      1.0]])
    @property
    def transform(self):
        return self._transform

    def bounds(self):
        bounds = super().bounds()
        top_left = metres_to_lon_lat(transform_point(self._transform, (bounds[0], bounds[1])))
        bottom_right = metres_to_lon_lat(transform_point(self._transform, (bounds[2], bounds[3])))
        return [top_left[0], top_left[1], bottom_right[0], bottom_right[1]]

#===============================================================================
