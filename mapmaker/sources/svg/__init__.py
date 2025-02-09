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

import os
import math
import tempfile
import typing
from typing import Optional
import unicodedata

#===============================================================================

from cssselect2 import ElementWrapper
import lxml.etree as etree
import numpy as np

from shapely.geometry.base import BaseGeometry
import shapely.ops

import skia

#===============================================================================

from mapmaker.exceptions import MakerException
from mapmaker.flatmap import Feature, FlatMap, SourceManifest, SOURCE_DETAIL_KINDS
from mapmaker.flatmap.layers import FEATURES_TILE_LAYER, MapLayer
from mapmaker.geometry import Transform
from mapmaker.settings import MAP_KIND
from mapmaker.shapes import Shape, SHAPE_TYPE
from mapmaker.shapes.classify import ShapeClassifier
from mapmaker.utils import FilePath, ProgressBar, log, TreeList

from .. import MapSource, RasterSource
from .. import WORLD_METRES_PER_PIXEL

from .cleaner import SVGCleaner
from .definitions import DefinitionStore, ObjectStore
from .styling import StyleMatcher, wrap_element
from .transform import SVGTransform
from .utils import circle_from_bounds, geometry_from_svg_path, length_as_pixels
from .utils import length_as_points, svg_markup, parse_svg_path, SVG_TAG

#===============================================================================

DETAILED_MAP_BORDER = 50        # pixels
FUNCTIONAL_MAP_MARGIN = 500     # pixels in SVG source space

#===============================================================================

# These SVG tags are not used to determine feature geometry

IGNORED_SVG_TAGS = [
    SVG_TAG('font'),
    SVG_TAG('linearGradient'),
    SVG_TAG('radialGradient'),
    SVG_TAG('style'),
    SVG_TAG('title'),
]

# We don't inherit the following properties from a shape's parent group

NON_INHERITED_PROPERTIES = [
    'id',
    'class',
    'markup',
    'models',
    'tooltip',
]

#===============================================================================

