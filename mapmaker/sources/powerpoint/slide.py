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

import numpy as np
import shapely.geometry

import pptx.shapes.connector
from pptx.enum.shapes import MSO_SHAPE_TYPE

#===============================================================================

from mapmaker.flatmap.layers import FeatureLayer
from mapmaker.geometry import ellipse_point
from mapmaker.geometry import bezier_sample
from mapmaker.geometry.arc_to_bezier import bezier_paths_from_arc_endpoints, tuple2
from mapmaker.utils import ProgressBar

from ..markup import parse_layer_directive, parse_markup

from .formula import Geometry, radians
from .presets import DML
from .transform import DrawMLTransform

#===============================================================================

class PowerpointSlide(FeatureLayer):
    def __init__(self, source, slide, slide_number):
        id = 'slide-{:02d}'.format(slide_number)
        # Get any layer directives
        if slide.has_notes_slide:
            notes_slide = slide.notes_slide
            notes_text = notes_slide.notes_text_frame.text
            if notes_text.startswith('.'):
                layer_directive = parse_layer_directive(notes_text)
                if 'error' in layer_directive:
                    source.error('Slide {}: invalid layer directive: {}'
                                 .format(slide_number, notes_text))
                if 'id' in layer_directive:
                    id = layer_directive['id']
        super().__init__(id, source, output_layer=(slide_number==1))
        self.__slide = slide
        self.__slide_number = slide_number
        self.__transform = source.transform
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
        features = self.__process_shape_list(self.slide.shapes, self.__transform)
        self.add_features('Slide', features, outermost=True)

    def __process_group(self, group, properties, transform):
    #=======================================================
        features = self.__process_shape_list(group.shapes, transform@DrawMLTransform(group).matrix())
        return self.add_features(properties.get('markup', ''), features)

    def __process_shape_list(self, shapes, transform):
    #=================================================
        progress_bar = ProgressBar(total=len(shapes),
            unit='shp', ncols=40,
            bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}')
        features = []
        for shape in shapes:
            properties = {'tile-layer': 'features'}   # Passed through to map viewer
            if shape.name.startswith('.'):
                group_name = self.__current_group[-1]  # For error reporting
                properties.update(parse_markup(shape.name))
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
                geometry = self.__get_geometry(shape, properties, transform)
                feature = self.flatmap.new_feature(geometry, properties)
                if self.output_layer and not feature.get_property('group'):
                    # Save relationship between id/class and internal feature id
                    self.flatmap.save_feature_id(feature)
                features.append(feature)
            elif shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                self.__current_group.append(properties.get('markup', "''"))
                grouped_feature = self.__process_group(shape, properties, transform)
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
            progress_bar.update(1)
        progress_bar.close()
        return features

    def __get_geometry(self, shape, properties, transform):
    #======================================================
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
                    (wR, hR) = ((pptx_geometry.attrib_value(c, 'wR'),
                                 pptx_geometry.attrib_value(c, 'hR')))
                    stAng = radians(pptx_geometry.attrib_value(c, 'stAng'))
                    swAng = radians(pptx_geometry.attrib_value(c, 'swAng'))
                    p1 = ellipse_point(wR, hR, stAng)
                    p2 = ellipse_point(wR, hR, stAng + swAng)
                    pt = (current_point[0] - p1[0] + p2[0],
                          current_point[1] - p1[1] + p2[1])
                    large_arc_flag = 1 if swAng >= math.pi else 0
                    paths = bezier_paths_from_arc_endpoints(tuple2(wR, hR),
                                        0, large_arc_flag, 1,
                                        tuple2(*current_point), tuple2(*pt),
                                        T)
                    coordinates.extend(bezier_sample(paths))
                    current_point = pt

                elif c.tag == DML('close'):
                    if first_point is not None and current_point != first_point:
                        coordinates.append(first_point)
                    closed = True
                    first_point = None
                    # Close current pptx_geometry and start a new one...

                elif c.tag == DML('cubicBezTo'):
                    coords = [BezierPoint(*T.transform_point(current_point))]
                    for p in c.getchildren():
                        pt = pptx_geometry.point(p)
                        coords.append(BezierPoint(*T.transform_point(pt)))
                        current_point = pt
                    bz = CubicBezier(*coords)
                    coordinates.extend(bezier_sample(bz))

                elif c.tag == DML('lnTo'):
                    pt = pptx_geometry.point(c.pt)
                    if moved:
                        coordinates.append(T.transform_point(current_point))
                        moved = False
                    coordinates.append(T.transform_point(pt))
                    current_point = pt

                elif c.tag == DML('moveTo'):
                    pt = pptx_geometry.point(c.pt)
                    if first_point is None:
                        first_point = pt
                    current_point = pt
                    moved = True

                elif c.tag == DML('quadBezTo'):
                    coords = [BezierPoint(*T.transform_point(current_point))]
                    for p in c.getchildren():
                        pt = pptx_geometry.point(p)
                        coords.append(BezierPoint(*T.transform_point(pt)))
                        current_point = pt
                    bz = QuadraticBezier(*coords)
                    coordinates.extend(bezier_sample(bz))

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
