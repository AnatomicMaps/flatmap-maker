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

import base64
import contextlib
import math
import typing
from typing import Optional, TYPE_CHECKING

#===============================================================================

import cv2
import lxml.etree as etree
import numpy as np
import mercantile
import shapely.geometry
from shapely.geometry.base import BaseGeometry
import shapely.ops
import shapely.prepared
import skia
import webcolors

#===============================================================================

from mapmaker.geometry import extent_to_bounds, Transform, reflect_point
from mapmaker.properties.markup import parse_markup
from mapmaker.utils import FilePath, ProgressBar, log

from .. import WORLD_METRES_PER_PIXEL
from .definitions import DefinitionStore, ObjectStore
from .styling import ElementStyleDict, StyleMatcher, wrap_element
from .transform import SVGTransform
from .utils import svg_markup, length_as_pixels, length_as_points, parse_svg_path, SVG_TAG, XLINK_HREF

if TYPE_CHECKING:
    from mapmaker.flatmap.layers import RasterLayer
    from mapmaker.output.tilemaker import TileSet

#===============================================================================

IMAGE_MEDIA_TYPES = ['image/jpeg', 'image/png']

#===============================================================================

IGNORED_SVG_TAGS = [
    SVG_TAG('style'),
    SVG_TAG('title'),
]

#===============================================================================

PRESCALE_IMAGE_SIZES = [10, 100]        # If an image is too small we prescale it
PRESCALE_FACTORS     = [100, 10]        # for skia and then scale it back in a transform

#===============================================================================

def make_colour(colour_string, opacity=1.0):
    if colour_string.startswith('#'):
        colour = webcolors.hex_to_rgb(colour_string)
    elif colour_string.startswith('rgb('):
        rgb = colour_string[4:-1].split(',')
        if '%' in colour_string:
            colour = webcolors.rgb_percent_to_rgb(rgb) # type: ignore
        else:
            colour = [int(c) for c in rgb]
    elif colour_string.startswith('rgba('):
        rgba = colour_string[5:-1].split(',')
        rgb = rgba[:3]
        if '%' in colour_string:
            colour = webcolors.rgb_percent_to_rgb(rgb) # type: ignore
        else:
            colour = [int(c) for c in rgb]
        opacity *= float(rgba[3])
    else:
        colour = webcolors.html5_parse_legacy_color(colour_string)
    return skia.Color(*tuple(colour), round(255*opacity))

#===============================================================================

class GradientStops(object):
    def __init__(self, element):
        self.__offsets = []
        self.__colours = []
        for stop in element:
            if stop.tag == SVG_TAG('stop'):
                styling = ElementStyleDict(stop)
                self.__offsets.append(float(stop.attrib['offset']))
                self.__colours.append(make_colour(styling.get('stop-color'),
                                                  float(styling.get('stop-opacity', 1.0))))

    @property
    def offsets(self):
        return self.__offsets

    @property
    def colours(self):
        return self.__colours

#===============================================================================

class CanvasDrawingObject(object):
    def __init__(self, paint: skia.Paint, bounds: skia.IRect, parent_transform: Transform,
                       local_transform: Optional[Transform],
                       clip_path: Optional[skia.Path], bbox: Optional[shapely.geometry.Polygon]=None,
                       root_object=False, scale=1.0):
        if root_object:
            T = parent_transform if local_transform is None else parent_transform@local_transform
            self.__matrix = skia.Matrix(list(T.flatten()))
        else:
            T = parent_transform
            if local_transform is None:
                self.__matrix = None
            else:
                self.__matrix = skia.Matrix(list(local_transform.flatten()))
                T = T@local_transform
        if scale != 1.0:
            if self.__matrix is not None:
                self.__matrix = self.__matrix.preScale(1.0/scale, 1.0/scale)
        if bounds is not None and bbox is None:
            bbox = typing.cast(Optional[shapely.geometry.Polygon],
                               T.transform_geometry(shapely.geometry.box(*tuple(bounds))))
        self.__bbox = bbox
        self.__clip_path = clip_path
        self.__paint = paint
        self.__save_state = (self.__matrix is not None
                          or self.__clip_path is not None)

    @property
    def bbox(self) -> Optional[shapely.geometry.Polygon]:
        return self.__bbox

    @property
    def paint(self):
        return self.__paint

    def draw_element(self, canvas: skia.Canvas, tile_bbox: shapely.geometry.Polygon):
    #================================================================================
        pass

    def intersects(self, bbox: BaseGeometry):
    #========================================
        return bbox is not None and (self.__bbox is None or self.__bbox.intersects(bbox))

    @contextlib.contextmanager
    def transformed_clipped_canvas(self, canvas):
    #============================================
        if self.__save_state:
            canvas.save()
            if self.__matrix is not None:
                canvas.concat(self.__matrix)
            if self.__clip_path is not None:
                canvas.clipPath(self.__clip_path, doAntiAlias=True)
        yield
        if self.__save_state:
            canvas.restore()

