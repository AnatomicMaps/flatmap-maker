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

import math
import re

#===============================================================================

import cssselect2
from lxml import etree
import skia
import tinycss2

#===============================================================================

from .. import WORLD_METRES_PER_PIXEL
from .. import EXCLUDE_SHAPE_TYPES, EXCLUDE_TILE_LAYERS

from ..markup import parse_markup

from mapmaker.geometry import degrees, radians, Transform, reflect_point

from .definitions import DefinitionStore
from .transform import SVGTransform
from .utils import adobe_decode, length_as_pixels, SVG_NS

#===============================================================================

def make_colour(hex_string, opacity):
    if hex_string.startswith('#'):
        if len(hex_string) == 4:
            rgb = tuple(2*c for c in hex_string[1:])
        else:
            rgb = tuple(hex_string[n:n+2] for n in range(1, 6, 2))
        colour = tuple(int(c, 16) for c in (rgb[2], rgb[1], rgb[0]))
        return skia.Color(*colour, int(255*opacity))
    else:
        return skia.Color(0, 0, 0, 128)

#===============================================================================

class GradientStops(object):
    def __init__(self, element):
        self.__offsets = []
        self.__colours = []
        for stop in element:
            if stop.tag == SVG_NS('stop'):
                styling = ElementStyle(stop)
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

class ElementStyle(object):
    def __init__(self, element, style_dict={}):
        self.__attributes = element.attrib
        self.__style_dict = style_dict
        if 'style' in self.__attributes:
            local_style = {}
            for declaration in tinycss2.parse_declaration_list(
                self.__attributes['style'],
                skip_comments=True, skip_whitespace=True):
                local_style[declaration.lower_name] = ' '.join(
                    [t.serialize() for t in declaration.value])
            self.__style_dict.update(local_style)

    def get(self, key, default=None):
    #================================
        if key in self.__attributes:
            return self.__attributes[key]
        return self.__style_dict.get(key, default)

#===============================================================================

class StyleMatcher(cssselect2.Matcher):
    '''Parse CSS and add rules to the matcher.'''
    def __init__(self, style_element):
        super().__init__()
        rules = tinycss2.parse_stylesheet(style_element.text
                    if style_element is not None else '',
                    skip_comments=True, skip_whitespace=True)
        for rule in rules:
            selectors = cssselect2.compile_selector_list(rule.prelude)
            declarations = [obj for obj in tinycss2.parse_declaration_list(
                                               rule.content,
                                               skip_whitespace=True)
                            if obj.type == 'declaration']
            for selector in selectors:
                self.add_selector(selector, declarations)

    def match(self, element):
    #========================
        styling = {}
        matches = super().match(element)
        if matches:
            for match in matches:
                specificity, order, pseudo, declarations = match
                for declaration in declarations:
                    styling[declaration.lower_name] = declaration.value
        return styling

    def element_style(self, wrapped_element):
    #========================================
        return ElementStyle(wrapped_element.etree_element,
                            { key: ' '.join([t.serialize() for t in value])
                                for key, value in self.match(wrapped_element).items()
                            })

#===============================================================================

