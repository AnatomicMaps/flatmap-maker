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

#===============================================================================

import cv2
from lxml import etree
import numpy as np
import mercantile
import shapely.geometry
import shapely.ops
import shapely.prepared
import skia
import webcolors

#===============================================================================

from mapmaker.geometry import extent_to_bounds, Transform, reflect_point
from mapmaker.properties.markup import parse_markup
from mapmaker.utils import ProgressBar, log

from .. import WORLD_METRES_PER_PIXEL
from .definitions import DefinitionStore, ObjectStore
from .styling import ElementStyleDict, StyleMatcher, wrap_element
from .transform import SVGTransform
from .utils import svg_markup, length_as_pixels, length_as_points, parse_svg_path, SVG_NS, XLINK_HREF

#===============================================================================

IMAGE_MEDIA_TYPES = ['image/jpeg', 'image/png']

#===============================================================================

IGNORED_SVG_TAGS = [
    SVG_NS('style'),
    SVG_NS('title'),
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
            colour = webcolors.rgb_percent_to_rgb(rgb)
        else:
            colour = [int(c) for c in rgb]
    else:
        colour = webcolors.html5_parse_legacy_color(colour_string)
    return skia.Color(*tuple(colour), round(255*opacity))

#===============================================================================

class GradientStops(object):
    def __init__(self, element):
        self.__offsets = []
        self.__colours = []
        for stop in element:
            if stop.tag == SVG_NS('stop'):
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
    def __init__(self, paint, bounds, parent_transform, transform_attribute, clip_path,
                    bbox=None, root_object=False, scale=1.0):
        if root_object:
            T = parent_transform@SVGTransform(transform_attribute)
            self.__matrix = skia.Matrix(list(T.flatten()))
        else:
            T = parent_transform
            if transform_attribute is None:
                self.__matrix = None
            else:
                local_transform = SVGTransform(transform_attribute)
                self.__matrix = skia.Matrix(list(local_transform.flatten()))
                T = T@local_transform
        if scale != 1.0:
            if self.__matrix is not None:
                self.__matrix = self.__matrix.preScale(1.0/scale, 1.0/scale)
        if bounds is not None and bbox is None:
            bbox = T.transform_geometry(shapely.geometry.box(*tuple(bounds)))
        self.__bbox = bbox
        self.__prep_bbox = shapely.prepared.prep(bbox) if bbox is not None else None
        self.__clip_path = clip_path
        self.__paint = paint
        self.__save_state = (self.__matrix is not None
                          or self.__clip_path is not None)

    @property
    def bbox(self):
        return self.__bbox

    @property
    def paint(self):
        return self.__paint

    def draw_element(self, canvas, tile_bbox):
    #=========================================
        pass

    def intersects(self, bbox):
    #==========================
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
    def __init__(self, path, paint, parent_transform, transform_attribute, clip_path):
        super().__init__(paint, path.getBounds(), parent_transform, transform_attribute, clip_path)
        self.__path = path

    def draw_element(self, canvas, tile_bbox):
    #=========================================
        if self.intersects(tile_bbox):
            with self.transformed_clipped_canvas(canvas):
                canvas.drawPath(self.__path, self.paint)

#===============================================================================

class CanvasImage(CanvasDrawingObject):
    def __init__(self, image, paint, parent_transform, transform_attribute, clip_path, scale=1.0):
        super().__init__(paint, image.bounds(), parent_transform, transform_attribute, clip_path, scale=scale)
        self.__image = image

    def draw_element(self, canvas, tile_bbox):
    #=========================================
        if self.intersects(tile_bbox):
            with self.transformed_clipped_canvas(canvas):
                canvas.drawImage(self.__image, 0, 0, self.paint)

#===============================================================================

class CanvasText(CanvasDrawingObject):
    def __init__(self, text, attribs, parent_transform, transform_attribute, clip_path):
        self.__text = text
        style_rules = dict([rule.split(':', 1) for rule in [rule.strip() for rule in attribs.get('style', '')[:-1].split(';')]])
        self.__font = skia.Font(skia.Typeface(style_rules.get('font-family', 'Calibri'),
                                              skia.FontStyle(int(style_rules.get('font-weight', skia.FontStyle.kNormal_Weight)),
                                                             skia.FontStyle.kNormal_Width,
                                                             skia.FontStyle.kUpright_Slant)),
                                length_as_points(style_rules.get('font-size', 10)))
        self.__pos = [float(attribs['x']), float(attribs['y'])]
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
        self.__paint = skia.Paint(AntiAlias=True, Color=skia.ColorBLACK)
        super().__init__(None, bounds, parent_transform, transform_attribute, clip_path)

    def draw_element(self, canvas, tile_bbox):
    #=========================================
        if self.intersects(tile_bbox):
            with self.transformed_clipped_canvas(canvas):
                canvas.drawString(self.__text, self.__pos[0], self.__pos[1], self.__font, self.__paint)

#===============================================================================

class CanvasGroup(CanvasDrawingObject):
    def __init__(self, drawing_objects, parent_transform, transform_attribute, clip_path, outermost=False):
        bbox = (shapely.ops.unary_union([element.bbox for element in drawing_objects]).envelope
                    if len(drawing_objects) > 0 else
                None)
        super().__init__(None, None, parent_transform, transform_attribute, clip_path, bbox=bbox, root_object=outermost)
        self.__drawing_objects = drawing_objects

    @property
    def is_valid(self):
        return len(self.__drawing_objects) > 0

    def draw_element(self, canvas, tile_bbox):
    #=========================================
        if self.intersects(tile_bbox):
            with self.transformed_clipped_canvas(canvas):
                for element in self.__drawing_objects:
                    element.draw_element(canvas, tile_bbox)

#===============================================================================
#===============================================================================

class SVGTiler(object):
    def __init__(self, raster_layer, tile_set):
        self.__bbox = shapely.geometry.box(*extent_to_bounds(raster_layer.extent))
        self.__svg = etree.parse(raster_layer.source_data).getroot()
        self.__source_path = raster_layer.source_path
        if 'viewBox' in self.__svg.attrib:
            self.__size = tuple(float(x)
                for x in self.__svg.attrib['viewBox'].split()[2:])
        else:
            self.__size = (length_as_pixels(self.__svg.attrib['width']),
                           length_as_pixels(self.__svg.attrib['height']))
        self.__scaling = (tile_set.pixel_rect.width/self.__size[0],
                          tile_set.pixel_rect.height/self.__size[1])
        self.__definitions = DefinitionStore()
        self.__style_matcher = StyleMatcher(self.__svg.find(SVG_NS('style')))
        self.__clip_paths = ObjectStore()

        # Transform from SVG pixels to tile pixels
        svg_to_tile_transform = Transform([[self.__scaling[0],               0.0, 0.0],
                                           [              0.0, self.__scaling[1], 0.0],
                                           [              0.0,               0.0, 1.0]])

        # Transform from SVG pixels to world coordinates
        self.__image_to_world = (Transform([
            [WORLD_METRES_PER_PIXEL/self.__scaling[0],                                        0, 0],
            [                                       0, WORLD_METRES_PER_PIXEL/self.__scaling[1], 0],
            [                                       0,                                        0, 1]])
           @np.array([[1.0,  0.0, -self.__scaling[0]*self.__size[0]/2.0],
                      [0.0, -1.0,  self.__scaling[1]*self.__size[1]/2.0],
                      [0.0,  0.0,                                   1.0]]))

        self.__tile_size = tile_set.tile_size
        self.__tile_origin = tile_set.start_coords
        self.__pixel_offset = tuple(tile_set.pixel_rect)[0:2]

        self.__tile_bboxes = {}
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
        log('Making image snapshot...')
        image = surface.makeImageSnapshot()
        return image.toarray(colorType=skia.kBGRA_8888_ColorType)

    def get_tile(self, tile):
    #========================
        surface = skia.Surface(*self.__tile_size)  ## In pixels...
        canvas = surface.getCanvas()
        canvas.clear(skia.Color4f(0xFFFFFFFF))
        canvas.translate(self.__pixel_offset[0] + (self.__tile_origin[0] - tile.x)*self.__tile_size[0],
                         self.__pixel_offset[1] + (self.__tile_origin[1] - tile.y)*self.__tile_size[1])
        quadkey = mercantile.quadkey(tile)
        self.__svg_drawing.draw_element(canvas, self.__tile_bboxes.get(quadkey))
        image = surface.makeImageSnapshot()
        return image.toarray(colorType=skia.kBGRA_8888_ColorType)

    def __draw_svg(self, svg_to_tile_transform, show_progress=False):
    #================================================================
        wrapped_svg = wrap_element(self.__svg)
        drawing_objects = self.__draw_element_list(wrapped_svg,
            svg_to_tile_transform@SVGTransform(wrapped_svg.etree_element.attrib.get('transform')),
            None,
            show_progress=show_progress)
        attributes = wrapped_svg.etree_element.attrib
        return CanvasGroup(drawing_objects, svg_to_tile_transform,
                    attributes.get('transform'),
                    None,
                    outermost=True)

    def __draw_group(self, group, parent_transform, parent_style):
    #=============================================================
        group_style = self.__style_matcher.element_style(group, parent_style)
        group_clip_path = group_style.pop('clip-path', None)
        drawing_objects = self.__draw_element_list(group,
            parent_transform@SVGTransform(group.etree_element.attrib.get('transform')),
            group_style)
        return CanvasGroup(drawing_objects, parent_transform,
                    group.etree_element.attrib.get('transform'),
                    self.__clip_paths.get_by_url(group_clip_path))

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
            if element.tag == SVG_NS('defs'):
                self.__definitions.add_definitions(element)
                continue
            elif element.tag == SVG_NS('use'):
                element = self.__definitions.use(element)
                wrapped_element = wrap_element(element)
            elif element.tag in [SVG_NS('linearGradient'), SVG_NS('radialGradient')]:
                self.__definitions.add_definition(element)
                continue
            elif element.tag == SVG_NS('clipPath'):
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
            if element.tag == SVG_NS('use'):
                element = self.__definitions.use(element)
            if (element is not None
            and element.tag in [SVG_NS('circle'), SVG_NS('ellipse'), SVG_NS('line'),
                               SVG_NS('path'), SVG_NS('polyline'), SVG_NS('polygon'),
                               SVG_NS('rect')]):
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

        if element.tag == SVG_NS('g'):
            canvas_group = self.__draw_group(wrapped_element, parent_transform, parent_style)
            if canvas_group.is_valid:
                drawing_objects.append(canvas_group)

        elif element.tag == SVG_NS('a'):
            link_elements = self.__draw_element_list(wrapped_element, parent_transform, parent_style)
            drawing_objects.extend(link_elements)

        elif element.tag in [SVG_NS('circle'), SVG_NS('ellipse'), SVG_NS('line'),
                             SVG_NS('path'), SVG_NS('polyline'), SVG_NS('polygon'),
                             SVG_NS('rect')]:

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
                    elif gradient.tag == SVG_NS('linearGradient'):
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
                    elif gradient.tag == SVG_NS('radialGradient'):
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

                drawing_objects.append(CanvasPath(path, paint, parent_transform,
                    element.attrib.get('transform'),
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
                if dasharray is not None:
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
                drawing_objects.append(CanvasPath(path, paint, parent_transform,
                    element.attrib.get('transform'),
                    self.__clip_paths.get_by_url(element.attrib.get('clip-path'))
                    ))

        elif element.tag == SVG_NS('image'):
            image_href = element.attrib.get(XLINK_HREF)
            pixel_bytes = None
            if image_href is not None:
                if image_href.startswith('data:'):
                    parts = image_href[5:].split(',', 1)
                    if parts[0].endswith(';base64'):
                        media_type = parts[0].split(';', 1)[0]
                        if media_type in IMAGE_MEDIA_TYPES:
                            pixel_bytes = base64.b64decode(parts[1])
                else:
                    pixel_bytes = self.__source_path.join_path(image_href).get_data()
                if pixel_bytes is not None:
                    pixel_array = np.frombuffer(pixel_bytes, dtype=np.uint8)
                    pixels = cv2.imdecode(pixel_array, cv2.IMREAD_UNCHANGED)    # type: ignore
                    if pixels.shape[2] == 3:
                        pixels = cv2.cvtColor(pixels, cv2.COLOR_RGB2RGBA)       # type: ignore
                    image = skia.Image.fromarray(pixels, colorType=skia.kBGRA_8888_ColorType)
                    width = float(element.attrib.get('width', image.width()))
                    height = float(element.attrib.get('height', image.height()))
                    scale = 1.0
                    for n, prescale_size in enumerate(PRESCALE_IMAGE_SIZES):
                        if width < prescale_size or height < prescale_size:
                            scale = PRESCALE_FACTORS[n]
                            width *= scale
                            height *= scale
                            break
                    if round(width) != image.width() or round(height) != image.height():
                        image = image.resize(round(width), round(height), skia.FilterQuality.kHigh_FilterQuality)
                    paint = skia.Paint()
                    opacity = float(element_style.get('opacity', 1.0))
                    paint.setAlpha(round(opacity * 255))
                    clip_path_url = element_style.pop('clip-path', None)
                    if ((clip_path := self.__clip_paths.get_by_url(clip_path_url)) is None
                    and (clip_path_element := self.__definitions.get_by_url(clip_path_url)) is not None):
                        clip_path = self.__get_clip_path(clip_path_element)
                    drawing_objects.append(CanvasImage(image, paint, parent_transform,
                        element.attrib.get('transform'), clip_path, scale=scale))

        elif element.tag == SVG_NS('text'):
            drawing_objects.append(CanvasText(element.text, element.attrib, parent_transform,
                element.attrib.get('transform'),
                self.__clip_paths.get_by_url(element_style.get('clip-path'))
            ))

        elif element.tag not in IGNORED_SVG_TAGS:
            log.warning("'{}' not supported...".format(element.tag))

        return drawing_objects

    @staticmethod
    def __get_graphics_path(element):
    #================================
        if element.tag == SVG_NS('path'):
            tokens = list(parse_svg_path(element.attrib.get('d', '')))
            path = SVGTiler.__path_from_tokens(tokens)
        elif element.tag == SVG_NS('rect'):
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
        elif element.tag == SVG_NS('line'):
            x1 = length_as_pixels(element.attrib.get('x1', 0))
            y1 = length_as_pixels(element.attrib.get('y1', 0))
            x2 = length_as_pixels(element.attrib.get('x2', 0))
            y2 = length_as_pixels(element.attrib.get('y2', 0))
            path = SVGTiler.__path_from_tokens(['M', x1, y1, x2, y2])
        elif element.tag == SVG_NS('polyline'):
            points = element.attrib.get('points', '').replace(',', ' ').split()
            path = SVGTiler.__path_from_tokens(['M'] + points)
        elif element.tag == SVG_NS('polygon'):
            points = [ float(p) for p in element.attrib.get('points', '').replace(',', ' ').split() ]
            skia_points = [skia.Point(*points[n:n+2]) for n in range(0, len(points), 2)]
            path = skia.Path.Polygon(skia_points, True)
        elif element.tag == SVG_NS('circle'):
            r = length_as_pixels(element.attrib.get('r', 0))
            if r == 0: return None
            (cx, cy) = (length_as_pixels(element.attrib.get('cx', 0)),
                        length_as_pixels(element.attrib.get('cy', 0)))
            path = skia.Path.Circle(cx, cy, r)
        elif element.tag == SVG_NS('ellipse'):
            (rx, ry) = (length_as_pixels(element.attrib.get('rx', 0)),
                        length_as_pixels(element.attrib.get('ry', 0)))
            if rx == 0 or ry == 0: return None
            (cx, cy) = (length_as_pixels(element.attrib.get('cx', 0)),
                        length_as_pixels(element.attrib.get('cy', 0)))
            path = skia.Path.Oval(skia.Rect(cx-rx, cy-ry, cx+rx, cy+ry))
        else:
            path = None
        return path

    @staticmethod
    def __path_from_tokens(tokens):
    #==============================
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
