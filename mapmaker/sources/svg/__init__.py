#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2020  David Brooks
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
import os
from pathlib import Path
import re

#===============================================================================

# https://simoncozens.github.io/beziers.py/index.html
from beziers.cubicbezier import CubicBezier
from beziers.point import Point as BezierPoint
from beziers.quadraticbezier import QuadraticBezier

from lxml import etree

import numpy as np
import shapely.geometry
from tqdm import tqdm

#===============================================================================

from .. import MapSource, RasterSource
from .. import WORLD_METRES_PER_PIXEL
from ..markup import parse_markup

from .transform import SVGTransform
from .utils import adobe_decode, length_as_pixels

from mapmaker.flatmap.layers import FeatureLayer
from mapmaker.geometry import transform_bezier_samples, transform_point
from mapmaker.geometry.arc_to_bezier import path_from_arc, tuple2

#===============================================================================

def SVG(tag):
    return '{{http://www.w3.org/2000/svg}}{}'.format(tag)

#===============================================================================

class SVGSource(MapSource):
    def __init__(self, flatmap, id, source_path, boundary_id=None, output_layer=True):
        super().__init__(flatmap, id)
        self.__boundary_id = boundary_id

        self.__svg = etree.parse(source_path).getroot()

        if 'viewBox' in self.__svg.attrib:
            (width, height) = tuple(float(x) for x in self.__svg.attrib['viewBox'].split()[2:])
        else:
            width = length_as_pixels(self.__svg.attrib['width'])
            height = length_as_pixels(self.__svg.attrib['height'])

        self.__transform = np.array([[WORLD_METRES_PER_PIXEL,                      0, 0],
                                     [                     0, WORLD_METRES_PER_PIXEL, 0],
                                     [                     0,                         0, 1]])@np.array([[1,  0, -width/2.0],
                                                                                                        [0, -1,  height/2.0],
                                                                                                        [0,  0,         1.0]])
        top_left = transform_point(self.__transform, (0, 0))
        bottom_right = transform_point(self.__transform, (width, height))
        # southwest and northeast corners
        self.bounds = (top_left[0], bottom_right[1], bottom_right[0], top_left[1])

        self.__layer = SVGLayer(id, self, output_layer)
        self.add_layer(self.__layer)

    @property
    def transform(self):
        return self.__transform

    def process(self):
    #=================
        self.__layer.process(self.__svg)

#===============================================================================

