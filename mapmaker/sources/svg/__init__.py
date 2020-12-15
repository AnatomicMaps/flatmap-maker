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

import io
import os
import re

#===============================================================================

# https://simoncozens.github.io/beziers.py/index.html
from beziers.cubicbezier import CubicBezier
from beziers.point import Point as BezierPoint
from beziers.quadraticbezier import QuadraticBezier

from lxml import etree
import numpy as np
import shapely.geometry

#===============================================================================

from .. import MapSource, RasterSource
from .. import WORLD_METRES_PER_PIXEL
from ..markup import parse_markup

from .cleaner import SVGCleaner
from .definitions import DefinitionStore
from .transform import SVGTransform
from .utils import adobe_decode, length_as_pixels, SVG_NS

from mapmaker.flatmap.layers import FeatureLayer
from mapmaker.geometry import bezier_sample, radians, Transform, reflect_point
from mapmaker.geometry.arc_to_bezier import bezier_paths_from_arc_endpoints, tuple2
from mapmaker.settings import settings
from mapmaker.utils import ProgressBar

#===============================================================================

class SVGSource(MapSource):
    def __init__(self, flatmap, id, source_path, output_layer=True):
        super().__init__(flatmap, id)
        self.__source_path = source_path
        self.__output_layer = output_layer
        self.__svg = etree.parse(source_path).getroot()
        if 'viewBox' in self.__svg.attrib:
            (width, height) = tuple(float(x) for x in self.__svg.attrib['viewBox'].split()[2:])
        else:
            width = length_as_pixels(self.__svg.attrib['width'])
            height = length_as_pixels(self.__svg.attrib['height'])

        self.__transform = Transform([[WORLD_METRES_PER_PIXEL,                      0, 0],
                                      [                     0, WORLD_METRES_PER_PIXEL, 0],
                                      [                     0,                         0, 1]])@np.array([[1,  0, -width/2.0],
                                                                                                         [0, -1,  height/2.0],
                                                                                                         [0,  0,         1.0]])
        top_left = self.__transform.transform_point((0, 0))
        bottom_right = self.__transform.transform_point((width, height))
        # southwest and northeast corners
        self.bounds = (top_left[0], bottom_right[1], bottom_right[0], top_left[1])

        self.__layer = SVGLayer(id, self, output_layer)
        self.__raster_source = None
        self.add_layer(self.__layer)

    @property
    def raster_source(self):
        return self.__raster_source

    @property
    def transform(self):
        return self.__transform

    def process(self):
    #=================
        self.__layer.process(self.__svg)
        if self.__output_layer:
            # Save a cleaned copy of the SVG in the map's output directory
            cleaner = SVGCleaner(self.__source_path, self.flatmap.map_properties)
            cleaner.clean()
            with open(os.path.join(settings.get('output'),
                      self.flatmap.id,
                      '{}.svg'.format(self.id)), 'wb') as fp:
                cleaner.save(fp)
            if settings.get('backgroundTiles', False):
                cleaner = SVGCleaner(self.__source_path, self.flatmap.map_properties, all_layers=False)
                cleaner.clean()
                cleaned_svg = io.BytesIO()
                cleaner.save(cleaned_svg)
                cleaned_svg.seek(0)
                self.__raster_source = RasterSource('svg', cleaned_svg)

#===============================================================================

