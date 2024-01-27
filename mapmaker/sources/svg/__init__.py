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

import tempfile

#===============================================================================

from lxml import etree
import numpy as np
import shapely.ops

#===============================================================================

from mapmaker.flatmap.layers import FEATURES_TILE_LAYER, MapLayer
from mapmaker.geometry import Transform
from mapmaker.properties import not_in_group_properties
from mapmaker.utils import FilePath, ProgressBar, log

from .. import MapSource, RasterSource
from .. import WORLD_METRES_PER_PIXEL

from .cleaner import SVGCleaner
from .definitions import DefinitionStore, ObjectStore
from .styling import StyleMatcher, wrap_element
from .transform import SVGTransform
from .utils import circle_from_bounds, geometry_from_svg_path, length_as_pixels
from .utils import svg_markup, parse_svg_path, SVG_TAG

#===============================================================================

# These SVG tags are not used to determine feature geometry

IGNORED_SVG_TAGS = [
    SVG_TAG('font'),
    SVG_TAG('linearGradient'),
    SVG_TAG('radialGradient'),
    SVG_TAG('style'),
    SVG_TAG('text'),
    SVG_TAG('title'),
]

#===============================================================================

class SVGSource(MapSource):
    def __init__(self, flatmap, id, href, kind):  # maker v's flatmap (esp. id)
        super().__init__(flatmap, id, href, kind)
        self.__source_file = FilePath(href)
        self.__exported = (kind=='base')
        svg = etree.parse(self.__source_file.get_fp()).getroot()
        if 'viewBox' in svg.attrib:
            viewbox = [float(x) for x in svg.attrib.get('viewBox').split()]
            (left, top) = tuple(viewbox[:2])
            (width, height) = tuple(viewbox[2:])
        else:
            (left, top) = (0, 0)
            width = length_as_pixels(svg.attrib.get('width'))
            height = length_as_pixels(svg.attrib.get('height'))
        # Transform from SVG pixels to world coordinates
        self.__transform = Transform([[WORLD_METRES_PER_PIXEL,                      0, 0],
                                      [                     0, WORLD_METRES_PER_PIXEL, 0],
                                      [                     0,                      0, 1]])@np.array([[1.0,  0.0, -left-width/2.0],
                                                                                                      [0.0, -1.0,  top+height/2.0],
                                                                                                      [0.0,  0.0,             1.0]])
        top_left = self.__transform.transform_point((left, top))
        bottom_right = self.__transform.transform_point((left+width, top+height))
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

    def create_preview(self):
    #========================
        # Save a cleaned copy of the SVG in the map's output directory. Call after
        # connectivity has been generated otherwise thno paths will be in the saved SVG
        cleaner = SVGCleaner(self.__source_file, self.flatmap.properties_store, all_layers=True)
        cleaner.clean()
        cleaner.add_connectivity_group(self.flatmap, self.__transform)
        with open(self.flatmap.full_filename(f'{self.flatmap.id}.svg'), 'wb') as fp:
            cleaner.save(fp)

    def get_raster_source(self):
    #===========================
        return RasterSource('svg', self.__get_raster_data, source_path=self.__source_file)

    def __get_raster_data(self) -> bytes:
    #====================================
        cleaner = SVGCleaner(self.__source_file, self.flatmap.properties_store, all_layers=False)
        cleaner.clean()
        cleaned_svg = tempfile.TemporaryFile()
        cleaner.save(cleaned_svg)
        cleaned_svg.seek(0)
        return cleaned_svg.read()

#===============================================================================