#===============================================================================

class CanvasPath(CanvasDrawingObject):
    def __init__(self, path: skia.Path, paint: skia.Paint, parent_transform: Transform,
                       local_transform: Optional[Transform], clip_path):
        super().__init__(paint, path.getBounds(), parent_transform, local_transform, clip_path)
        self.__path = path

    def draw_element(self, canvas: skia.Canvas, tile_bbox: shapely.geometry.Polygon):
    #================================================================================
        if self.intersects(tile_bbox):
            with self.transformed_clipped_canvas(canvas):
                canvas.drawPath(self.__path, self.paint)

#===============================================================================

class CanvasImage(CanvasDrawingObject):
    def __init__(self, image: skia.Image, paint: skia.Paint, parent_transform: Transform,
                       local_transform: Optional[Transform], clip_path: skia.Path, pos=(0, 0), scale=1.0):
        super().__init__(paint, image.bounds(), parent_transform, local_transform, clip_path, scale=scale)
        self.__image = image
        self.__pos = (scale*pos[0], scale*pos[1])

    def draw_element(self, canvas: skia.Canvas, tile_bbox: shapely.geometry.Polygon):
    #================================================================================
        if self.intersects(tile_bbox):
            with self.transformed_clipped_canvas(canvas):
                canvas.drawImage(self.__image, self.__pos[0], self.__pos[1], skia.SamplingOptions(), self.paint)

#===============================================================================

class CanvasText(CanvasDrawingObject):
    def __init__(self, text, attribs, parent_transform: Transform,
                       local_transform: Optional[Transform], clip_path: skia.Path):
        self.__text = text
        style_rules = dict(attribs)
        if 'style' in attribs:
            styling = attribs.pop('style')
            style_rules.update(dict([rule.split(':', 1) for rule in [rule.strip()
                                                for rule in styling[:-1].split(';')]]))
        font_style = skia.FontStyle(int(style_rules.get('font-weight', skia.FontStyle.kNormal_Weight)),
                                    skia.FontStyle.kNormal_Width,
                                    skia.FontStyle.kUpright_Slant)
        type_face = None
        font_manager = skia.FontMgr()
        for font_family in style_rules.get('font-family', 'Calibri').split(','):
            type_face = font_manager.matchFamilyStyle(font_family, font_style)
            if type_face is not None:
                break
        if type_face is None:
            type_face = font_manager.matchFamilyStyle(None, font_style)
        self.__font = skia.Font(type_face,
                                length_as_points(style_rules.get('font-size', 10)))
        self.__pos = [float(attribs.get('x', 0)), float(attribs.get('y', 0))]
        text_width = self.__font.measureText(text)
        text_height = self.__font.getSpacing()
        halign = attribs.get('text-anchor')  # end, middle, start
        if halign == 'middle':
            self.__pos[0] -= text_width/2
        elif halign == 'end':
            self.__pos[0] -= text_width
        valign = attribs.get('dominant-baseline')  # auto, middle
        if valign == 'middle':
            self.__pos[1] += text_height/2
        bounds = skia.Rect(self.__pos[0], self.__pos[1] - text_height,
                           self.__pos[0] + text_width, self.__pos[1])
        paint = skia.Paint(AntiAlias=True, Color=skia.ColorBLACK)
        super().__init__(paint, bounds, parent_transform, local_transform, clip_path)

    def draw_element(self, canvas: skia.Canvas, tile_bbox: shapely.geometry.Polygon):
    #================================================================================
        if self.intersects(tile_bbox):
            with self.transformed_clipped_canvas(canvas):
                canvas.drawString(self.__text, self.__pos[0], self.__pos[1], self.__font, self.paint)

