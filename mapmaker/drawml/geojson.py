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

import copy
import json
import math
import os

#===============================================================================

# https://simoncozens.github.io/beziers.py/index.html
from beziers.cubicbezier import CubicBezier
from beziers.point import Point as BezierPoint
from beziers.quadraticbezier import QuadraticBezier

import cv2

import numpy as np

import shapely.affinity
import shapely.geometry
import shapely.ops
import shapely.prepared

#===============================================================================

from parser import Parser

from flatmap import MapLayer

from geometry import connect_dividers, extend_line, make_boundary
from geometry import mercator_transform, mercator_transformer
from geometry import transform_bezier_samples, transform_point
from geometry import save_geometry

from .arc_to_bezier import cubic_beziers_from_arc, tuple2
from .mapmaker import Feature, FeaturesValueError
from .mapmaker import MapMaker, SlideLayer, Transform
from .mapmaker import ellipse_point
from .formula import Geometry, radians
from .presets import DML

#===============================================================================

METRES_PER_EMU = 0.1   ## This to become a command line parameter...
                       ## Or in a specification file...
#===============================================================================

class GeoJsonOutput(object):

    def initialise_geojson_output(self):
    #===================================
        self.__geojson_layers = {
            'features': [],
            'pathways': []
        }

    def save(self, map_dir):
    #=======================
        return { layer_id: self.save_as_collection_(map_dir, layer_id)
                    for layer_id in self.__geojson_layers}

    def save_as_collection_(self, map_dir, layer_id):
    #================================================
        # Tippecanoe doesn't need a FeatureCollection
        # Delimit features with RS...LF   (RS = 0x1E)
        filename = os.path.join(map_dir, '{}_{}.json'.format(self.id, layer_id))
        with open(filename, 'w') as output_file:
            for feature in self.__geojson_layers.get(layer_id, []):
                output_file.write('\x1E{}\x0A'.format(json.dumps(feature)))
        return filename

    def save_geo_features(self, map_area):
    #=====================================
        for feature in self.geo_features:
            properties = feature.properties
            source_layer = '{}-{}'.format(self.id, feature.properties['tile-layer'])
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
            if 'maxzoom' in properties:
                geojson['tippecanoe']['maxzoom'] = properties['maxzoom']
            if 'minzoom' in properties:
                geojson['tippecanoe']['minzoom'] = properties['minzoom']
            if area > 0:
                scale = math.log(math.sqrt(map_area/area), 2)
                geojson['properties']['scale'] = scale
                if scale > 6 and 'group' not in properties and 'minzoom' not in properties:
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
                self.__geojson_layers['pathways'].append(geojson)
            else:
                self.__geojson_layers['features'].append(geojson)

#===============================================================================