class SVGLayer(MapLayer):
    def __init__(self, id, source, svg, exported=True):
        super().__init__(id, source, exported=exported)
        self.__svg = svg
        self.__style_matcher = StyleMatcher(svg.find(SVG_TAG('style')))
        self.__transform = source.transform
        self.__definitions = DefinitionStore()
        self.__clip_geometries = ObjectStore()

    def process(self):
    #=================
        properties = {'tile-layer': FEATURES_TILE_LAYER}   # Passed through to map viewer
        features = self.__process_element_list(wrap_element(self.__svg),
                                               self.__transform,
                                               properties,
                                               None, show_progress=True)
        self.add_features('SVG', features, outermost=True)

    @staticmethod
    def __excluded_group_feature(properties):
        return (not_in_group_properties(properties)
             or 'auto-hide' in properties.get('class', '')
             or (properties.get('type') == 'nerve'
                 and properties.get('kind') != 'centreline'))

    def __process_group(self, wrapped_group, properties, transform, parent_style):
    #=============================================================================
        group = wrapped_group.etree_element
        if len(group) == 0:
            return None
        children = wrapped_group.etree_children
        while (len(children) == 1
          and children[0].tag == SVG_TAG('g')
          and len(children[0].attrib) == 0):
            # Ignore nested groups with only a single group element with no attributes
            for k, v in group.items():
                children[0].set(k, v)
            group = children[0]
            wrapped_group = wrap_element(group)
            children = wrapped_group.etree_children
        group_style = self.__style_matcher.element_style(wrapped_group, parent_style)
        group_clip_path = group_style.pop('clip-path', None)
        clipped = self.__clip_geometries.get_by_url(group_clip_path)
        if clipped is not None:
            # Replace any features inside a clipped group with just the clipped outline
            group_feature = self.flatmap.new_feature(clipped, properties)
        else:
            features = self.__process_element_list(wrapped_group,
                transform@SVGTransform(group.attrib.get('transform')),
                properties,
                group_style)
            properties.pop('tile-layer', None)  # Don't set ``tile-layer``
            if len(group_features := [f for f in features if f.geometry.is_valid and not self.__excluded_group_feature(f.properties)]):
                # If the group element has markup and contains geometry then add it as a feature
                group_feature = self.flatmap.new_feature(shapely.ops.unary_union([f.geometry for f in group_features]), properties)
                # And don't output interior features with no markup
                for feature in group_features:
                    if not feature.has_property('markup'):
                        feature.set_property('exclude', True)
            else:
                group_feature = None
            group_name = svg_markup(group)
            if (feature_group := self.add_features(group_name, features)) is not None:
                if 'id' not in properties:
                    group_feature = feature_group
                else:
                    log.warning(f'SVG group `{group_name}` with id cannot also contain a `.group` marker')
        return group_feature

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
            elif element.tag == SVG_TAG('defs'):
                self.__definitions.add_definitions(element)
                continue
            elif element.tag == SVG_TAG('use'):
                element = self.__definitions.use(element)
                wrapped_element = wrap_element(element)
            if element.tag == SVG_TAG('clipPath'):
                self.__add_clip_geometry(element, transform)
            elif (feature := self.__process_element(wrapped_element, transform, parent_properties, parent_style)) is not None:
                features.append(feature)
        progress_bar.close()
        return features

    def __add_clip_geometry(self, clip_path_element, transform):
    #===========================================================
        if ((clip_id := clip_path_element.attrib.get('id')) is not None
        and (geometry := self.__get_clip_geometry(clip_path_element, transform)) is not None):
            self.__clip_geometries.add(clip_id, geometry)

    def __get_clip_geometry(self, clip_path_element, transform):
    #===========================================================
        geometries = []
        for element in clip_path_element:
            if element.tag == SVG_TAG('use'):
                element = self.__definitions.use(element)
            if (element is not None
            and element.tag in [SVG_TAG('circle'), SVG_TAG('ellipse'), SVG_TAG('line'),
                               SVG_TAG('path'), SVG_TAG('polyline'), SVG_TAG('polygon'),
                               SVG_TAG('rect')]):
                properties = {}
                geometry = self.__get_geometry(element, properties, transform)
                if geometry is not None:
                    geometries.append(geometry)
        return shapely.ops.unary_union(geometries) if len(geometries) else None

    def __process_element(self, wrapped_element, transform, parent_properties, parent_style):
    #========================================================================================
        element = wrapped_element.etree_element
        element_style = self.__style_matcher.element_style(wrapped_element, parent_style)
        markup = svg_markup(element)
        properties_from_markup = self.source.properties_from_markup(markup)
        properties = parent_properties.copy()
        properties.pop('id', None)       # We don't inherit `id`
        properties.pop('markup', None)   # nor `markup`
        properties.update(properties_from_markup)
        if 'path' in properties:
            pass
        elif 'styling' in properties:
            pass
        elif element.tag in [SVG_TAG('circle'), SVG_TAG('ellipse'),
                             SVG_TAG('line'), SVG_TAG('path'), SVG_TAG('polyline'),
                             SVG_TAG('polygon'), SVG_TAG('rect')]:
            geometry = self.__get_geometry(element, properties, transform)
            if geometry is None:
                return None
            # Ignore element if fill is none and no stroke is specified
            elif (element_style.get('fill', '#FFF') == 'none'
            and element_style.get('stroke', 'none') == 'none'
            and 'id' not in properties):
                return None
            else:
                return self.flatmap.new_feature(geometry, properties)
        elif element.tag == SVG_TAG('image'):
            clip_path_url = element_style.pop('clip-path', None)
            if ((geometry := self.__clip_geometries.get_by_url(clip_path_url)) is None
            and (clip_path_element := self.__definitions.get_by_url(clip_path_url)) is not None):
                T = transform@SVGTransform(element.attrib.get('transform'))
                geometry = self.__get_clip_geometry(clip_path_element, T)
            if geometry is not None:
                return self.flatmap.new_feature(geometry, properties)
        elif element.tag == SVG_TAG('g'):
            return self.__process_group(wrapped_element, properties, transform, parent_style)
        elif element.tag in IGNORED_SVG_TAGS:
            pass
        else:
            log.warning(f'SVG element {element.tag} "{markup}" not processed...')
        return None

    def __get_geometry(self, element, properties, transform):
    #=======================================================
    ##
    ## Returns path element as a `shapely` object.
    ##
        path_tokens = []
        if element.tag == SVG_TAG('path'):
            path_tokens = list(parse_svg_path(element.attrib.get('d', '')))

        elif element.tag == SVG_TAG('rect'):
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

        elif element.tag == SVG_TAG('line'):
            x1 = length_as_pixels(element.attrib.get('x1', 0))
            y1 = length_as_pixels(element.attrib.get('y1', 0))
            x2 = length_as_pixels(element.attrib.get('x2', 0))
            y2 = length_as_pixels(element.attrib.get('y2', 0))
            path_tokens = ['M', x1, y1, x2, y2]

        elif element.tag == SVG_TAG('polyline'):
            points = element.attrib.get('points', '').replace(',', ' ').split()
            path_tokens = ['M'] + points

        elif element.tag == SVG_TAG('polygon'):
            points = element.attrib.get('points', '').replace(',', ' ').split()
            path_tokens = ['M'] + points + ['Z']

        elif element.tag == SVG_TAG('circle'):
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

        elif element.tag == SVG_TAG('ellipse'):
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

        elif element.tag == SVG_TAG('image'):
            if 'id' in properties or 'class' in properties:
                width = length_as_pixels(element.attrib.get('width', 0))
                height = length_as_pixels(element.attrib.get('height', 0))
                path_tokens = ['M', 0, 0,
                               'H', width,
                               'V', height,
                               'H', 0,
                               'V', 0,
                               'Z']

        if properties.get('node', False):
            must_close = True
        elif properties.get('centreline', False):
            must_close = False
        else:
            must_close = properties.get('closed', None)
        try:
            geometry, bezier_segments = geometry_from_svg_path(path_tokens, transform@SVGTransform(element.attrib.get('transform')), must_close)
            if properties.get('node', False):
                # All centeline nodes become circles
                geometry = circle_from_bounds(geometry.bounds)
            properties['bezier-segments'] = bezier_segments
            return geometry
        except ValueError as err:
            log.warning(f"{err}: {properties.get('markup')}")

#===============================================================================
