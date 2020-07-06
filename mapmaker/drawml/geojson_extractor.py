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

import numpy as np

import shapely.geometry
import shapely.ops
import shapely.prepared

#===============================================================================

from parser import Parser

from geometry import connect_dividers, extend_line, make_boundary
from geometry import mercator_transform, mercator_transformer
from geometry import transform_bezier_samples, transform_point
from geometry import save_geometry

from .arc_to_bezier import cubic_beziers_from_arc, tuple2
from .extractor import Feature, FeaturesValueError
from .extractor import Extractor, Layer, Transform
from .extractor import ellipse_point
from .formula import Geometry, radians
from .presets import DML

#===============================================================================

METRES_PER_EMU = 0.1   ## This to become a command line parameter...
                       ## Or in a specification file...
#===============================================================================

class GeoJsonLayer(Layer):
    def __init__(self, extractor, slide, slide_number):
        super().__init__(extractor, slide, slide_number)
        self.__geo_features = []
        self.__geo_pathways = []
        self.__transform = extractor.transform

    def new_feature_(self, geometry, properties, has_children=False):
    #================================================================
        return Feature(self.next_local_id(), geometry, properties, has_children)

    def process(self):
    #=================
        self.process_initialise()
        self.__geo_features = []
        self.__geo_pathways = []
        features = self.process_shape_list(self._slide.shapes, self.__transform, outermost=True)
        self.add_geo_features_('Slide', features, True)
        self.process_finialise()

    def save_as_collection_(self, features, layer_type):
    #===================================================
        # Tippecanoe doesn't need a FeatureCollection
        # Delimit features with RS...LF   (RS = 0x1E)
        filename = os.path.join(self.settings.output_dir, '{}_{}.json'.format(self.layer_id, layer_type))
        with open(filename, 'w') as output_file:
            for feature in features:
                output_file.write('\x1E{}\x0A'.format(json.dumps(feature)))
        return filename

    def save(self):
    #==============
        return {
            'features': self.save_as_collection_(self.__geo_features, 'features'),
            'pathways': self.save_as_collection_(self.__geo_pathways, 'pathways')
        }

    def process_group(self, group, properties, transform):
    #=====================================================
        features = self.process_shape_list(group.shapes, transform@Transform(group).matrix())
        return self.add_geo_features_(properties.get('shape_name', ''), features)

    def add_geo_features_(self, group_name, features, outermost=False):
    #==================================================================
        map_area = self.extractor.map_area()

        base_properties = {
            'layer': self.layer_id,
            'tile-layer': 'features'
            }

        group_features = []
        grouped_properties = {
            'group': True,
            'interior': True,
            'layer': self.layer_id,
            'tile-layer': 'features'
        }

        # We first find our boundary polygon(s)
        boundary_class = None
        boundary_lines = []
        boundary_polygon = None
        dividers = []
        regions = []

        debug_group = False
        single_features = [ feature for feature in features if not feature.has_children ]
        for feature in single_features:
            if feature.is_a('boundary'):
                if outermost:
                    raise ValueError('Boundary elements must be inside a group: {}'.format(feature))
                if feature.geom_type == 'LineString':
                    boundary_lines.append(extend_line(feature.geometry))
                elif feature.geom_type == 'Polygon':
                    if boundary_polygon is not None:
                        raise FeaturesValueError('Group {} can only have one boundary shape:'.format(group_name), features)
                    boundary_polygon = feature.geometry
                    if not feature.property('invisible'):
                        group_features.append(feature)
                cls = feature.property('class')
                if cls is not None:
                    if cls != boundary_class:
                        boundary_class = cls
                    else:
                        raise ValueError('Class of boundary shapes have changed in group{}: {}'.format(group_name, feature))
            elif feature.is_a('group'):
                grouped_properties.update(feature.properties)
            elif feature.is_a('region'):
                regions.append(Feature(feature.id, feature.geometry.representative_point(), feature.properties))
            elif not feature.annotated or feature.is_a('divider'):
                if feature.geom_type == 'LineString':
                    dividers.append(feature.geometry)
                elif feature.geom_type == 'Polygon':
                    dividers.append(feature.geometry.boundary)
                if not feature.property('invisible'):
                    group_features.append(feature)
            elif feature.has('class') or not feature.is_a('interior'):
                group_features.append(feature)

        interior_features = []
        for feature in features:
            if feature.is_a('interior') and not feature.is_a('boundary'):
                interior_features.append(feature)

        if boundary_polygon is not None and len(boundary_lines):
            raise FeaturesValueError("Group {} can't be bounded by both a closed shape and lines:".format(group_name), features)

        elif boundary_polygon is not None or len(boundary_lines):
            if len(boundary_lines):
                if debug_group:
                    save_geometry(shapely.geometry.MultiLineString(boundary_lines), 'boundary_lines.wkt')
                try:
                    boundary_polygon = make_boundary(boundary_lines)
                except ValueError as err:
                    raise FeaturesValueError('Group {}: {}'.format(group_name, str(err)), features)

            group_features.append(
                self.new_feature_(
                    boundary_polygon,
                    base_properties))

            if len(dividers):

                # For all line dividers, if the end of a line is 'close to' another line
                # then extend the line end in about the same direction until it touches
                # the other. NB. may need to 'bend towards' the other...
                #
                # And then only add these cleaned up lines as features, not the original dividers

                dividers.append(boundary_polygon.boundary)
                if debug_group:
                    save_geometry(shapely.geometry.MultiLineString(dividers), 'dividers.wkt')

                divider_lines = connect_dividers(dividers, debug_group)
                if debug_group:
                    save_geometry(shapely.geometry.MultiLineString(divider_lines), 'divider_lines.wkt')

                polygon_boundaries = shapely.ops.unary_union(divider_lines)
                if debug_group:
                    save_geometry(polygon_boundaries, 'polygon_boundaries.wkt')

                polygons = list(shapely.ops.polygonize(polygon_boundaries))

                for n, polygon in enumerate(polygons):
                    prepared_polygon = shapely.prepared.prep(polygon)
                    region_id = None
                    region_properties = base_properties.copy()
                    for region in filter(lambda p: prepared_polygon.contains(p.geometry), regions):
                        region_properties.update(region.properties)
                        group_features.append(Feature(region.id, polygon, region_properties))
                        break
        else:
            for feature in features:
                if feature.is_a('region'):
                    raise ValueError('Region dividers in group {} must have a boundary: {}'.format(group_name, feature))

        if not outermost and interior_features:
            interior_polygons = []
            for feature in interior_features:
                if feature.geom_type == 'Polygon':
                    interior_polygons.append(feature.geometry)
                elif feature.geom_type == 'MultiPolygon':
                    interior_polygons.extend(list(feature.geometry))
            interior_polygon = shapely.ops.unary_union(interior_polygons)
            for feature in group_features:
                if (feature.annotated
                and not feature.is_a('interior')
                and feature.geom_type in ['Polygon', 'MultiPolygon']):
                    feature.geometry = feature.geometry.buffer(0).difference(interior_polygon)

        # Construct a MultiPolygon containing all of the group's polygons
        grouped_polygon_features = [ feature for feature in features if feature.has_children ]
        for feature in group_features:
            grouped_polygon_features.append(feature)

        feature_group = None  # Our returned Feature
        grouped_lines = []
        for feature in grouped_polygon_features:
            if feature.properties.get('tile-layer') != 'pathways':
                if feature.geom_type == 'LineString':
                    grouped_lines.append(feature.geometry)
                elif feature.geom_type == 'MultiLineString':
                    grouped_lines.extend(list(feature.geometry))
        if len(grouped_lines):
            feature_group = self.new_feature_(
                  shapely.geometry.MultiLineString(grouped_lines),
                  grouped_properties, True)
            group_features.append(feature_group)
        grouped_polygons = []
        for feature in grouped_polygon_features:
            if feature.geom_type == 'Polygon':
                grouped_polygons.append(feature.geometry)
            elif feature.geom_type == 'MultiPolygon':
                grouped_polygons.extend(list(feature.geometry))
        if len(grouped_polygons):
            feature_group = self.new_feature_(
                    shapely.geometry.MultiPolygon(grouped_polygons),
                    grouped_properties, True)
            group_features.append(feature_group)

        # Add polygon features for nerve cuffs
        nerve_polygons = []
        for feature in group_features:
            if (feature.properties.get('type') == 'nerve'
            and feature.geom_type == 'LineString'):
                nerve_id = feature.id
                nerve_polygon_feature = self.new_feature_(
                    shapely.geometry.Polygon(feature.geometry.coords), feature.properties)
                if 'models' in nerve_polygon_feature.properties:
                    del nerve_polygon_feature.properties['models']
                nerve_polygon_feature.properties['nerve-id'] = nerve_id
                nerve_polygons.append(nerve_polygon_feature)
        group_features.extend(nerve_polygons)

        for feature in group_features:
            if feature.geometry is not None:
                # Initial set of properties come from ``.group``
                properties = base_properties.copy()
                # And are overriden by feature specific ones
                properties.update(feature.properties)
                source_layer = '{}-{}'.format(properties['layer'], properties['tile-layer'])
                properties['source-layer'] = source_layer
                geometry = feature.geometry
                area = geometry.area
                mercator_geometry = mercator_transform(geometry)
                geojson = {
                    'type': 'Feature',
                    'id': int(feature.feature_id),   # Must be numeric for tipeecanoe
                    'tippecanoe' : {
                        'layer' : source_layer
                    },
                    'geometry': shapely.geometry.mapping(mercator_geometry),
                    'properties': {
                        'bounds': list(mercator_geometry.bounds),
                        # The viewer requires `centroid`
                        'centroid': list(list(mercator_geometry.centroid.coords)[0]),
                        'area': area,
                        'length': geometry.length,
                        'layer': source_layer,
                    }
                }

                if area > 0:
                    scale = math.log(math.sqrt(map_area/area), 2)
                    geojson['properties']['scale'] = scale
                    if scale > 6 and 'group' not in properties:
                        geojson['tippecanoe']['minzoom'] = 5
                else:
                    geojson['properties']['scale'] = 10

                if properties:
                    for (key, value) in properties.items():
                        if not Parser.ignore_property(key):
                            geojson['properties'][key] = value
                    properties['bounds'] = geojson['properties']['bounds']
                    properties['centroid'] = geojson['properties']['centroid']
                    properties['geometry'] = geojson['geometry']['type']
                    self.annotations[feature.id] = properties

                if properties['tile-layer'] == 'pathways':
                    self.__geo_pathways.append(geojson)
                else:
                    self.__geo_features.append(geojson)

                self.map_features.append({
                    'id': feature.id,
                    'type': geojson['geometry']['type']
                })
        return feature_group

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
            if properties.get('closed', False):
                # Return a polygon if flagged as `closed`
                coordinates.append(coordinates[0])
                return shapely.geometry.Polygon(coordinates)
        return geometry

#===============================================================================

class GeoJsonExtractor(Extractor):
    def __init__(self, pptx, settings):
        super().__init__(pptx, settings, GeoJsonLayer)
        bounds = super().bounds()
        self.__transform = np.array([[METRES_PER_EMU,               0, 0],
                                    [              0, -METRES_PER_EMU, 0],
                                    [              0,               0, 1]])@np.array([[1, 0, -bounds[2]/2.0],
                                                                                      [0, 1, -bounds[3]/2.0],
                                                                                      [0, 0,            1.0]])
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
