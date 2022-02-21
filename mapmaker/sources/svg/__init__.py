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
from beziers.path import BezierPath
from beziers.point import Point as BezierPoint
from beziers.quadraticbezier import QuadraticBezier

from lxml import etree
import numpy as np
import shapely.geometry
import shapely.ops

#===============================================================================

from .. import MapSource, RasterSource
from .. import WORLD_METRES_PER_PIXEL

from .cleaner import SVGCleaner
from .definitions import DefinitionStore, ObjectStore
from .styling import StyleMatcher, wrap_element
from .transform import SVGTransform
from .utils import adobe_decode_markup, length_as_pixels, parse_svg_path, SVG_NS

from mapmaker.flatmap.layers import MapLayer
from mapmaker.geometry import bezier_sample, radians, Transform, reflect_point
from mapmaker.geometry.arc_to_bezier import bezier_path_from_arc_endpoints, tuple2
from mapmaker.settings import settings
from mapmaker.utils import FilePath, ProgressBar, log

#===============================================================================

# These SVG tags are not used to determine feature geometry

IGNORED_SVG_TAGS = [
    SVG_NS('font'),
    SVG_NS('image'),
    SVG_NS('linearGradient'),
    SVG_NS('radialGradient'),
    SVG_NS('style'),
    SVG_NS('text'),
]

#===============================================================================

class SVGSource(MapSource):
    def __init__(self, flatmap, id, href, kind):  # maker v's flatmap (esp. id)
        super().__init__(flatmap, id, href, kind)
        self.__source_file = FilePath(href)
        self.__exported = (kind=='base')
        svg = etree.parse(self.__source_file.get_fp()).getroot()
        if 'viewBox' in svg.attrib:
            (width, height) = tuple(float(x) for x in svg.attrib['viewBox'].split()[2:])
        else:
            width = length_as_pixels(svg.attrib['width'])
            height = length_as_pixels(svg.attrib['height'])
        # Transform from SVG pixels to world coordinates
        self.__transform = Transform([[WORLD_METRES_PER_PIXEL,                      0, 0],
                                      [                     0, WORLD_METRES_PER_PIXEL, 0],
                                      [                     0,                         0, 1]])@np.array([[1,  0, -width/2.0],
                                                                                                         [0, -1,  height/2.0],
                                                                                                         [0,  0,         1.0]])
        top_left = self.__transform.transform_point((0, 0))
        bottom_right = self.__transform.transform_point((width, height))
        # southwest and northeast corners
        self.bounds = (top_left[0], bottom_right[1], bottom_right[0], top_left[1])
        self.__layer = SVGLayer(id, self, svg, exported=self.__exported)
        self.add_layer(self.__layer)
        self.__boundary_geometry = None

    @property
    def boundary_geometry(self):
        return self.__boundary_geometry

    @property
    def transform(self):
        return self.__transform

    def process(self):
    #=================
        self.__layer.process()
        if self.__layer.boundary_feature is not None:
            self.__boundary_geometry = self.__layer.boundary_feature.geometry
        if self.__exported:
            # Save a cleaned copy of the SVG in the map's output directory
            cleaner = SVGCleaner(self.__source_file, self.flatmap.map_properties)
            cleaner.clean()
            with open(os.path.join(settings.get('output'),
                      self.flatmap.id,
                      '{}.svg'.format(self.flatmap.id)), 'wb') as fp:
                cleaner.save(fp)
        if settings.get('backgroundTiles', False):
            cleaner = SVGCleaner(self.__source_file, self.flatmap.map_properties, all_layers=False)
            cleaner.clean()
            cleaned_svg = io.BytesIO()
            cleaner.save(cleaned_svg)
            cleaned_svg.seek(0)
        else:
            cleaned_svg = None
        self.set_raster_source(RasterSource('svg', cleaned_svg, source=self.__source_file))

#===============================================================================

