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

import pptx.shapes.connector
from pptx.enum.shapes import MSO_SHAPE_TYPE

import shapely.geometry
import shapely.ops
import shapely.prepared

from tqdm import tqdm

#===============================================================================

from mapmaker.exceptions import GroupValueError

from mapmaker.flatmap.layers import FeatureLayer

from mapmaker.geometry import connect_dividers, extend_line, make_boundary
from mapmaker.geometry import ellipse_point
from mapmaker.geometry import transform_bezier_samples, transform_point
from mapmaker.geometry import save_geometry
from mapmaker.geometry.arc_to_bezier import path_from_arc, tuple2

from .formula import Geometry, radians
from .parser import parse_layer_directive, parse_shape_markup
from .presets import DML
from .transform import DrawMLTransform

#===============================================================================

class PowerpointSlide(object):
    def __init__(self, source, slide, slide_number):
        self.__flatmap = source.flatmap
        self.__source = source
        self.__slide = slide
        self.__slide_number = slide_number
        self.__transform = source.transform
        self.__id = 'slide-{:02d}'.format(slide_number)
        self.__feature_layer = FeatureLayer(self.__id, source, output_layer=(slide_number==1))
        self.__outline_feature_id = None
        # Get any layer directives
        if slide.has_notes_slide:
            notes_slide = slide.notes_slide
            notes_text = notes_slide.notes_text_frame.text
            if notes_text.startswith('.'):
                layer_directive = parse_layer_directive(notes_text)
                if 'error' in layer_directive:
                    source.error('Slide {}: invalid layer directive: {}'
                                 .format(slide_number, notes_text))
                self.__outline_feature_id = layer_directive.get('outline')
        self.__current_group = []

    @property
    def feature_layer(self):
        return self.__feature_layer

    @property
    def id(self):
        return self.__id

    @property
    def slide(self):
        return self.__slide

    @property
    def slide_id(self):
        return self.__slide.slide_id

    @property
    def slide_number(self):
        return self.__slide_number

    def __add_features(self, group_name, features, outermost=False):
    #===============================================================
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
        child_class = None
        generate_group = False
        single_features = [ feature for feature in features if not feature.has_children ]
        for feature in single_features:
            if feature.get_property('boundary'):
                if outermost:
                    raise ValueError('Boundary elements must be inside a group: {}'.format(feature))
                if feature.geom_type == 'LineString':
                    boundary_lines.append(extend_line(feature.geometry))
                elif feature.geom_type == 'Polygon':
                    if boundary_polygon is not None:
                        raise GroupValueError('Group {} can only have one boundary shape:'.format(group_name), features)
                    boundary_polygon = feature.geometry
                    if not feature.get_property('invisible'):
                        group_features.append(feature)
                cls = feature.get_property('class')
                if cls is not None:
                    if cls != boundary_class:
                        boundary_class = cls
                    else:
                        raise ValueError('Class of boundary shapes have changed in group{}: {}'.format(group_name, feature))
            elif feature.get_property('group'):
                generate_group = True
                child_class = feature.del_property('children')
                grouped_properties.update(feature.copy_properties())
            elif feature.get_property('region'):
                regions.append(self.__flatmap.new_feature(feature.geometry.representative_point(), feature.copy_properties()))
            elif not feature.has_property('markup') or feature.get_property('divider'):
                if feature.geom_type == 'LineString':
                    dividers.append(feature.geometry)
                elif feature.geom_type == 'Polygon':
                    dividers.append(feature.geometry.boundary)
                if not feature.get_property('invisible'):
                    group_features.append(feature)
            elif feature.has_property('class') or not feature.get_property('interior'):
                group_features.append(feature)

        interior_features = []
        for feature in features:
            if feature.get_property('interior') and not feature.get_property('boundary'):
                interior_features.append(feature)

        if boundary_polygon is not None and len(boundary_lines):
            raise GroupValueError("Group {} can't be bounded by both a closed shape and lines:".format(group_name), features)

        elif boundary_polygon is not None or len(boundary_lines):
            if len(boundary_lines):
                if debug_group:
                    save_geometry(shapely.geometry.MultiLineString(boundary_lines), 'boundary_lines.wkt')
                try:
                    boundary_polygon = make_boundary(boundary_lines)
                except ValueError as err:
                    raise GroupValueError('Group {}: {}'.format(group_name, str(err)), features)

            group_features.append(
                self.__flatmap.new_feature(
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
                        region_properties.update(region.copy_properties())
                        group_features.append(self.__flatmap.new_feature(polygon, region_properties))
                        break
        else:
            for feature in features:
                if feature.get_property('region'):
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
                if (feature.has_property('markup')
                and feature.get_property('exterior')
                and feature.geom_type in ['Polygon', 'MultiPolygon']):
                    feature.geometry = feature.geometry.buffer(0).difference(interior_polygon)

        # Construct a MultiPolygon containing all of the group's polygons
        # But only if the group contains a `.group` element...

        feature_group = None  # Our returned Feature
        if generate_group:
            grouped_polygon_features = [ feature for feature in features if feature.has_children ]
            for feature in group_features:
                grouped_polygon_features.append(feature)

            grouped_lines = []
            for feature in grouped_polygon_features:
                if feature.get_property('tile-layer') != 'pathways':
                    if feature.geom_type == 'LineString':
                        grouped_lines.append(feature.geometry)
                    elif feature.geom_type == 'MultiLineString':
                        grouped_lines.extend(list(feature.geometry))
            if len(grouped_lines):
                feature_group = self.__flatmap.new_feature(
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
                feature_group = self.__flatmap.new_feature(
                        shapely.geometry.MultiPolygon(grouped_polygons),
                        grouped_properties, True)
                group_features.append(feature_group)

        # Feature specific properties have precedence over group's

        default_properties = base_properties.copy()
        if child_class is not None:
            # Default class for all of the group's child shapes
            default_properties['class'] = child_class

        for feature in group_features:
            if feature.geometry is not None:
                for (key, value) in default_properties.items():
                    if not feature.has_property(key):
                        feature.set_property(key, value)
                feature.set_property('geometry', feature.geometry.geom_type)
                self.__feature_layer.add_feature(feature)

        return feature_group

    def process(self):
    #=================
        self.__current_group.append('SLIDE')
        features = self.process_shape_list(self.slide.shapes, self.__transform, outermost=True)
        self.__add_features('Slide', features, True)

    def process_group(self, group, properties, transform):
    #=====================================================
        features = self.process_shape_list(group.shapes, transform@DrawMLTransform(group).matrix())
        return self.__add_features(properties.get('shape_name', ''), features)

    def process_shape(self, shape, properties, transform):
    #=====================================================
    ##
    ## Returns shape's geometry as `shapely` object.
    ##
        coordinates = []
        pptx_geometry = Geometry(shape)
        for path in pptx_geometry.path_list:
            bbox = (shape.width, shape.height) if path.w is None or path.h is None else (path.w, path.h)
            T = transform@DrawMLTransform(shape, bbox).matrix()

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
                    path = path_from_arc(tuple2(wR, hR), 0, large_arc_flag, 1,
                                         tuple2(*current_point), tuple2(*pt))
                    coordinates.extend(transform_bezier_samples(T, path))
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


    def process_shape_list(self, shapes, transform, outermost=False):
    #================================================================
        if outermost:
            progress_bar = tqdm(total=len(shapes),
                unit='shp', ncols=40,
                bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}')

        features = []
        for shape in shapes:
            properties = {'tile-layer': 'features'}   # Passed through to map viewer
            if shape.name.startswith('.'):
                group_name = self.__current_group[-1]  # For error reporting
                properties.update(parse_shape_markup(shape.name))
                if 'error' in properties:
                    self.__source.error('Shape in slide {}, group {}, has annotation syntax error: {}'
                                        .format(self.__slide_number, group_name, shape.name))
                if 'warning' in properties:
                    self.__source.error('Warning, slide {}, group {}: {}'
                                        .format(self.__slide_number, group_name, properties['warning']))
                for key in ['id', 'path']:
                    if key in properties:
                        if self.__flatmap.is_duplicate_feature_id(properties[key]):
                           self.__source.error('Shape in slide {}, group {}, has a duplicate id: {}'
                                               .format(self.__slide_number, group_name, shape.name))
            if 'error' in properties:
                pass
            elif 'path' in properties:
                pass
            elif (shape.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE
             or shape.shape_type == MSO_SHAPE_TYPE.FREEFORM
             or isinstance(shape, pptx.shapes.connector.Connector)):
                geometry = self.process_shape(shape, properties, transform)
                feature = self.__flatmap.new_feature(geometry, properties)
                if self.__feature_layer.output_layer and not feature.get_property('group'):
                    # Save relationship between id/class and internal feature id
                    self.__flatmap.save_feature_id(feature)
                if properties.get('id', '') == self.__outline_feature_id:
                    self.__feature_layer.outline_feature_id = feature.feature_id
                features.append(feature)
            elif shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                self.__current_group.append(properties.get('shape_name', "''"))
                grouped_feature = self.process_group(shape, properties, transform)
                self.__current_group.pop()
                if grouped_feature is not None:
                    if self.__feature_layer.output_layer:
                        self.__flatmap.save_feature_id(grouped_feature)
                    features.append(grouped_feature)
            elif (shape.shape_type == MSO_SHAPE_TYPE.TEXT_BOX
               or shape.shape_type == MSO_SHAPE_TYPE.PICTURE):
                pass
            else:
                print('"{}" {} not processed...'.format(shape.name, str(shape.shape_type)))
            if outermost:
                progress_bar.update(1)

        if outermost:
            progress_bar.close()
        return features