class SVGLayer(FeatureLayer):
    def __init__(self, id, source, output_layer=True):
        super().__init__(id, source, output_layer=output_layer)

        self.__transform = source.transform

        self.__outline_feature_id = None
        self.__current_group = []

    def process(self, svg):
    #======================
        self.__current_group.append('ROOT')
        features = self.__process_element_list(svg, self.__transform, outermost=True)
        self.add_features('SVG', features, True)

    def __process_group(self, group, properties, transform):
    #=======================================================
        features = self.__process_element_list(group, transform@SVGTransform(group).matrix())
        return self.add_features(properties.get('markup', ''), features)

    def __process_element_list(self, elements, transform, outermost=False):
    #======================================================================
        if outermost:
            progress_bar = tqdm(total=len(elements),
                unit='shp', ncols=40,
                bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}')

        features = []
        for element in elements:
            properties = {'tile-layer': 'features'}   # Passed through to map viewer
            if element.attrib.get('id', '').startswith('_x2E_'):
                markup = adobe_decode(element.attrib['id'])
                properties.update(parse_markup(markup))
                group_name = self.__current_group[-1]  # For error reporting
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
            else:
                markup = ''
            if 'error' in properties:
                pass
            elif 'path' in properties:
                pass
            elif element.tag == SVG('path'):
                geometry = self.__get_geometry(element, properties, transform)
                feature = self.flatmap.new_feature(geometry, properties)
                if self.output_layer and not feature.get_property('group'):
                    # Save relationship between id/class and internal feature id
                    self.flatmap.save_feature_id(feature)
                if properties.get('id', '') == self.__outline_feature_id:
                    self.outline_feature_id = feature.feature_id
                features.append(feature)
            elif element.tag == SVG('g'):
                self.__current_group.append(properties.get('markup', "''"))
                grouped_feature = self.__process_group(element, properties, transform)
                self.__current_group.pop()
                if grouped_feature is not None:
                    if self.output_layer:
                        self.flatmap.save_feature_id(grouped_feature)
                    features.append(grouped_feature)
            elif element.tag in [SVG('image'), SVG('text')]:
                pass
            else:
                print('"{}" {} not processed...'.format(markup, element.tag))
            if outermost:
                progress_bar.update(1)

        if outermost:
            progress_bar.close()
        return features

    @staticmethod
    def __path_matcher(m):
    #=====================
    # Helper for parsing `d` attrib of a path
        c = m[0]
        if c.isalpha(): return ' ' + c + ' '
        if c == '-': return ' -'
        if c == ',': return ' '
        return c

    def __get_geometry(self, element, properties, transform):
    #=====================================================
    ##
    ## Returns path element as a `shapely` object.
    ##
        coordinates = []
        moved = False
        first_point = None
        current_point = None
        closed = False

        T = transform@SVGTransform(element).matrix()
        path_tokens = re.sub('.', SVGLayer.__path_matcher, element.attrib.get('d', '')).split()
        pos = 0
        while pos < len(path_tokens):
            if isinstance(path_tokens[pos], str) and path_tokens[pos].isalpha():
                cmd = path_tokens[pos]
                pos += 1
            # Else repeat previous command with new coordinates
            # with `moveTo` becoming `lineTo`
            elif cmd == 'M':
                cmd = 'L'
            elif cmd == 'm':
                cmd = 'l'

            if cmd in ['a', 'A']:
                params = [float(x) for x in path_tokens[pos:pos+7]]
                pos += 7
                pt = params[5:7]
                if cmd == 'a':
                    pt[0] += current_point[0]
                    pt[1] += current_point[1]
                path = path_from_arc(tuple2(*params[0:2]), *params[2:5],
                                     tuple2(*current_point), tuple2(*pt))
                coordinates.extend(transform_bezier_samples(T, path))
                current_point = pt

            elif cmd in ['c', 'C']:
                params = [float(x) for x in path_tokens[pos:pos+6]]
                pos += 6
                coords = [BezierPoint(*current_point)]
                for n in [0, 2, 4]:
                    pt = params[n:n+2]
                    if cmd == 'c':
                        pt[0] += current_point[0]
                        pt[1] += current_point[1]
                    coords.append(BezierPoint(*pt))
                current_point = pt
                bz = CubicBezier(*coords)
                coordinates.extend(transform_bezier_samples(T, bz))

            elif cmd in ['l', 'L', 'h', 'H', 'v', 'V']:
                if cmd in ['l', 'L']:
                    params = [float(x) for x in path_tokens[pos:pos+2]]
                    pos += 2
                    pt = params[0:2]
                    if cmd == 'l':
                        pt[0] += current_point[0]
                        pt[1] += current_point[1]
                else:
                    param = float(path_tokens[pos])
                    pos += 1
                    if cmd == 'h':
                        param += current_point[0]
                    elif cmd == 'v':
                        param += current_point[1]
                    if cmd in ['h', 'H']:
                        pt = [param, current_point[1]]
                    else:
                        pt = [current_point[0], param]
                if moved:
                    coordinates.append(transform_point(T, current_point))
                    moved = False
                coordinates.append(transform_point(T, pt))
                current_point = pt

            elif cmd in ['m', 'M']:
                params = [float(x) for x in path_tokens[pos:pos+2]]
                pos += 2
                pt = params[0:2]
                if first_point is None:
                    first_point = pt
                    # First `m` in a path is treated as `M`
                    current_point = pt
                else:
                    if cmd == 'm':
                        pt[0] += current_point[0]
                        pt[1] += current_point[1]
                    current_point = pt
                moved = True

            elif cmd in ['q', 'Q']:
                params = [float(x) for x in path_tokens[pos:pos+4]]
                pos += 4
                coords = [BezierPoint(*current_point)]
                for n in [0, 2]:
                    pt = params[n:n+2]
                    if cmd == 'q':
                        pt[0] += current_point[0]
                        pt[1] += current_point[1]
                    coords.append(BezierPoint(*pt))
                current_point = pt
                bz = QuadraticBezier(*coords)
                coordinates.extend(transform_bezier_samples(T, bz))

            elif cmd in ['z', 'Z']:
                if first_point is not None and current_point != first_point:
                    coordinates.append(transform_point(T, first_point))
                closed = True
                first_point = None

            else:
                print('Unknown path command: {}'.format(cmd))

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
