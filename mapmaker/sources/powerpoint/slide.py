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

from mapmaker.geometry import ellipse_point
from mapmaker.geometry import transform_bezier_samples, transform_point
from mapmaker.geometry.arc_to_bezier import path_from_arc, tuple2

from ..markup import parse_layer_directive, parse_shape_markup

from .formula import Geometry, radians
from .presets import DML
from .transform import DrawMLTransform

#===============================================================================

class PowerpointSlide(FeatureLayer):
    def __init__(self, source, slide, slide_number):
        super().__init__('slide-{:02d}'.format(slide_number), source, output_layer=(slide_number==1))

        self.__slide = slide
        self.__slide_number = slide_number
        self.__transform = source.transform

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
    def slide(self):
        return self.__slide

    @property
    def slide_id(self):
        return self.__slide.slide_id

    @property
    def slide_number(self):
        return self.__slide_number

    def process(self):
    #=================
        self.__current_group.append('SLIDE')
        features = self.process_shape_list(self.slide.shapes, self.__transform, outermost=True)
        self.add_features('Slide', features, True)

    def process_group(self, group, properties, transform):
    #=====================================================
        features = self.process_shape_list(group.shapes, transform@DrawMLTransform(group).matrix())
        return self.add_features(properties.get('shape_name', ''), features)

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
                    self.source.error('Shape in slide {}, group {}, has annotation syntax error: {}'
                                        .format(self.__slide_number, group_name, shape.name))
                if 'warning' in properties:
                    self.source.error('Warning, slide {}, group {}: {}'
                                        .format(self.__slide_number, group_name, properties['warning']))
                for key in ['id', 'path']:
                    if key in properties:
                        if self.flatmap.is_duplicate_feature_id(properties[key]):
                           self.source.error('Shape in slide {}, group {}, has a duplicate id: {}'
                                               .format(self.__slide_number, group_name, shape.name))
            if 'error' in properties:
                pass
            elif 'path' in properties:
                pass
            elif (shape.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE
             or shape.shape_type == MSO_SHAPE_TYPE.FREEFORM
             or isinstance(shape, pptx.shapes.connector.Connector)):
                geometry = self.process_shape(shape, properties, transform)
                feature = self.flatmap.new_feature(geometry, properties)
                if self.output_layer and not feature.get_property('group'):
                    # Save relationship between id/class and internal feature id
                    self.flatmap.save_feature_id(feature)
                if properties.get('id', '') == self.__outline_feature_id:
                    self.outline_feature_id = feature.feature_id
                features.append(feature)
            elif shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                self.__current_group.append(properties.get('shape_name', "''"))
                grouped_feature = self.process_group(shape, properties, transform)
                self.__current_group.pop()
                if grouped_feature is not None:
                    if self.output_layer:
                        self.flatmap.save_feature_id(grouped_feature)
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
