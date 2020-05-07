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
import warnings

#===============================================================================

# https://simoncozens.github.io/beziers.py/index.html
from beziers.cubicbezier import CubicBezier
from beziers.point import Point as BezierPoint
from beziers.quadraticbezier import QuadraticBezier

import numpy as np

import pyproj

import shapely.geometry
import shapely.ops
import shapely.prepared

#===============================================================================

from parser import Parser

from .arc_to_bezier import cubic_beziers_from_arc, tuple2
from .extractor import Feature, Extractor, Layer, Transform
from .extractor import ellipse_point
from .formula import Geometry, radians
from .presets import DML

#===============================================================================

AUTO_CLOSE_RATIO = 0.3

#===============================================================================

METRES_PER_EMU = 0.1   ## This to become a command line parameter...
                       ## Or in a specification file...


#===============================================================================

# Ignore FutureWarning messages from ``pyproj.Proj``.

warnings.simplefilter(action='ignore', category=FutureWarning)

mercator_transformer = pyproj.Transformer.from_proj(
                            pyproj.Proj(init='epsg:3857'),
                            pyproj.Proj(init='epsg:4326'))

warnings.simplefilter(action='default', category=FutureWarning)


def mercator_transform(geometry):
#================================
    return shapely.ops.transform(mercator_transformer.transform, geometry)

#===============================================================================

def transform_point(transform, point):
#=====================================
    return (transform@[point[0], point[1], 1.0])[:2]

def transform_bezier_samples(transform, bz):
#===========================================
    samples = 100
    return [transform_point(transform, (pt.x, pt.y)) for pt in bz.sample(samples)]

def extend_(p0, p1, delta):
#==========================
    """
    Extend the line through `p0` and `p1` by `delta`
    and return the new end point
    """
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    l = math.sqrt(dx*dx + dy*dy)
    scale = (delta + l)/l
    return (p1[0] + scale*dx, p1[1] + scale*dy)

def extend_line(geometry, delta):
#================================
    if geometry.geom_type != 'LineString':
        return geometry
    coords = list(geometry.coords)
    if len(coords) == 2:
        return shapely.geometry.LineString([extend_(coords[1], coords[0], delta),
                                            extend_(coords[0], coords[1], delta)])
    else:
        coords[0] = extend_(coords[1], coords[0], delta)
        coords[-1] = extend_(coords[-2], coords[-1], delta)
        return shapely.geometry.LineString(coords)

#===============================================================================