class SVGSource(MapSource):
    def __init__(self, flatmap: FlatMap, source_manifest: SourceManifest):  # maker v's flatmap (esp. id)
        super().__init__(flatmap, source_manifest)
        self.__source_file = FilePath(source_manifest.href)
        self.__exported = (self.kind == 'base' or self.kind in SOURCE_DETAIL_KINDS)
        svg: etree.Element = etree.parse(self.__source_file.get_fp()).getroot()
        if 'viewBox' in svg.attrib:
            viewbox = [float(x) for x in svg.attrib.get('viewBox').split()]
            (left, top) = tuple(viewbox[:2])
            (width, height) = tuple(viewbox[2:])
        else:
            (left, top) = (0, 0)
            width = length_as_pixels(svg.attrib.get('width'))
            height = length_as_pixels(svg.attrib.get('height'))
        if self.base_feature is not None:
            bounds = self.base_feature.bounds
            (scale_x, scale_y) = ((bounds[2]-bounds[0])/width, (bounds[3]-bounds[1])/height)
            if source_manifest.detail_fit == 'fit-width':
                scale = scale_x
            elif source_manifest.detail_fit == 'fit-height':
                scale = scale_y
            elif source_manifest.detail_fit == 'fit-mean':
                scale = math.sqrt(scale_x*scale_x + scale_y*scale_y)
            elif source_manifest.detail_fit == 'fit-smallest':
                scale = min(scale_x, scale_y)
            else:                       # Default to ``fit-largest``
                scale = max(scale_x, scale_y)
            self.__transform = (Transform([[1,  0, bounds[0]+(bounds[2]-bounds[0])/2],
                                           [0,  1, bounds[1]+(bounds[3]-bounds[1])/2],
                                           [0,  0,         1]])
                               @np.array([[scale,     0,  0],
                                          [    0, scale,  0],
                                          [    0,     0,  1]])
                               @np.array([[1.0,  0.0, -left-width/2],
                                          [0.0, -1.0,   top+height/2],
                                          [0.0,  0.0,            1.0]]))
            self.__metres_per_pixel = scale
        else:
            # Add a margin around the base layer of a functional map
            if (self.flatmap.map_kind == MAP_KIND.FUNCTIONAL
            and self.kind == 'base'):
                left -= FUNCTIONAL_MAP_MARGIN
                top -= FUNCTIONAL_MAP_MARGIN
                width += 2*FUNCTIONAL_MAP_MARGIN
                height += 2*FUNCTIONAL_MAP_MARGIN
            # Transform from SVG pixels to world coordinates
            self.__transform = (Transform([[WORLD_METRES_PER_PIXEL,                      0, 0],
                                           [                     0, WORLD_METRES_PER_PIXEL, 0],
                                           [                     0,                      0, 1]])
                               @np.array([[1.0,  0.0, -left-width/2.0],
                                          [0.0, -1.0,  top+height/2.0],
                                          [0.0,  0.0,             1.0]]))
            self.__metres_per_pixel = WORLD_METRES_PER_PIXEL

        top_left = self.__transform.transform_point((left, top))
        bottom_right = self.__transform.transform_point((left+width, top+height))
        # southwest and northeast corners
        self.bounds = (top_left[0], bottom_right[1], bottom_right[0], top_left[1])
        self.__layer = SVGLayer(self.id, self, svg, exported=self.__exported, min_zoom=self.min_zoom)
        self.__boundary_geometry = None

    @property
    def boundary_geometry(self):
        return self.__boundary_geometry

    @property
    def metres_per_pixel(self):
        return self.__metres_per_pixel

    @property
    def transform(self):
        return self.__transform

    def process(self):
    #=================
        self.__layer.process()
        if self.__layer.boundary_feature is not None:
            self.__boundary_geometry = self.__layer.boundary_feature.geometry
        self.add_layer(self.__layer)

    def create_preview(self):
    #========================
        # Save a cleaned copy of the SVG in the map's output directory. Call after
        # connectivity has been generated otherwise thno paths will be in the saved SVG
        cleaner = SVGCleaner(self.__source_file, self.flatmap.properties_store, all_layers=True)
        cleaner.clean()
        cleaner.add_connectivity_group(self.flatmap, self.__transform)
        cleaned_svg = self.flatmap.full_filename(f'images/{self.flatmap.id}.svg')
        os.makedirs(os.path.dirname(cleaned_svg), exist_ok=True)
        with open(cleaned_svg, 'wb') as fp:
            cleaner.save(fp)

    def get_raster_sources(self) -> list[RasterSource]:
    #==================================================
        raster_sources = []
        if (background := self.background_raster_source) is not None:
            background_path = FilePath(background.href)
            raster_sources.append(RasterSource(f'{self.id}_background', 'svg', background_path.get_data, self,
                                               source_path=background_path, background_layer=True,
                                               transform=Transform.translate(background.translate)@Transform.scale(background.scale)))
        raster_sources.append(RasterSource(f'{self.id}_image', 'svg', self.__get_raster_data, self,
                                           source_path=self.__source_file))
        return raster_sources

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
    def __init__(self, id: str, source: SVGSource, svg: etree.Element, exported=True, min_zoom=None):
        super().__init__(id, source, exported=exported, min_zoom=min_zoom)
        self.__svg = svg
        self.__style_matcher = StyleMatcher(svg.find(f'.//{SVG_TAG('style')}'))
        self.__transform = source.transform
        self.__definitions = DefinitionStore()
        self.__clip_geometries = ObjectStore()
        if self.flatmap.map_kind == MAP_KIND.FUNCTIONAL:
            # Include layer id with shape id when setting feature id
            Shape.reset_shape_id(prefix=f'{id}/')

    @property
    def source(self) -> SVGSource:
        return typing.cast(SVGSource, super().source)

    def process(self):
    #=================
        properties = {'tile-layer': FEATURES_TILE_LAYER}   # Passed through to map viewer
        shapes = self.__process_element_list(wrap_element(self.__svg),
                                             self.__transform,
                                             properties,
                                             None, show_progress=True)
        self.__process_shapes(shapes)

    def __process_shapes(self, shapes: TreeList[Shape]) -> list[Feature]:
    #====================================================================
        if (self.flatmap.map_kind == MAP_KIND.FUNCTIONAL
        and not self.source.kind == 'anatomical'):
            # CellDL conversion mode...
            shape_classifier = ShapeClassifier(shapes.flatten(), self.source.map_area(), self.source.metres_per_pixel)
            shapes = TreeList(shape_classifier.shapes)
        # Add a background shape behind a detailed functional map
        if (self.flatmap.map_kind == MAP_KIND.FUNCTIONAL
        and self.source.kind == 'functional'):
            bounds = self.source.bounds
            margin = self.source.metres_per_pixel*DETAILED_MAP_BORDER
            bounds = (bounds[0] + margin, bounds[1] - margin,
                      bounds[2] - margin, bounds[3] - margin)
            bbox = shapely.geometry.box(*bounds).buffer(2*margin)
            shapes.insert(0, Shape(None, bbox, {
                'id': 'background',
                'tooltip': False,
                'colour': 'white',
                'kind': 'background'
            }))
        return self.__process_shape_list(shapes, 0)

    def __process_shape_list(self, shapes: TreeList[Shape], depth) -> list[Feature]:
    #===============================================================================
        ## need to go through tree list and add_features for every branch
        features = []
        for shape in shapes[0:]:
            if isinstance(shape, TreeList):
                self.__process_shape_list(shape, depth+1)
            elif not shape.properties.get('exclude', False):
                features.append(self.flatmap.new_feature(self.id, shape.geometry, shape.properties))
        self.add_group_features(f'SVG_{depth}', features, outermost=(depth==0))
        return features

    def __get_transform(self, wrapped_element) -> Transform:
    #=======================================================
        element_style = self.__style_matcher.element_style(wrapped_element)
        T = SVGTransform(element_style.get(
            'transform', wrapped_element.etree_element.attrib.get('transform')))
        transform_origin = element_style.get(
            'transform-origin', wrapped_element.etree_element.attrib.get('transform-origin'))
        transform_box = element_style.get(
            'transform-box', wrapped_element.etree_element.attrib.get('transform-box'))
        if transform_box is not None:
            raise MakerException('Unsupported `transform-box` attribute -- please normalise SVG source')
        if transform_origin is None:
            return T
        try:
            translation = [length_as_pixels(l) for l in transform_origin.split()]
            return (SVGTransform(f'translate({translation[0]}, {translation[1]})')
                   @T
                   @SVGTransform(f'translate({-translation[0]}, {-translation[1]})'))
        except MakerException:
            raise MakerException('Unsupported `transform-origin` units -- please normalise SVG source')

    def __process_group(self, wrapped_group: ElementWrapper, properties, transform, parent_style) -> Optional[Shape|TreeList[Shape]]:
    #================================================================================================================================
        group = wrapped_group.etree_element
        if len(group) == 0:
            return None
        children: list[etree.Element] = wrapped_group.etree_children    # type: ignore
        pruned = False
        while (len(children) == 1
          and children[0].tag == SVG_TAG('g')
          and len(children[0].attrib) == 0):
            # Ignore nested groups with only a single group element with no attributes
            for k, v in group.items():
                children[0].set(k, v)
            group = children[0]
            wrapped_group = wrap_element(group)
            children = wrapped_group.etree_children                     # type: ignore
            pruned = True
        if pruned:
            markup = svg_markup(group)
            properties_from_markup = self.source.properties_from_markup(markup)
            properties.update(properties_from_markup)
        group_id = properties.get('id')
        group_style = self.__style_matcher.element_style(wrapped_group, parent_style)
        group_clip_path = group_style.pop('clip-path', None)
        clipped = self.__clip_geometries.get_by_url(group_clip_path)
        if clipped is not None:
            # Replace any shapes inside a clipped group with just the clipped outline
            shapes = Shape(group_id, clipped, properties, svg_element=group)
        else:
            group_transform = self.__get_transform(wrapped_group)
            shapes = self.__process_element_list(wrapped_group,
                transform@group_transform,
                properties,
                group_style)
            properties.pop('tile-layer', None)  # Don't set ``tile-layer``
            if group_id and len(group_shapes := TreeList([s for s in shapes.flatten() if s.geometry.is_valid and not s.properties.get('exclude', False)])):
                # If the group element has markup and contains geometry then add it as a shape
                group_geometry = shapely.ops.unary_union([s.geometry for s in group_shapes.flatten()])
                group_shape = Shape(group_id, group_geometry, properties)
                # Don't output interior shapes with no markup
                shapes = TreeList([shape for shape in group_shapes.flatten() if shape.has_property('markup')])
                shapes.append(group_shape)

        return shapes

    def __process_element_list(self, elements: ElementWrapper, transform, parent_properties, parent_style, show_progress=False) -> TreeList[Shape]:
    #==============================================================================================================================================
        children = list(elements.iter_children())
        progress_bar = ProgressBar(show=show_progress,
            total=len(children),
            unit='shp', ncols=40,
            bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}')
        shapes: TreeList[Shape] = TreeList()
        for wrapped_element in children:
            progress_bar.update(1)
            element = wrapped_element.etree_element
            if (element.tag is etree.Comment
             or element.tag is etree.PI
             or element.tag in IGNORED_SVG_TAGS):
                continue
            elif element.tag == SVG_TAG('defs'):
                self.__add_definitions(element, transform)
                continue
            elif element.tag == SVG_TAG('use'):
                element = self.__definitions.use(element)
                wrapped_element = wrap_element(element)
            if element is not None and element.tag == SVG_TAG('clipPath'):
                self.__add_clip_geometry(element, transform)
            elif (shape := self.__process_element(wrapped_element, transform, parent_properties, parent_style)) is not None:
                shapes.append(shape)
        progress_bar.close()
        return shapes

    def __add_definitions(self, defs_element, transform):
    #====================================================
        for element in defs_element:
            if element.tag == SVG_TAG('clipPath'):
                self.__add_clip_geometry(element, transform)
            else:
                self.__definitions.add_definition(element)

    def __add_clip_geometry(self, clip_path_element, transform):
    #===========================================================
        if ((clip_id := clip_path_element.attrib.get('id')) is not None
        and (geometry := self.__get_clip_geometry(clip_path_element, transform)) is not None):
            self.__clip_geometries.add(clip_id, geometry)

    """
    Get the geometry described by the children of a ``clipPath`` element
    """
    def __get_clip_geometry(self, clip_path_element, transform) -> Optional[BaseGeometry]:
    #====================================================================================
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

    def __process_element(self, wrapped_element: ElementWrapper, transform, parent_properties, parent_style) -> Optional[Shape|TreeList[Shape]]:
    #===========================================================================================================================================
        element = wrapped_element.etree_element
        element_style = self.__style_matcher.element_style(wrapped_element, parent_style)
        markup = svg_markup(element)
        properties_from_markup = self.source.properties_from_markup(markup)
        properties = parent_properties.copy()
        for name in NON_INHERITED_PROPERTIES:
            properties.pop(name, None)
        properties.update(properties_from_markup)
        shape_id = properties.get('id')  ## versus element.attrib.get('id')
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
                if self.source.flatmap.map_kind == MAP_KIND.FUNCTIONAL:
                    properties['fill'] = element_style.get('fill', 'none')
                    properties['stroke'] = element_style.get('stroke', 'none')
                return Shape(shape_id, geometry, properties, svg_element=element)
        elif element.tag == SVG_TAG('image'):
            geometry = None
            clip_path_url = element_style.pop('clip-path', None)
            if clip_path_url is not None:
                if ((geometry := self.__clip_geometries.get_by_url(clip_path_url)) is None
                and (clip_path_element := self.__definitions.get_by_url(clip_path_url)) is not None):
                    T = transform@self.__get_transform(wrapped_element)
                    geometry = self.__get_clip_geometry(clip_path_element, T)
                if geometry is not None:
                    return Shape(shape_id, geometry, properties, shape_type=SHAPE_TYPE.IMAGE, svg_element=element)
        elif element.tag == SVG_TAG('g'):
            return self.__process_group(wrapped_element, properties, transform, parent_style)
        elif element.tag == SVG_TAG('text'):
            geometry = self.__process_text(element, properties, transform)
            if geometry is not None:
                return Shape(shape_id, geometry, properties, shape_type=SHAPE_TYPE.TEXT, svg_element=element)
        else:
            log.warning(f'SVG element {element.tag} "{markup}" not processed...')
        return None

    def __get_geometry(self, element, properties, transform) -> Optional[BaseGeometry]:
    #==================================================================================
    ##
    ## Returns path element as a `shapely` object.
    ##
        path_tokens = []
        if element.tag == SVG_TAG('path'):
            path_tokens = list(parse_svg_path(element.attrib.get('d', '')))

        elif element.tag in [SVG_TAG('rect'), SVG_TAG('image')]:
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

        if properties.get('node', False):
            must_close = True
        elif properties.get('centreline', False):
            must_close = False
        else:
            must_close = properties.get('closed', None)
        try:
            wrapped_element = wrap_element(element)
            geometry, bezier_segments = geometry_from_svg_path(path_tokens,
                transform@self.__get_transform(wrapped_element), must_close)
            if geometry is not None and properties.get('node', False):
                # All centeline nodes become circles
                geometry = circle_from_bounds(geometry.bounds)
            if self.flatmap.map_kind in [MAP_KIND.ANATOMICAL, MAP_KIND.CENTRELINE]:
                properties['bezier-segments'] = bezier_segments
            return geometry
        except ValueError as err:
            log.warning(f"{err}: {properties.get('markup')}")

    def __process_text(self, element, properties, transform: Transform) -> Optional[BaseGeometry]:
    #=============================================================================================
        attribs = element.attrib
        style_rules = dict(attribs)
        if 'style' in attribs:
            styling = attribs.pop('style')
            style_rules.update(dict([rule.split(':', 1) for rule in [rule.strip()
                                                for rule in styling[:-1].split(';')]]))
        font_style = skia.FontStyle(int(style_rules.get('font-weight', skia.FontStyle.kNormal_Weight)),
                                    skia.FontStyle.kNormal_Width,
                                    skia.FontStyle.kUpright_Slant)
        type_face = None
        element_text = ' '.join(' '.join([t.replace('\u200b', '') for t in element.itertext()]).split())
        if element_text == '':
            element_text = ' '
        font_manager = skia.FontMgr()
        for font_family in style_rules.get('font-family', 'Calibri').split(','):
            type_face = font_manager.matchFamilyStyle(font_family, font_style)
            if type_face is not None:
                break
        if type_face is None:
            type_face = font_manager.matchFamilyStyle(None, font_style)
        font = skia.Font(type_face, length_as_points(style_rules.get('font-size', 10)))
        bounds = skia.Rect()
        width = font.measureText(element_text, skia.TextEncoding.kUTF8, bounds)
        height = font.getSpacing()
        halign = attribs.get('text-anchor')  # end, middle, start
        [x, y] = [float(attribs.get('x', 0)), float(attribs.get('y', 0))]
        if halign == 'middle':
            x -= width/2
        elif halign == 'end':
            x -= width
        valign = attribs.get('dominant-baseline')  # auto, middle
        if valign == 'middle':
            y += height/2
        metrics = font.getMetrics()
        bds = bounds.asScalars()
        if (top := bds[1]) == 0:
            top = metrics.fXHeight
        if (right := bds[2]) == 0:
            right = width
        path_tokens = ['M', x+bds[0], y+top,
                       'H', x+right,
                       'V', y+bds[3],
                       'H', x+bds[0],
                       'V', y+top,
                       'Z']
        wrapped_element = wrap_element(element)
        T = transform@self.__get_transform(wrapped_element)
        geometry, _ = geometry_from_svg_path(path_tokens, T, True)
        bounds = shapely.bounds(geometry)
        properties['left'] = bounds[0]
        properties['right'] = bounds[2]
        properties['baseline'] = T.transform_point((x, y))[1]
        properties['text'] = unicodedata.normalize('NFKD', element_text).replace('\u2212', '-')  ## minus-sign --> minus
        properties['font-family'] = font.getTypeface().getFamilyName()

        return geometry             # type: ignore

#===============================================================================