class SVGTiler(object):
    def __init__(self, source_path):
        self.__source_path = source_path
        self.__svg = etree.parse(source_path).getroot()
        if 'viewBox' in self.__svg.attrib:
            (width, height) = tuple(float(x)
                for x in self.__svg.attrib['viewBox'].split()[2:])
        else:
            width = length_as_pixels(self.__svg.attrib['width'])
            height = length_as_pixels(self.__svg.attrib['height'])
        self.__transform = Transform([[1, 0, 0],
                                      [0, 1, 0],
                                      [0, 0, 1]])
        self.__definitions = DefinitionStore()
        self.__style_matcher = StyleMatcher(self.__svg.find(SVG_NS('style')))
        self.__surface = skia.Surface(int(width), int(height))
        self.__canvas = self.__surface.getCanvas()

    def process(self):
    #=================
        wrapped_svg = cssselect2.ElementWrapper.from_xml_root(self.__svg)
        self.__process_element_list(wrapped_svg, self.__transform)

    def image(self):
    #===============
        return self.__surface.makeImageSnapshot().toarray()

    def __process_group(self, group, transform):
    #===========================================
        self.__process_element_list(group,
            transform@SVGTransform(group.etree_element.attrib.get('transform')))

    def __process_element_list(self, elements, transform):
    #=====================================================
        for wrapped_element in elements.iter_children():
            element = wrapped_element.etree_element
            if element.tag == SVG_NS('defs'):
                self.__definitions.add_definitions(element)
                continue
            elif element.tag == SVG_NS('use'):
                element = self.__definitions.use(element)
                wrapped_element = cssselect2.ElementWrapper.from_xml_root(element)
            elif element.tag in [SVG_NS('linearGradient'), SVG_NS('radialGradient')]:
                self.__definitions.add_definition(element)
                continue
            self.__process_element(wrapped_element, transform)

    def __process_element(self, wrapped_element, transform):
    #=======================================================
        element = wrapped_element.etree_element
        element_style = self.__style_matcher.element_style(wrapped_element)

        if element.tag == SVG_NS('g'):
            self.__process_group(wrapped_element, transform)

        elif element.tag in [SVG_NS('circle'), SVG_NS('ellipse'), SVG_NS('line'),
                             SVG_NS('path'), SVG_NS('polyline'), SVG_NS('polygon'),
                             SVG_NS('rect')]:

            path = self.__get_graphics_path(element, transform)
            if path is None: return

            ## Or simply don't stroke as Mapbox will draw boundaries...
            stroke = element_style.get('stroke', 'none')
            if False and stroke.startswith('#'):
                opacity = float(element_style.get('stroke-opacity', 1.0))
                paint = skia.Paint(AntiAlias=True,
                    Style=skia.Paint.kStroke_Style,
                    Color=make_colour(stroke, opacity),
                    StrokeWidth=1)  ## Use actual stroke-width?? Scale??
                self.__canvas.drawPath(path, paint)

            fill = element_style.get('fill', '#FFF')
            if fill == 'none': return

            path.setFillType(skia.PathFillType.kWinding)
            opacity = float(element_style.get('opacity', 1.0))
            paint = skia.Paint(AntiAlias=True)

            if fill.startswith('url('):
                gradient = self.__definitions.lookup(fill[4:-1])
                if gradient is None:
                    fill = '#800'     # Something's wrong show show in image...
                    opacity = 0.5
                elif gradient.tag == SVG_NS('linearGradient'):
                    gradient_stops = GradientStops(gradient)
                    svg_transform = SVGTransform(gradient.attrib.get('gradientTransform'))
                    if gradient.attrib.get('gradientUnits') == 'userSpaceOnUse':
                        points = [(float(gradient.attrib.get('x1')),
                                   float(gradient.attrib.get('y1'))),
                                  (float(gradient.attrib.get('x2')),
                                   float(gradient.attrib.get('y2')))]
                    else:
                        bounds = path.getBounds()
                        v_centre = (bounds.top() + bounds.bottom())/2
                        points=[(bounds.left(), v_centre), (bounds.right(), v_centre)]
                    paint.setShader(skia.GradientShader.MakeLinear(
                        points=points,
                        positions=gradient_stops.offsets,
                        colors=gradient_stops.colours,
                        localMatrix=skia.Matrix(list(svg_transform.flatten()))
                    ))
                elif gradient.tag == SVG_NS('radialGradient'):
                    gradient_stops = GradientStops(gradient)
                    svg_transform = SVGTransform(gradient.attrib.get('gradientTransform'))
                    cx = float(gradient.attrib.get('cx'))
                    cy = float(gradient.attrib.get('cx'))
                    r = float(gradient.attrib.get('r'))
                    if gradient.attrib.get('gradientUnits') == 'userSpaceOnUse':
                        centre = svg_transform.scale_length((cx, cy))
                        radius = r
                    else:
                        bounds = path.getBounds()
                        centre = (bounds.left() + cx*bounds.width(),
                                  bounds.top() + cy*bounds.height())
                        radius = math.sqrt(bounds.width()**2 + bounds.height()**2)/2.0
                    ## Transform centre, radius....
                    paint.setShader(skia.GradientShader.MakeRadial(
                        center=centre,
                        radius=radius,
                        positions=gradient_stops.offsets,
                        colors=gradient_stops.colours,
                        #localMatrix=skia.Matrix(list(svg_transform.flatten()))
                    ))
                else:
                    fill = '#008'     # Something's wrong show show in image...
                    opacity = 0.5

            if fill.startswith('#'):
                paint.setColor(make_colour(fill, opacity))
            self.__canvas.drawPath(path, paint)


    @staticmethod
    def __svg_path_matcher(m):
    #=========================
    # Helper for parsing `d` attrib of a path
        c = m[0]
        if c.isalpha(): return ' ' + c + ' '
        if c == '-': return ' -'
        if c == ',': return ' '
        return c

    def __get_graphics_path(self, element, transform):
    #=================================================
        T = transform@SVGTransform(element.attrib.get('transform'))
        if element.tag == SVG_NS('path'):
            tokens = re.sub('.', SVGTiler.__svg_path_matcher,
                            element.attrib.get('d', '')).split()
            path = self.__path_from_tokens(tokens, T)

        elif element.tag == SVG_NS('rect'):
            (width, height) = T.scale_length(length_as_pixels(element.attrib.get('width', 0)),
                                             length_as_pixels(element.attrib.get('height', 0)))
            if width == 0 or height == 0: return None
            (rx, ry) = T.scale_length(length_as_pixels(element.attrib.get('rx')),
                                      length_as_pixels(element.attrib.get('ry')))
            if rx is None and ry is None:
                rx = ry = 0
            elif ry is None:
                ry = rx
            elif rx is None:
                rx = ry
            rx = min(rx, width/2)
            ry = min(ry, height/2)
            (x, y) = T.transform_point(length_as_pixels(element.attrib.get('x', 0)),
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
            path = self.__path_from_tokens(['M', x1, y1, x2, y2], T)

        elif element.tag == SVG_NS('polyline'):
            points = element.attrib.get('points', '').replace(',', ' ').split()
            path = self.__path_from_tokens(['M'] + points, T)

        elif element.tag == SVG_NS('polygon'):
            points = element.attrib.get('points', '').replace(',', ' ').split()
            skia_points = [skia.Point(*T.transform_point(points[n:n+2]))
                                            for n in range(0, len(points), 2)]
            path = skia.Path.Polygon(skia_points, True)

        elif element.tag == SVG_NS('circle'):
            r = length_as_pixels(element.attrib.get('r', 0))
            if r == 0: return None
            (cx, cy) = T.transform_point(length_as_pixels(element.attrib.get('cx', 0)),
                                         length_as_pixels(element.attrib.get('cy', 0)))
            path = skia.Path.Circle(cx, cy, r)

        elif element.tag == SVG_NS('ellipse'):
            (rx, ry) = T.scale_length(length_as_pixels(element.attrib.get('rx', 0)),
                                      length_as_pixels(element.attrib.get('ry', 0)))
            if rx == 0 or ry == 0: return None
            (cx, cy) = T.transform_point(length_as_pixels(element.attrib.get('cx', 0)),
                                         length_as_pixels(element.attrib.get('cy', 0)))
            path = skia.Path.Oval((cx-rx, cy-ry, cx+rx, cy+ry))

        return path

    def __path_from_tokens(self, tokens, transform):
    #===============================================
        moved = False
        first_point = None
        current_point = None
        closed = False
        path = skia.Path()
        pos = 0
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
                phi = radians(params[2])
                if moved:
                    path.moveTo(*transform.transform_point(current_point))
                    moved = False
                (rx, ry) = transform.scale_length(params[0:2])
                path.arcTo(rx, ry, degrees(transform.rotate_angle(phi)),
                    skia.Path.ArcSize.kSmall_ArcSize if params[3] == 0
                        else skia.Path.ArcSize.kLarge_ArcSize,
                    skia.PathDirection.kCCW if params[4] == 0
                        else skia.PathDirection.kCW,
                    *transform.transform_point(pt))
                current_point = pt

            elif cmd in ['c', 'C', 's', 'S']:
                if moved:
                    path.moveTo(*transform.transform_point(current_point))
                    moved = False
                if cmd in ['c', 'C']:
                    n_params = 6
                    coords = []
                else:
                    n_params = 4
                    if second_cubic_control is None:
                        coords = list(transform.transform_point(current_point))
                    else:
                        coords = list(transform.transform_point(
                                    reflect_point(second_cubic_control, current_point)))
                params = [float(x) for x in tokens[pos:pos+n_params]]
                pos += n_params
                for n in range(0, n_params, 2):
                    pt = params[n:n+2]
                    if cmd.islower():
                        pt[0] += current_point[0]
                        pt[1] += current_point[1]
                    if n == (n_params - 4):
                        second_cubic_control = pt
                    coords.extend(transform.transform_point(pt))
                path.cubicTo(*coords)
                current_point = pt

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
                    path.moveTo(*transform.transform_point(current_point))
                    moved = False
                path.lineTo(*transform.transform_point(pt))
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
                    path.moveTo(*transform.transform_point(current_point))
                    moved = False
                if cmd in ['t', 'T']:
                    n_params = 4
                    coords = []
                else:
                    n_params = 2
                    if second_quad_control is None:
                        coords = list(transform.transform_point(current_point))
                    else:
                        coords = list(transform.transform_point(
                                    reflect_point(second_quad_control, current_point)))
                params = [float(x) for x in tokens[pos:pos+n_params]]
                pos += n_params
                for n in range(0, n_params, 2):
                    pt = params[n:n+2]
                    if cmd.islower():
                        pt[0] += current_point[0]
                        pt[1] += current_point[1]
                    if n == (n_params - 4):
                        second_quad_control = pt
                    coords.extend(transform.transform_point(pt))
                path.quadTo(*coords)
                current_point = pt

            elif cmd in ['z', 'Z']:
                if first_point is not None and current_point != first_point:
                    pass
                    #path.close()
                closed = True
                first_point = None

            else:
                print('Unknown path command: {}'.format(cmd))
        return path

#===============================================================================