class GeoJsonLayer(Layer):
    def __init__(self, extractor, slide, slide_number):
        super().__init__(extractor, slide, slide_number)
        self.__geo_collection = {}
        self.__geo_features = []
        self.__region_id = 10000
        self.__transform = extractor.transform

    def process(self):
    #=================
        self.__geo_features = []

        features = self.process_shape_list(self._slide.shapes, self.__transform)
        self.add_geo_features_(features, True)

        self.__geo_collection = {
            'type': 'FeatureCollection',
            'id': self.layer_id,
            'creator': 'mapmaker',        # Add version
            'features': self.__geo_features,
            'properties': {
                'id': self.layer_id,
                'description': self.description
            }
        }

    def save(self, filename=None):
    #=============================
        if filename is None:
            filename = os.path.join(self.settings.output_dir, '{}.json'.format(self.layer_id))
        with open(filename, 'w') as output_file:
            json.dump(self.__geo_collection, output_file)

    def process_group(self, group, transform):
    #=========================================
        features = self.process_shape_list(group.shapes, transform@Transform(group).matrix())
        return self.add_geo_features_(features)

    def add_geo_features_(self, features, outermost=False):
    #======================================================
        map_area = self.extractor.map_area()
        divided_area = 0
        base_properties = {'layer': self.layer_id}

        group_features = []
        grouped_properties = {
            'group': True,
            'interior': True,
            'layer': self.layer_id,
        }

        # We first find our boundary polygon(s)
        boundary = None
        boundary_area = 0
        boundary_class = None
        boundary_lines = []
        boundary_polygons = []

        single_features = [ feature for feature in features if not feature.has_children ]
        for feature in single_features:
            if feature.is_a('boundary'):
                if outermost:
                    raise ValueError('Boundary elements must be inside a group: {}'.format(feature))
                if feature.geom_type == 'Polygon':
                    boundary_polygons.append(feature.geometry)
                elif feature.geom_type == 'LineString':
                    boundary_lines.append(extend_line(feature.geometry, self.settings.line_extension))
                cls = feature.property('class')
                if cls is not None:
                    if cls != boundary_class:
                        boundary_class = cls
                    else:
                        raise ValueError('Class of boundary has changed...')
            elif feature.is_a('group'):
                grouped_properties.update(feature.properties)
            elif feature.has('class') or not feature.is_a('interior'):
                group_features.append(feature)

        interior_features = []
        for feature in features:
            if feature.is_a('interior') and not feature.is_a('boundary'):
                interior_features.append(feature)

        if len(boundary_lines):
            for boundary in shapely.ops.polygonize(shapely.ops.unary_union(boundary_lines)):
                boundary_polygons.append(boundary)
        if len(boundary_polygons):
            boundary_polygon = shapely.geometry.MultiPolygon(boundary_polygons)
            boundary_area = boundary_polygon.area
            boundary = boundary_polygon.boundary

        if boundary is not None:
            dividers = [ boundary ]
            group_features = []
            regions = []
            for feature in single_features:
                if feature.is_a('region'):
                    regions.append(Feature(feature.id, feature.geometry.representative_point(), feature.properties))
                elif feature.geom_type == 'LineString':
                    if feature.is_a('boundary') or not feature.has('annotation'):
                        longer_line = extend_line(feature.geometry, self.settings.line_extension)
                        dividers.append(longer_line)
                    if not feature.is_a('invisible'):
                        group_features.append(feature)
                elif feature.geom_type == 'Polygon':
                    if not feature.has('annotation'):
                        dividers.append(feature.geometry.boundary)
                    # Only show divider if not flagged as invisible
                    #if not feature.is_a('invisible'):
                    #    group_features.append(Feature(self.__region_id,
                    #                                  feature.geometry.boundary,
                    #                                  {'layer': self.layer_id} ))
                    #    self.__region_id += 1
                    if feature.is_a('boundary') and not feature.is_a('invisible'):
                        group_features.append(feature)
                elif not feature.is_a('group'):
                    if not feature.is_a('invisible'):
                        group_features.append(feature)
            if dividers:
                for polygon in shapely.ops.polygonize(shapely.ops.unary_union(dividers)):
                    prepared_polygon = shapely.prepared.prep(polygon)
                    region_id = None
                    region_properties = base_properties.copy()
                    for region in filter(lambda p: prepared_polygon.contains(p.geometry), regions):
                        region_id = region.id
                        region_properties.update(region.properties)
                        group_features.append(Feature(region_id, polygon, region_properties))
                        break

        else:
            for feature in features:
                if feature.is_a('region'):
                    raise ValueError('Region dividers must have a boundary')

        if not outermost and interior_features:
            interior_polygons = []
            for feature in interior_features:
                if feature.geom_type == 'Polygon':
                    interior_polygons.append(feature.geometry)
                elif feature.geom_type == 'MultiPolygon':
                    interior_polygons.extend(list(feature.geometry))
            interior_polygon = shapely.ops.unary_union(interior_polygons)
            for feature in group_features:
                if not feature.is_a('interior') and feature.geom_type in ['Polygon', 'MultiPolygon']:
                    feature.geometry = feature.geometry.buffer(0).difference(interior_polygon)

        # Construct a MultiPolygon containing all of the group's polygons
        grouped_features = [ feature for feature in features if feature.has_children ]
        grouped_features.extend( group_features)

        grouped_lines = []
        for feature in grouped_features:
            if feature.geom_type == 'LineString':
                grouped_lines.append(feature.geometry)
            elif feature.geom_type == 'MultiLineString':
                grouped_lines.extend(list(feature.geometry))
        if len(grouped_lines):
            grouped_feature = Feature(self.__region_id,
                                      shapely.geometry.MultiLineString(grouped_lines),
                                      grouped_properties, True)
            group_features.append(grouped_feature)
            self.__region_id += 1

        grouped_polygons = []
        for feature in grouped_features:
            if feature.geom_type == 'Polygon':
                grouped_polygons.append(feature.geometry)
            elif feature.geom_type == 'MultiPolygon':
                grouped_polygons.extend(list(feature.geometry))
        if len(grouped_polygons):
            grouped_feature = Feature(self.__region_id,
                                      shapely.geometry.MultiPolygon(grouped_polygons),
                                      grouped_properties, True)
            group_features.append(grouped_feature)
            self.__region_id += 1

        for feature in group_features:
            unique_id = '{}-{}'.format(self.slide_id, feature.id)
            if feature.geometry is not None:
                # Initial set of properties come from ``.group``
                properties = base_properties.copy()
                # And are overriden by feature specific ones
                properties.update(feature.properties)

                geometry = feature.geometry
                mercator_geometry = mercator_transform(geometry)
                area = geometry.area
                geojson = {
                    'type': 'Feature',
                    'id': feature.id,   # Must be numeric for tipeecanoe
                    'tippecanoe' : {
                        'layer' : properties['layer']
                    },
                    'geometry': shapely.geometry.mapping(mercator_geometry),
                    'properties': {
                        'id': unique_id,
                        'bounds': list(mercator_geometry.bounds),
                        'centroid': list(list(mercator_geometry.centroid.coords)[0]),
                        'area': area,
                        'length': geometry.length,
                    }
                }

                if area > 0:
                    geojson['properties']['scale'] = math.log(math.sqrt(map_area/area), 2)
                else:
                    geojson['properties']['scale'] = 10

                if properties:
                    for (key, value) in properties.items():
                        if not Parser.ignore_property(key):
                            geojson['properties'][key] = value
                    properties['bounds'] = geojson['properties']['bounds']
                    properties['geometry'] = geojson['geometry']['type']
                    self.annotations[unique_id] = properties

                self.__geo_features.append(geojson)
                self.map_features.append({
                    'id': unique_id,
                    'type': geojson['geometry']['type']
                })

        return grouped_feature


    def process_shape(self, shape, properties, transform):
    #=====================================================
    ##
    ## Returns shape's geometry as `shapely` object.
    ##
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


        if closed:
            geometry = shapely.geometry.Polygon(coordinates)
        else:
            geometry = shapely.geometry.LineString(coordinates)
            if not properties.get('open', False):
                # Return a polygon if distance between endpoints < 0.3*(line length)
                delta_ends = shapely.geometry.Point(coordinates[0]).distance(
                                shapely.geometry.Point(coordinates[-1]))
                if delta_ends < AUTO_CLOSE_RATIO*geometry.length:
                    coordinates.append(coordinates[0])
                    return shapely.geometry.Polygon(coordinates)
        return geometry