#===============================================================================

class CanvasGroup(CanvasDrawingObject):
    def __init__(self, drawing_objects, parent_transform: Transform,
                       local_transform: Optional[Transform], clip_path, outermost=False):
        bbox = (shapely.box(*shapely.total_bounds([element.bbox for element in drawing_objects]))
                    if len(drawing_objects) > 0 else
                None)
        super().__init__(None, None, parent_transform, local_transform, clip_path, bbox=bbox, root_object=outermost)
        self.__drawing_objects = drawing_objects

    @property
    def is_valid(self):
        return len(self.__drawing_objects) > 0

    def draw_element(self, canvas: skia.Canvas, tile_bbox: shapely.geometry.Polygon):
    #================================================================================
        if self.intersects(tile_bbox):
            with self.transformed_clipped_canvas(canvas):
                for element in self.__drawing_objects:
                    element.draw_element(canvas, tile_bbox)

#===============================================================================
#===============================================================================

class SVGTiler(object):
    def __init__(self, raster_layer: 'RasterLayer', tile_set: 'TileSet'):
        self.__bbox = shapely.geometry.box(*extent_to_bounds(raster_layer.extent))
        self.__svg = etree.fromstring(raster_layer.source_data, parser=etree.XMLParser(huge_tree=True))
        self.__source_path: Optional[FilePath] = raster_layer.source_path
        if 'viewBox' in self.__svg.attrib:
            viewbox = [float(x) for x in self.__svg.attrib.get('viewBox').split()]
            (left, top) = tuple(viewbox[:2])
            self.__size = tuple(viewbox[2:])
        else:
            (left, top) = (0, 0)
            self.__size = (length_as_pixels(self.__svg.attrib['width']),
                           length_as_pixels(self.__svg.attrib['height']))
        self.__scaling = (tile_set.pixel_rect.width/self.__size[0],
                          tile_set.pixel_rect.height/self.__size[1])
        self.__definitions = DefinitionStore()
        self.__style_matcher = StyleMatcher(self.__svg.find(SVG_TAG('style')))
        self.__clip_paths = ObjectStore()

        # Transform from SVG pixels to tile pixels
        svg_to_tile_transform = Transform([[self.__scaling[0],               0.0, 0.0],
                                           [              0.0, self.__scaling[1], 0.0],
                                           [              0.0,               0.0, 1.0]])@np.array([[1.0, 0.0, -left],
                                                                                                   [0.0, 1.0, -top],
                                                                                                   [0.0, 0.0,  1.0]])
        # Transform from SVG pixels to world coordinates
        self.__image_to_world = (Transform([
            [WORLD_METRES_PER_PIXEL/self.__scaling[0],                                        0, 0],
            [                                       0, WORLD_METRES_PER_PIXEL/self.__scaling[1], 0],
            [                                       0,                                        0, 1]])
           @np.array([[1.0,  0.0, -self.__scaling[0]*self.__size[0]/2.0],
                      [0.0, -1.0,  self.__scaling[1]*self.__size[1]/2.0],
                      [0.0,  0.0,                                   1.0]]))