class GeoJsonLayer(GeoJsonOutput, SlideLayer):
    def __init__(self, mapmaker, slide, slide_number):
        super().__init__(mapmaker, slide, slide_number)
        self.__transform = mapmaker.transform

    def new_feature_(self, geometry, properties, has_children=False):
    #================================================================
        return Feature(self.next_local_id(), geometry, properties, has_children)

    def process_initialise(self):
    #============================
        super().process_initialise()
        self.initialise_geojson_output()

    def process(self):
    #=================
        self.process_initialise()
        features = self.process_shape_list(self.slide.shapes, self.__transform, outermost=True)
        self.add_geo_features_('Slide', features, True)
        self.process_finialise()

    def process_group(self, group, properties, transform):
    #=====================================================
        features = self.process_shape_list(group.shapes, transform@Transform(group).matrix())
        return self.add_geo_features_(properties.get('shape_name', ''), features)

    def add_geo_features_(self, group_name, features, outermost=False):
    #==================================================================
        base_properties = {
            'tile-layer': 'features'
            }

        group_features = []
        grouped_properties = {
            'group': True,
            'interior': True,
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
                # Feature specific properties have precedence over group's
                for (key, value) in base_properties.items():
                    if key not in feature.properties:
                        feature.properties[key] = value
                feature.properties['geometry'] = feature.geometry.geom_type
                self.add_geo_feature(feature)

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

class DetailsLayer(GeoJsonOutput, MapLayer):
    def __init__(self, id):
        MapLayer.__init__(self, id)
        self.initialise_geojson_output()

#===============================================================================

class GeoJsonMaker(MapMaker):
    def __init__(self, pptx, settings):
        super().__init__(pptx, settings)
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

    def latlng_bounds(self):
    #=======================
        bounds = super().bounds()
        top_left = mercator_transformer.transform(*transform_point(self.__transform, (bounds[0], bounds[1])))
        bottom_right = mercator_transformer.transform(*transform_point(self.__transform, (bounds[2], bounds[3])))
        # southwest and northeast corners
        return (top_left[0], bottom_right[1], bottom_right[0], top_left[1])

    def slide_to_layer(self, slide_number):
    #======================================
        slide = self.get_slide(slide_number)
        layer = GeoJsonLayer(self, slide, slide_number)
        print('Slide {}, layer {}'.format(slide_number, layer.id))
        layer.process()
        return layer

    def add_detail_features(self, layer, detail_layer, lowres_features, layers_dict):
    #================================================================================
        extra_details = []
        for feature in lowres_features:
            hires_layer = layers_dict.get(feature.properties['details'])
            if hires_layer is None:
                raise KeyError("Cannot find details' layer '{}'".format(feature.properties['details']))

            outline_feature = hires_layer.features_with_id.get(hires_layer.outline_feature_id)
            if outline_feature is None:
                raise KeyError("Cannot find outline feature '{}'".format(hires_layer.outline_feature_id))

            # Calculate ``shapely.affinity`` 2D affine transform matrix to map source shapes to the destination

            # NOTE: We have no way of ensuring that the vertices of the source and destination rectangles
            #       align as intended. As a result, output features might be rotated by some multiple
            #       of 90 degrees.

            src = np.array(outline_feature.geometry.minimum_rotated_rectangle.exterior.coords, dtype = "float32")[:-1]
            dst = np.array(feature.geometry.minimum_rotated_rectangle.exterior.coords, dtype = "float32")[:-1]
            M = cv2.getPerspectiveTransform(src, dst)
            transform = np.concatenate((M[0][0:2], M[1][0:2], M[0][2], M[1][2]), axis=None).tolist()

            # Set the feature's geometry to that of the high-resolution outline

            feature.geometry = shapely.affinity.affine_transform(outline_feature.geometry, transform)
            minzoom = feature.properties['maxzoom'] + 1

##            layer.add_image_layer('{}-{}'.format(hires_layer.id, feature.id).replace('#', '_'),
##                                  hires_layer.slide_number,
##                                  minzoom,
##                                  bounding_box=outline_feature.geometry.bounds,
##                                  image_transform=M)

            # The detail layer gets a scaled copy of each high-resolution feature

            external_id = feature.properties.get('external-id', '')
            for f in hires_layer.geo_features:

                hires_feature = Feature(f.id, shapely.affinity.affine_transform(f.geometry, transform), f.properties)
                ## need to update hires_feature.id (from f.id ??)
                ## and hires_feature.properties['id']

                hires_feature.properties['minzoom'] = minzoom
                if external_id != '' and 'external-id' in hires_feature.properties:
                    hires_feature.properties['external-id'] = '{}/{}'.format(external_id,
                                                                             hires_feature.properties['external-id'])
                detail_layer.add_geo_feature(hires_feature)
                if hires_feature.has('details'):
                    extra_details.append(hires_feature)

        # If hires features that we've just added also have details then add them
        # to the detail layer

        if extra_details:
            self.add_detail_features(layer, detail_layer, extra_details, layers_dict)

    def resolve_details(self, layers_dict):
    #======================================
        # Generate a details layer for layer with detail features

        ## Need image layers...
        ##
        ## have Image of slide with outline image and outline's BBOX
        ## so can get Rect with just outline. Transform to match detail's feature.
        ##
        ## set layer.__image from slide when first making??
        ## Also want image layers scaled and with minzoom set...

        print('Resolving details...')
        detail_layers = []
        for layer in layers_dict.values():
            if not layer.hidden and layer.detail_features:
                detail_layer = DetailsLayer('{}-details'.format(layer.id))
                detail_layers.append(detail_layer)
                self.add_detail_features(layer, detail_layer, layer.detail_features, layers_dict)
        return detail_layers

#===============================================================================