#===============================================================================

class GeoJsonExtractor(Extractor):
    def __init__(self, pptx, settings):
        super().__init__(pptx, settings, GeoJsonLayer)
        self.__transform = np.array([[METRES_PER_EMU,               0, 0],
                                    [             0, -METRES_PER_EMU, 0],
                                    [             0,               0, 1]])@np.array([[1, 0, -self.slide_size[0]/2.0],
                                                                                     [0, 1, -self.slide_size[1]/2.0],
                                                                                     [0, 0,                      1.0]])
    @property
    def transform(self):
        return self.__transform

    def map_area(self):
    #==================
        bounds = super().bounds()
        top_left = transform_point(self.__transform, (bounds[0], bounds[1]))
        bottom_right = transform_point(self.__transform, (bounds[2], bounds[3]))
        return abs(bottom_right[0] - top_left[0]) * (top_left[1] - bottom_right[1])

    def bounds(self):
    #================
        bounds = super().bounds()
        top_left = mercator_transformer.transform(*transform_point(self.__transform, (bounds[0], bounds[1])))
        bottom_right = mercator_transformer.transform(*transform_point(self.__transform, (bounds[2], bounds[3])))
        return [top_left[0], top_left[1], bottom_right[0], bottom_right[1]]

#===============================================================================