##      ``image_to_world`` is used for rasterising details and may be wrong, esp. if the
##      SVG's viewport origin is not (0, 0).
##
##      The following might be correct, but needs testing...
##
##          svg_origin = (left+self.__size[0]/2.0, top+self.__size[1]/2)
##          @np.array([[1.0,  0.0, -svg_origin[0]],
##                     [0.0, -1.0,  svg_origin[1]],
##                     [0.0,  0.0,            1.0]]))
##
##     And do we need to multiply by scaling??
##
        self.__tile_size = tile_set.tile_size
        self.__tile_origin = tile_set.start_coords
        self.__pixel_offset = tuple(tile_set.pixel_rect)[0:2]

        self.__tile_bboxes: dict[str, shapely.geometry.Polygon] = {}
        for tile in tile_set:
            tile_set.tile_coords_to_pixels.transform_point((tile.x, tile.y))
            x0 = (tile.x - self.__tile_origin[0])*self.__tile_size[0] - self.__pixel_offset[0]
            y0 = (tile.y - self.__tile_origin[1])*self.__tile_size[1] - self.__pixel_offset[1]
            tile_bbox = shapely.geometry.box(x0, y0,
                                                                   x0 + self.__tile_size[0],
                                                                   y0 + self.__tile_size[0])
            self.__tile_bboxes[mercantile.quadkey(tile)] = tile_bbox

        # Render SVG onto a CanvasGroup
        self.__svg_drawing = self.__draw_svg(svg_to_tile_transform)

    @property
    def size(self):
        return self.__size

    @property
    def image_to_world(self):
        return self.__image_to_world

    def get_image(self):
    #===================
        # Draw image to fit tile set's pixel rectangle
        surface = skia.Surface(round(self.__scaling[0]*self.__size[0]),
                               round(self.__scaling[1]*self.__size[1]))
        canvas = surface.getCanvas()
        canvas.clear(skia.Color4f(0xFFFFFFFF))
        self.__svg_drawing.draw_element(canvas, self.__bbox)
        log.info('Making image snapshot...')
        image = surface.makeImageSnapshot()
        return image.toarray(colorType=skia.kBGRA_8888_ColorType)

    def get_tile(self, tile: mercantile.Tile):
    #=========================================
        surface = skia.Surface(*self.__tile_size)  ## In pixels...
        canvas = surface.getCanvas()
        canvas.clear(skia.Color4f(0xFFFFFFFF))
        canvas.translate(self.__pixel_offset[0] + (self.__tile_origin[0] - tile.x)*self.__tile_size[0],
                         self.__pixel_offset[1] + (self.__tile_origin[1] - tile.y)*self.__tile_size[1])
        quadkey = mercantile.quadkey(tile)
        if quadkey in self.__tile_bboxes:
            self.__svg_drawing.draw_element(canvas, self.__tile_bboxes[quadkey])
        image = surface.makeImageSnapshot()
        return image.toarray(colorType=skia.kBGRA_8888_ColorType)

    def __get_transform(self, wrapped_element) -> Optional[Transform]:
    #=================================================================
        element_style = self.__style_matcher.element_style(wrapped_element)
        transform = element_style.get(
            'transform', wrapped_element.etree_element.attrib.get('transform'))
        if transform is not None:
            T = SVGTransform(transform)
            transform_origin = element_style.get(
                'transform-origin', wrapped_element.etree_element.attrib.get('transform-origin'))
            if transform_origin is None:
                return T
            translation = [length_as_pixels(l) for l in transform_origin.split()]
            return (SVGTransform(f'translate({translation[0]}, {translation[1]})')
                   @T
                   @SVGTransform(f'translate({-translation[0]}, {-translation[1]})'))

    def __draw_svg(self, svg_to_tile_transform, show_progress=False):
    #================================================================
        wrapped_svg = wrap_element(self.__svg)
        transform = self.__get_transform(wrapped_svg)
        drawing_objects = self.__draw_element_list(wrapped_svg,
            svg_to_tile_transform if transform is None else svg_to_tile_transform@transform,
            None,
            show_progress=show_progress)
        return CanvasGroup(drawing_objects, svg_to_tile_transform, transform, None, outermost=True)

    def __draw_group(self, group, parent_transform, parent_style):
    #=============================================================
        group_style = self.__style_matcher.element_style(group, parent_style)
        group_clip_path = group_style.pop('clip-path', None)
        transform = self.__get_transform(group)
        drawing_objects = self.__draw_element_list(group,
            parent_transform if transform is None else parent_transform@transform,
            group_style)
        return CanvasGroup(drawing_objects, parent_transform, transform, self.__clip_paths.get_by_url(group_clip_path))

    def __draw_element_list(self, elements, parent_transform, parent_style, show_progress=False):
    #============================================================================================
        drawing_objects = []
        children = list(elements.iter_children())
        progress_bar = ProgressBar(show=show_progress,
            total=len(children),
            unit='shp', ncols=40,
            bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}')
        for wrapped_element in children:
            progress_bar.update(1)
            element = wrapped_element.etree_element
            if element.tag is etree.Comment or element.tag is etree.PI:
                continue
            if element.tag == SVG_TAG('defs'):
                self.__definitions.add_definitions(element)
                continue
            elif element.tag == SVG_TAG('use'):
                element = self.__definitions.use(element)
                wrapped_element = wrap_element(element)
            elif element.tag in [SVG_TAG('linearGradient'), SVG_TAG('radialGradient')]:
                self.__definitions.add_definition(element)
                continue
            elif element.tag == SVG_TAG('clipPath'):
                self.__add_clip_path(element)
            else:
                drawing_objects.extend(
                    self.__draw_element(wrapped_element, parent_transform, parent_style))
        progress_bar.close()
        return drawing_objects

    @staticmethod
    def __gradient_matrix(gradient, path):
    #=====================================
        if gradient.attrib.get('gradientUnits') == 'userSpaceOnUse':
            path_transform = Transform.Identity()
        else:                                    #  objectBoundingBox'
            bounds = path.getBounds()
            path_transform = Transform([[bounds.width(),               0, bounds.left()],
                                        [             0, bounds.height(), bounds.top()],
                                        [             0,               0,            1]])
        svg_transform = SVGTransform(gradient.attrib.get('gradientTransform'))
        return skia.Matrix(list((path_transform@svg_transform).flatten()))

    def __add_clip_path(self, clip_path_element):
    #============================================
        if ((clip_id := clip_path_element.attrib.get('id')) is not None
        and (clip_path := self.__get_clip_path(clip_path_element)) is not None):
            self.__clip_paths.add(clip_id, clip_path)

    def __get_clip_path(self, clip_path_element):
    #============================================
        clip_path = None
        for element in clip_path_element:
            if element.tag == SVG_TAG('use'):
                element = self.__definitions.use(element)
            if (element is not None
            and element.tag in [SVG_TAG('circle'), SVG_TAG('ellipse'), SVG_TAG('line'),
                               SVG_TAG('path'), SVG_TAG('polyline'), SVG_TAG('polygon'),
                               SVG_TAG('rect')]):
                path = SVGTiler.__get_graphics_path(element)
                if path is not None:
                    if clip_path is None:
                        clip_path = path
                    else:
                        clip_path.addPath(path)
        return clip_path

    def __draw_element(self, wrapped_element, parent_transform, parent_style):
    #=========================================================================
        drawing_objects = []
        element = wrapped_element.etree_element
        element_style = self.__style_matcher.element_style(wrapped_element, parent_style)
        transform = self.__get_transform(wrapped_element)

        if element.tag == SVG_TAG('g'):
            canvas_group = self.__draw_group(wrapped_element, parent_transform, parent_style)
            if canvas_group.is_valid:
                drawing_objects.append(canvas_group)

        elif element.tag == SVG_TAG('a'):
            link_elements = self.__draw_element_list(wrapped_element, parent_transform, parent_style)
            drawing_objects.extend(link_elements)

        elif element.tag in [SVG_TAG('circle'), SVG_TAG('ellipse'), SVG_TAG('line'),
                             SVG_TAG('path'), SVG_TAG('polyline'), SVG_TAG('polygon'),
                             SVG_TAG('rect')]:

            path = SVGTiler.__get_graphics_path(element)
            if path is None: return []

            fill = element_style.get('fill', '#FFF').strip()
            if fill != 'none':
                path.setFillType(skia.PathFillType.kWinding)
                opacity = float(element_style.get('opacity', 1.0))
                paint = skia.Paint(AntiAlias=True)
                if fill.startswith('url('):
                    gradient = self.__definitions.get_by_url(fill)
                    if gradient is None:
                        fill = '#800'     # Something's wrong so show show in image...
                        opacity = 0.5
                    elif gradient.tag == SVG_TAG('linearGradient'):
                        gradient_stops = GradientStops(gradient)
                        points = [(float(gradient.attrib.get('x1', 0.0)),
                                   float(gradient.attrib.get('y1', 0.0))),
                                  (float(gradient.attrib.get('x2', 1.0)),
                                   float(gradient.attrib.get('y2', 0.0)))]
                        paint.setShader(skia.GradientShader.MakeLinear(
                            points=points,
                            positions=gradient_stops.offsets,
                            colors=gradient_stops.colours,
                            localMatrix=SVGTiler.__gradient_matrix(gradient, path)
                        ))
                    elif gradient.tag == SVG_TAG('radialGradient'):
                        gradient_stops = GradientStops(gradient)
                        centre = (float(gradient.attrib.get('cx')),
                                  float(gradient.attrib.get('cy')))
                        radius = float(gradient.attrib.get('r'))
                        # TODO: fx, fy
                        #       This will need a two point conical shader
                        #       -- see chromium/blink sources
                        paint.setShader(skia.GradientShader.MakeRadial(
                            center=centre,
                            radius=radius,
                            positions=gradient_stops.offsets,
                            colors=gradient_stops.colours,
                            localMatrix=SVGTiler.__gradient_matrix(gradient, path)
                        ))
                    else:
                        fill = '#008'     # Something's wrong so show show in image...
                        opacity = 0.5

                if fill.startswith('url('):
                    if opacity < 1.0:
                        paint.setAlphaf(opacity)
                else:
                    paint.setColor(make_colour(fill, opacity))

                drawing_objects.append(CanvasPath(path, paint, parent_transform, transform,
                    self.__clip_paths.get_by_url(element_style.get('clip-path'))
                    ))

            stroke = element_style.get('stroke', 'none')
            stroked = (stroke != 'none')
            if stroked:
                stroke_opacity = 1.0
                markup = svg_markup(element)
                if markup.startswith('.'):
                    properties = parse_markup(markup)
                    if ('centreline' in properties or 'node' in properties
                     or 'id' in properties or 'class' in properties):
                        stroked = False
                opacity = stroke_opacity*float(element_style.get('stroke-opacity', 1.0))
                dasharray = element_style.get('stroke-dasharray')
                if dasharray is not None and dasharray != 'none':
                    pattern = [float(d) for d in dasharray.replace(',', ' ').split()]
                    if (len(pattern) % 2) == 1:
                        pattern = 2*pattern
                    path_effect = skia.DashPathEffect.Make(pattern, 0.0)
                else:
                    path_effect = None
                paint = skia.Paint(AntiAlias=True,
                    Style=skia.Paint.kStroke_Style,
                    Color=make_colour(stroke, opacity),
                    StrokeWidth=float(length_as_pixels(element_style.get('stroke-width', 1.0))),
                    PathEffect=path_effect,
                    )
                stroke_linejoin = element_style.get('stroke-linejoin')
                if stroke_linejoin == 'bevel':
                    paint.setStrokeJoin(skia.Paint.Join.kBevel_Join)
                elif stroke_linejoin == 'miter':
                    paint.setStrokeJoin(skia.Paint.Join.kMiter_Join)
                elif stroke_linejoin == 'round':
                    paint.setStrokeJoin(skia.Paint.Join.kRound_Join)
                stroke_linecap = element_style.get('stroke-linecap')
                if stroke_linecap == 'butt':
                    paint.setStrokeCap(skia.Paint.Cap.kButt_Cap)
                elif stroke_linecap == 'round':
                    paint.setStrokeCap(skia.Paint.Cap.kRound_Cap)
                elif stroke_linecap == 'square':
                    paint.setStrokeCap(skia.Paint.Cap.kSquare_Cap)
                stroke_miterlimit = element_style.get('stroke-miterlimit')
                if stroke_miterlimit is not None:
                    paint.setStrokeMiter(float(stroke_miterlimit))
                drawing_objects.append(CanvasPath(path, paint, parent_transform, transform,
                    self.__clip_paths.get_by_url(element.attrib.get('clip-path'))
                    ))

        elif element.tag == SVG_TAG('image'):
            image_href = element.attrib.get('href', element.attrib.get(XLINK_HREF))
            pixel_bytes = None
            if image_href is not None:
                if image_href.startswith('data:'):
                    parts = image_href[5:].split(',', 1)
                    if parts[0].endswith(';base64'):
                        media_type = parts[0].split(';', 1)[0]
                        if media_type in IMAGE_MEDIA_TYPES:
                            pixel_bytes = base64.b64decode(parts[1])
                elif self.__source_path is not None:
                    pixel_bytes = self.__source_path.join_path(image_href).get_data()
                if pixel_bytes is not None:
                    pixel_array = np.frombuffer(pixel_bytes, dtype=np.uint8)
                    pixels = cv2.imdecode(pixel_array, cv2.IMREAD_UNCHANGED)    # type: ignore
                    if pixels.shape[2] == 3:
                        pixels = cv2.cvtColor(pixels, cv2.COLOR_RGB2RGBA)       # type: ignore
                    image = skia.Image.fromarray(pixels, colorType=skia.kBGRA_8888_ColorType)
                    width = float(element.attrib.get('width', image.width()))
                    height = float(element.attrib.get('height', image.height()))
                    (x, y) = (length_as_pixels(element.attrib.get('x', 0)),
                              length_as_pixels(element.attrib.get('y', 0)))
                    scale = 1.0
                    for n, prescale_size in enumerate(PRESCALE_IMAGE_SIZES):
                        if width < prescale_size or height < prescale_size:
                            scale = PRESCALE_FACTORS[n]
                            width *= scale
                            height *= scale
                            break
                    if round(width) != image.width() or round(height) != image.height():
                        image = image.resize(round(width), round(height), skia.SamplingOptions(skia.CubicResampler.Mitchell()))
                    paint = skia.Paint()
                    opacity = float(element_style.get('opacity', 1.0))
                    paint.setAlpha(round(opacity * 255))
                    clip_path_url = element_style.pop('clip-path', None)
                    if ((clip_path := self.__clip_paths.get_by_url(clip_path_url)) is None
                    and (clip_path_element := self.__definitions.get_by_url(clip_path_url)) is not None):
                        clip_path = self.__get_clip_path(clip_path_element)
                    drawing_objects.append(CanvasImage(image, paint, parent_transform, transform, clip_path, pos=(x, y), scale=scale))

        elif element.tag == SVG_TAG('text'):
            drawing_objects.append(CanvasText(element.text, element.attrib, parent_transform, transform,
                self.__clip_paths.get_by_url(element_style.get('clip-path'))
            ))

        elif element.tag not in IGNORED_SVG_TAGS:
            log.warning("'{}' not supported...".format(element.tag))

        return drawing_objects

    @staticmethod
    def __get_graphics_path(element) -> skia.Path:
    #=============================================
        if element.tag == SVG_TAG('path'):
            tokens = list(parse_svg_path(element.attrib.get('d', '')))
            path = SVGTiler.__path_from_tokens(tokens)
        elif element.tag == SVG_TAG('rect'):
            (width, height) = (length_as_pixels(element.attrib.get('width', 0)),
                               length_as_pixels(element.attrib.get('height', 0)))
            if width == 0 or height == 0: return None
            (rx, ry) = (length_as_pixels(element.attrib.get('rx', 0)),
                        length_as_pixels(element.attrib.get('ry', 0)))
            if rx is None and ry is None:
                rx = ry = 0
            elif ry is None:
                ry = rx
            elif rx is None:
                rx = ry
            rx = min(rx, width/2)
            ry = min(ry, height/2)
            (x, y) = (length_as_pixels(element.attrib.get('x', 0)),
                      length_as_pixels(element.attrib.get('y', 0)))
            if rx == 0 and ry == 0:
                path = skia.Path.Rect((x, y, width, height))
            else:
                path = skia.Path.RRect((x, y, width, height), rx, ry)
        elif element.tag == SVG_TAG('line'):
            x1 = length_as_pixels(element.attrib.get('x1', 0))
            y1 = length_as_pixels(element.attrib.get('y1', 0))
            x2 = length_as_pixels(element.attrib.get('x2', 0))
            y2 = length_as_pixels(element.attrib.get('y2', 0))
            path = SVGTiler.__path_from_tokens(['M', x1, y1, x2, y2])
        elif element.tag == SVG_TAG('polyline'):
            points = element.attrib.get('points', '').replace(',', ' ').split()
            path = SVGTiler.__path_from_tokens(['M'] + points)
        elif element.tag == SVG_TAG('polygon'):
            points = [ float(p) for p in element.attrib.get('points', '').replace(',', ' ').split() ]
            skia_points = [skia.Point(*points[n:n+2]) for n in range(0, len(points), 2)]
            path = skia.Path.Polygon(skia_points, True)
        elif element.tag == SVG_TAG('circle'):
            r = length_as_pixels(element.attrib.get('r', 0))
            if r == 0: return None
            (cx, cy) = (length_as_pixels(element.attrib.get('cx', 0)),
                        length_as_pixels(element.attrib.get('cy', 0)))
            path = skia.Path.Circle(cx, cy, r)
        elif element.tag == SVG_TAG('ellipse'):
            (rx, ry) = (length_as_pixels(element.attrib.get('rx', 0)),
                        length_as_pixels(element.attrib.get('ry', 0)))
            if rx == 0 or ry == 0: return None
            (cx, cy) = (length_as_pixels(element.attrib.get('cx', 0)),
                        length_as_pixels(element.attrib.get('cy', 0)))
            path = skia.Path.Oval(skia.Rect(cx-rx, cy-ry, cx+rx, cy+ry))
        else:
            path = skia.Path()
        return path

    @staticmethod
    def __path_from_tokens(tokens) -> skia.Path:
    #===========================================
        moved = False
        first_point = None
        current_point = []
        path = skia.Path()
        pos = 0
        cmd = ''
        second_cubic_control = None
        second_quad_control = None
        while pos < len(tokens):
            if isinstance(tokens[pos], str) and tokens[pos].isalpha():
                cmd = tokens[pos]
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
                params = [float(x) for x in tokens[pos:pos+7]]
                pos += 7
                pt = params[5:7]
                if cmd == 'a':
                    pt[0] += current_point[0]
                    pt[1] += current_point[1]
                phi = math.radians(params[2])
                if moved:
                    path.moveTo(*current_point)
                    moved = False
                (rx, ry) = (params[0], params[1])
                path.arcTo(rx, ry, math.degrees(phi),
                    skia.Path.ArcSize.kSmall_ArcSize if params[3] == 0
                        else skia.Path.ArcSize.kLarge_ArcSize,
                    skia.PathDirection.kCCW if params[4] == 0
                        else skia.PathDirection.kCW,
                    *pt)
                current_point = pt

            elif cmd in ['c', 'C', 's', 'S']:
                if moved:
                    path.moveTo(*current_point)
                    moved = False
                if cmd in ['c', 'C']:
                    n_params = 6
                    coords = []
                else:
                    n_params = 4
                    if second_cubic_control is None:
                        coords = list(current_point)
                    else:
                        coords = list(reflect_point(second_cubic_control, current_point))
                params = [float(x) for x in tokens[pos:pos+n_params]]
                pos += n_params
                for n in range(0, n_params, 2):
                    pt = params[n:n+2]
                    if cmd.islower():
                        pt[0] += current_point[0]
                        pt[1] += current_point[1]
                    if n == (n_params - 4):
                        second_cubic_control = pt
                    coords.extend(pt)
                path.cubicTo(*coords)
                current_point = pt              # type: ignore

            elif cmd in ['l', 'L', 'h', 'H', 'v', 'V']:
                if cmd in ['l', 'L']:
                    params = [float(x) for x in tokens[pos:pos+2]]
                    pos += 2
                    pt = params[0:2]
                    if cmd == 'l':
                        pt[0] += current_point[0]
                        pt[1] += current_point[1]
                else:
                    param = float(tokens[pos])
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
                    path.moveTo(*current_point)
                    moved = False
                path.lineTo(*pt)
                current_point = pt

            elif cmd in ['m', 'M']:
                params = [float(x) for x in tokens[pos:pos+2]]
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
                if moved:
                    path.moveTo(*current_point)
                    moved = False
                if cmd in ['t', 'T']:
                    n_params = 4
                    coords = []
                else:
                    n_params = 2
                    if second_quad_control is None:
                        coords = list(current_point)
                    else:
                        coords = list(reflect_point(second_quad_control, current_point))
                params = [float(x) for x in tokens[pos:pos+n_params]]
                pos += n_params
                for n in range(0, n_params, 2):
                    pt = params[n:n+2]
                    if cmd.islower():
                        pt[0] += current_point[0]
                        pt[1] += current_point[1]
                    if n == (n_params - 4):
                        second_quad_control = pt
                    coords.extend(pt)
                path.quadTo(*coords)
                current_point = pt              # type: ignore

            elif cmd in ['z', 'Z']:
                if first_point is not None:
                    path.close()
                first_point = None

            else:
                log.warning('Unknown path command: {}'.format(cmd))

        return path

#===============================================================================