class SVGLayer(FeatureLayer):
    def __init__(self, id, source, output_layer=True):
        super().__init__(id, source, output_layer=output_layer)
        self.__transform = source.transform
        self.__current_group = []
        self.__definitions = DefinitionStore()

    def process(self, svg):
    #======================
        self.__current_group.append('ROOT')
        features = self.__process_element_list(svg, self.__transform, show_progress=True)
        self.add_features('SVG', features, outermost=True)

    def __process_group(self, group, properties, transform):
    #=======================================================
        features = self.__process_element_list(group,
            transform@SVGTransform(group.attrib.get('transform')))
        return self.add_features(adobe_decode(group.attrib.get('id', '')), features)

    def __process_element_list(self, elements, transform, show_progress=False):
    #==========================================================================
        progress_bar = ProgressBar(show=show_progress,
            total=len(elements),
            unit='shp', ncols=40,
            bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}')
        features = []
        for element in elements:
            if element.tag == SVG_NS('defs'):
                self.__definitions.add_definitions(element)
                progress_bar.update(1)
                continue
            elif element.tag == SVG_NS('use'):
                element = self.__definitions.use(element)
            self.__process_element(element, transform, features)
            progress_bar.update(1)
        progress_bar.close()
        return features

    def __process_element(self, element, transform, features):
    #=========================================================
        properties = {'tile-layer': 'features'}   # Passed through to map viewer
        markup = adobe_decode(element.attrib.get('id', ''))
        if markup.startswith('.'):
            markup = adobe_decode(element.attrib['id'])
            properties.update(parse_markup(markup))
            group_name = self.__current_group[-1]  # For error reporting
            if 'error' in properties:
                self.source.error('{} error: {}: annotation syntax error: {}'
                                    .format(self.id, group_name, markup))
            if 'warning' in properties:
                self.source.error('{} warning: {}: {}'
                                    .format(self.id, group_name, properties['warning']))
            for key in ['id', 'path']:
                if key in properties:
                    if self.flatmap.is_duplicate_feature_id(properties[key]):
                       self.source.error('{} error: {}: duplicate id: {}'
                                           .format(self.id, group_name, markup))
        if 'error' in properties:
            pass
        elif 'path' in properties:
            pass
        elif element.tag in [SVG_NS('circle'), SVG_NS('ellipse'), SVG_NS('line'),
                             SVG_NS('path'), SVG_NS('polyline'), SVG_NS('polygon'),
                             SVG_NS('rect')]:
            geometry = self.__get_geometry(element, properties, transform)
            if geometry is None:
                return
            feature = self.flatmap.new_feature(geometry, properties)
            if self.output_layer and not feature.get_property('group'):
                # Save relationship between id/class and internal feature id
                self.flatmap.save_feature_id(feature)
            features.append(feature)
        elif element.tag == SVG_NS('g'):
            self.__current_group.append(properties.get('markup', "''"))
            grouped_feature = self.__process_group(element, properties, transform)
            self.__current_group.pop()
            if grouped_feature is not None:
                if self.output_layer:
                    self.flatmap.save_feature_id(grouped_feature)
                features.append(grouped_feature)
        elif element.tag in [SVG_NS('image'), SVG_NS('style'), SVG_NS('text')]:
            pass
        else:
            print('"{}" {} not processed...'.format(markup, element.tag))

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
    #=======================================================
    ##
    ## Returns path element as a `shapely` object.
    ##
        coordinates = []
        bezier_segments = []
        moved = False
        first_point = None
        current_point = None
        closed = False

        T = transform@SVGTransform(element.attrib.get('transform'))
        if element.tag == SVG_NS('path'):
            path_tokens = re.sub('.', SVGLayer.__path_matcher, element.attrib.get('d', '')).split()

        elif element.tag == SVG_NS('rect'):
            x = length_as_pixels(element.attrib.get('x', 0))
            y = length_as_pixels(element.attrib.get('y', 0))
            width = length_as_pixels(element.attrib.get('width', 0))
            height = length_as_pixels(element.attrib.get('height', 0))
            rx = length_as_pixels(element.attrib.get('rx'))
            ry = length_as_pixels(element.attrib.get('ry'))
            if width == 0 or height == 0: return None

            if rx is None and ry is None:
                rx = ry = 0
            elif ry is None:
                ry = rx
            elif rx is None:
                rx = ry
            rx = min(rx, width/2)
            ry = min(ry, height/2)
            if rx == 0 and ry == 0:
                path_tokens = ['M', x, y,
                               'H', x+width,
                               'V', y+height,
                               'H', x,
                               'V', y,
                               'Z']
            else:
                path_tokens = ['M', x+rx, y,
                               'H', x+width-rx,
                               'A', rx, ry, 0, 0, 1, x+width, y+ry,
                               'V', y+height-ry,
                               'A', rx, ry, 0, 0, 1, x+width-rx, y+height,
                               'H', x+rx,
                               'A', rx, ry, 0, 0, 1, x, y+height-ry,
                               'V', y+ry,
                               'A', rx, ry, 0, 0, 1, x+rx, y,
                               'Z']

        elif element.tag == SVG_NS('line'):
            x1 = length_as_pixels(element.attrib.get('x1', 0))
            y1 = length_as_pixels(element.attrib.get('y1', 0))
            x2 = length_as_pixels(element.attrib.get('x2', 0))
            y2 = length_as_pixels(element.attrib.get('y2', 0))
            path_tokens = ['M', x1, y1, x2, y2]

        elif element.tag == SVG_NS('polyline'):
            points = element.attrib.get('points', '').replace(',', ' ').split()
            path_tokens = ['M'] + points

        elif element.tag == SVG_NS('polygon'):
            points = element.attrib.get('points', '').replace(',', ' ').split()
            path_tokens = ['M'] + points + ['Z']

        elif element.tag == SVG_NS('circle'):
            cx = length_as_pixels(element.attrib.get('cx', 0))
            cy = length_as_pixels(element.attrib.get('cy', 0))
            r = length_as_pixels(element.attrib.get('r', 0))
            if r == 0: return None
            path_tokens = ['M', cx+r, cy,
                           'A', r, r, 0, 0, 0, cx, cy-r,
                           'A', r, r, 0, 0, 0, cx-r, cy,
                           'A', r, r, 0, 0, 0, cx, cy+r,
                           'A', r, r, 0, 0, 0, cx+r, cy,
                           'Z']

        elif element.tag == SVG_NS('ellipse'):
            cx = length_as_pixels(element.attrib.get('cx', 0))
            cy = length_as_pixels(element.attrib.get('cy', 0))
            rx = length_as_pixels(element.attrib.get('rx', 0))
            ry = length_as_pixels(element.attrib.get('ry', 0))
            if rx == 0 or ry == 0: return None
            path_tokens = ['M', cx+rx, cy,
                           'A', rx, ry, 0, 0, 0, cx, cy-ry,
                           'A', rx, ry, 0, 0, 0, cx-rx, cy,
                           'A', rx, ry, 0, 0, 0, cx, cy+ry,
                           'A', rx, ry, 0, 0, 0, cx+rx, cy,
                           'Z']

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

            if cmd not in ['s', 'S']:
                second_cubic_control = None
            if cmd not in ['t', 'T']:
                second_quad_control = None

            if cmd in ['a', 'A']:
                params = [float(x) for x in path_tokens[pos:pos+7]]
                pos += 7
                pt = params[5:7]
                if cmd == 'a':
                    pt[0] += current_point[0]
                    pt[1] += current_point[1]
                phi = radians(params[2])
                paths = bezier_paths_from_arc_endpoints(tuple2(*params[0:2]), phi, *params[3:5],
                                                        tuple2(*current_point), tuple2(*pt), T)
                bezier_segments.extend(paths.asSegments())
                coordinates.extend(bezier_sample(paths))
                current_point = pt

            elif cmd in ['c', 'C', 's', 'S']:
                coords = [BezierPoint(*T.transform_point(current_point))]
                if cmd in ['c', 'C']:
                    n_params = 6
                else:
                    n_params = 4
                    if second_cubic_control is None:
                        coords.append(BezierPoint(*T.transform_point(current_point)))
                    else:
                        coords.append(BezierPoint(*T.transform_point(
                            reflect_point(second_cubic_control, current_point))))
                params = [float(x) for x in path_tokens[pos:pos+n_params]]
                pos += n_params
                for n in range(0, n_params, 2):
                    pt = params[n:n+2]
                    if cmd.islower():
                        pt[0] += current_point[0]
                        pt[1] += current_point[1]
                    if n == (n_params - 4):
                        second_cubic_control = pt
                    coords.append(BezierPoint(*T.transform_point(pt)))
                bz = CubicBezier(*coords)
                bezier_segments.append(bz)
                coordinates.extend(bezier_sample(bz))
                current_point = pt

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
                    coordinates.append(T.transform_point(current_point))
                    moved = False
                coordinates.append(T.transform_point(pt))
                current_point = pt

            elif cmd in ['m', 'M']:
                params = [float(x) for x in path_tokens[pos:pos+2]]
                pos += 2
                pt = params[0:2]
                if first_point is None:
                    # First `m` in a path is treated as `M`
                    first_point = pt
                else:
                    if cmd == 'm':
                        pt[0] += current_point[0]
                        pt[1] += current_point[1]
                current_point = pt
                moved = True

            elif cmd in ['q', 'Q', 't', 'T']:
                coords = [BezierPoint(*T.transform_point(current_point))]
                if cmd in ['q', 'Q']:
                    n_params = 4
                else:
                    n_params = 2
                    if second_quad_control is None:
                        coords.append(BezierPoint(*T.transform_point(current_point)))
                    else:
                        coords.append(BezierPoint(*T.transform_point(
                            reflect_point(second_quad_control, current_point))))
                params = [float(x) for x in path_tokens[pos:pos+n_params]]
                pos += n_params
                for n in range(0, n_params, 2):
                    pt = params[n:n+2]
                    if cmd.islower():
                        pt[0] += current_point[0]
                        pt[1] += current_point[1]
                    if n == (n_params - 4):
                        second_quad_control = pt
                    coords.append(BezierPoint(*T.transform_point(pt)))
                bz = QuadraticBezier(*coords)
                bezier_segments.append(bz)
                coordinates.extend(bezier_sample(bz))
                current_point = pt

            elif cmd in ['z', 'Z']:
                if first_point is not None and current_point != first_point:
                    coordinates.append(T.transform_point(first_point))
                closed = True
                first_point = None

            else:
                print('Unknown path command: {}'.format(cmd))

        if settings.get('saveBeziers', False) and len(bezier_segments) > 0:
            properties['bezier-segments'] = [repr(bz) for bz in bezier_segments]

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