class SVGLayer(MapLayer):
    def __init__(self, id, source, svg, exported=True):
        super().__init__(id, source, exported=exported)
        self.__svg = svg
        self.__style_matcher = StyleMatcher(svg.find(SVG_NS('style')))
        self.__transform = source.transform
        self.__definitions = DefinitionStore()
        self.__clip_geometries = ObjectStore()

    def process(self):
    #=================
        properties = {'tile-layer': 'features'}   # Passed through to map viewer
        features = self.__process_element_list(wrap_element(self.__svg),
                                               self.__transform,
                                               properties,
                                               None, show_progress=True)
        self.add_features('SVG', features, outermost=True)

    def __process_group(self, wrapped_group, properties, transform, parent_style):
    #=============================================================================
        group_style = self.__style_matcher.element_style(wrapped_group, parent_style)
        group = wrapped_group.etree_element
        group_clip_path = group_style.pop('clip-path', None)
        clipped = self.__clip_geometries.get_by_url(group_clip_path)
        if clipped is not None:
            # Replace any features inside a clipped group with just the clipped outline
            features = [self.flatmap.new_feature(clipped, properties)]
        else:
            features = self.__process_element_list(wrapped_group,
                transform@SVGTransform(group.attrib.get('transform')),
                properties,
                group_style)
            properties.pop('tile-layer', None)
            if len(properties):
                # If the group element has markup then add a dummy `.group` feature
                # to pass it to the MapLayer
                properties['group'] = True
                features.append(self.flatmap.new_feature(shapely.geometry.Polygon(), properties))

        return self.add_features(adobe_decode_markup(group), features)

    def __process_element_list(self, elements, transform, parent_properties, parent_style, show_progress=False):
    #===========================================================================================================
        children = list(elements.iter_children())
        progress_bar = ProgressBar(show=show_progress,
            total=len(children),
            unit='shp', ncols=40,
            bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}')
        features = []
        for wrapped_element in children:
            progress_bar.update(1)
            element = wrapped_element.etree_element
            if element.tag is etree.Comment or element.tag is etree.PI:
                continue
            elif element.tag == SVG_NS('defs'):
                self.__definitions.add_definitions(element)
                continue
            elif element.tag == SVG_NS('use'):
                element = self.__definitions.use(element)
                wrapped_element = wrap_element(element)
            if element.tag == SVG_NS('clipPath'):
                self.__add_clip_geometry(wrapped_element, transform)
            else:
                self.__process_element(wrapped_element, transform, features, parent_properties, parent_style)
        progress_bar.close()
        return features

    def __add_clip_geometry(self, wrapped_clip_path, transform):
    #===========================================================
        clip_path_element = wrapped_clip_path.etree_element
        clip_id = clip_path_element.attrib.get('id')
        if clip_id is None:
            return
        geometries = []
        for wrapped_element in wrapped_clip_path.iter_children():
            element = wrapped_element.etree_element
            if element.tag == SVG_NS('use'):
                element = self.__definitions.use(element)
            if (element is not None
            and element.tag in [SVG_NS('circle'), SVG_NS('ellipse'), SVG_NS('line'),
                               SVG_NS('path'), SVG_NS('polyline'), SVG_NS('polygon'),
                               SVG_NS('rect')]):
                properties = {}
                geometry = self.__get_geometry(element, properties, transform)
                if geometry is not None:
                    geometries.append(geometry)
        if len(geometries):
            self.__clip_geometries.add(clip_id, shapely.ops.unary_union(geometries))

    def __process_element(self, wrapped_element, transform, features, parent_properties, parent_style):
    #==================================================================================================
        element = wrapped_element.etree_element
        element_style = self.__style_matcher.element_style(wrapped_element, parent_style)
        properties = parent_properties.copy()
        if 'id' in properties:   # We don't inherit `id`  (or do we have a list of inheritable properties??)
            del properties['id']
        markup = adobe_decode_markup(element)
        properties.update(self.source.properties_from_markup(markup))
        if 'error' in properties:
            pass
        elif 'path' in properties:
            pass
        elif 'styling' in properties:
            pass
        elif element.tag in [SVG_NS('circle'), SVG_NS('ellipse'),
                             SVG_NS('line'), SVG_NS('path'), SVG_NS('polyline'),
                             SVG_NS('polygon'), SVG_NS('rect')]:
            geometry = self.__get_geometry(element, properties, transform)
            if geometry is None:
                return

            # Ignore element if fill is none and no stroke is specified
            if (element_style.get('fill', '#FFF') == 'none'
            and element_style.get('stroke', 'none') == 'none'
            and 'id' not in properties):
                return

            feature = self.flatmap.new_feature(geometry, properties)
            features.append(feature)
        elif element.tag == SVG_NS('g'):
            grouped_feature = self.__process_group(wrapped_element, properties, transform, parent_style)
            if grouped_feature is not None:
                features.append(grouped_feature)
        elif element.tag in IGNORED_SVG_TAGS:
            pass
        else:
            log.warning('"{}" {} not processed...'.format(markup, element.tag))

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
        path_tokens = []

        T = transform@SVGTransform(element.attrib.get('transform'))
        if element.tag == SVG_NS('path'):
            path_tokens = list(parse_svg_path(element.attrib.get('d', '')))

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

        elif element.tag == SVG_NS('image'):
            if 'id' in properties or 'class' in properties:
                width = length_as_pixels(element.attrib.get('width', 0))
                height = length_as_pixels(element.attrib.get('height', 0))
                path_tokens = ['M', 0, 0,
                               'H', width,
                               'V', height,
                               'H', 0,
                               'V', 0,
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
                path = bezier_path_from_arc_endpoints(tuple2(*params[0:2]), phi, *params[3:5],
                                                        tuple2(*current_point), tuple2(*pt), T)
                bezier_segments.extend(path.asSegments())
                coordinates.extend(bezier_sample(path))
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
                log.warning('Unknown path command: {}'.format(cmd))

        if len(bezier_segments) > 0:
            properties['bezier-path'] = BezierPath.fromSegments(bezier_segments)

        if closed and len(coordinates) >= 3:
            geometry = shapely.geometry.Polygon(coordinates)
        elif properties.get('closed', False) and len(coordinates) >= 3:
            # Return a polygon if flagged as `closed`
            coordinates.append(coordinates[0])
            geometry = shapely.geometry.Polygon(coordinates)
        elif len(coordinates) >= 2:
            geometry = shapely.geometry.LineString(coordinates)
        else:
            geometry = None
        return geometry

#===============================================================================
