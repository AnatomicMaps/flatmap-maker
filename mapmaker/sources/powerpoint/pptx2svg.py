#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019 - 2022 David Brooks
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

from __future__ import annotations
from collections import OrderedDict
from math import sqrt, sin, cos, acos, pi as PI
import os
from pathlib import Path
import re
from typing import Optional

#===============================================================================

from lxml import etree
import numpy as np
import svgwrite
from svgwrite.base import BaseElement as SvgElement
from tqdm import tqdm
import transforms3d

#===============================================================================

import shapely.geometry
import shapely.strtree

#===============================================================================

from beziers.cubicbezier import CubicBezier
from beziers.path import BezierPath
from beziers.point import Point as BezierPoint
from beziers.quadraticbezier import QuadraticBezier

#===============================================================================

import pptx.shapes.connector
from pptx import Presentation
from pptx.dml.fill import FillFormat
from pptx.enum.dml import MSO_FILL_TYPE, MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.enum.text import MSO_VERTICAL_ANCHOR as MSO_ANCHOR
from pptx.enum.text import PP_PARAGRAPH_ALIGNMENT as PP_ALIGN
from pptx.util import Length

from pptx.shapes.base import BaseShape as PptxShape
from pptx.shapes.group import GroupShape as PptxGroupShape
from pptx.shapes.shapetree import GroupShapes as PptxGroupShapes
from pptx.slide import Slide as PptxSlide

#===============================================================================

from mapmaker.geometry.beziers import bezier_sample
from mapmaker.geometry.arc_to_bezier import bezier_segments_from_arc_endpoints, tuple2
from mapmaker.utils import FilePath, log

from .colour import ColourMap, Theme
from .formula import Geometry, radians
from .presets import DML
from .powerpoint import Shape, SHAPE_TYPE

#===============================================================================

PPTX_NAMESPACE = {
    'p': "http://schemas.openxmlformats.org/presentationml/2006/main",
    'a': "http://schemas.openxmlformats.org/drawingml/2006/main",
    'r': "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
}

def pptx_resolve(qname: str) -> str:
#===================================
    parts = qname.split(':', 1)
    if len(parts) == 2 and parts[0] in PPTX_NAMESPACE:
        return f'{{{PPTX_NAMESPACE[parts[0]]}}}{parts[1]}'
    return qname

#===============================================================================

# Internal PPT units are EMUs (English Metric Units)

EMU_PER_CM  = 360000
EMU_PER_IN  = 914400

POINTS_PER_IN = 72

# SVG pixel resolution
PIXELS_PER_IN = 96
EMU_PER_PIXEL = EMU_PER_IN/PIXELS_PER_IN

# Minimum width for a stroked path in points
MIN_STROKE_WIDTH = 0.5

TEXT_MARGINS = (4, 1)    # pixels

#===============================================================================

def text_alignment(shape):
#=========================
    para = shape.text_frame.paragraphs[0].alignment
    vertical = shape.text_frame.vertical_anchor
    return ('left' if para in [PP_ALIGN.LEFT, PP_ALIGN.DISTRIBUTE, PP_ALIGN.JUSTIFY, PP_ALIGN.JUSTIFY_LOW] else
            'right' if para == PP_ALIGN.RIGHT else
            'centre',
            'top' if vertical == MSO_ANCHOR.TOP else
            'bottom' if vertical == MSO_ANCHOR.BOTTOM else
            'middle')

def text_content(shape):
#=======================
    text = shape.text.replace('\n', ' ').replace('\xA0', ' ').replace('\v', ' ').strip() # Newline, non-breaking space, vertical-tab
    return text if text not in ['', '.'] else None

#===============================================================================

def emu_to_pixels(emu):
#======================
    return emu/EMU_PER_PIXEL

def points_to_pixels(pts):
#=========================
    return pts*PIXELS_PER_IN/POINTS_PER_IN

#===============================================================================

def ellipse_point(a, b, theta):
#==============================
    a_sin_theta = a*sin(theta)
    b_cos_theta = b*cos(theta)
    circle_radius = sqrt(a_sin_theta**2 + b_cos_theta**2)
    return (a*b_cos_theta/circle_radius, b*a_sin_theta/circle_radius)

#===============================================================================

ARROW_MARKERS = {
    'triangle-head': 'M 10 0 L 0 5 L 10 10 z',
    'triangle-tail': 'M 0 0 L 10 5 L 0 10 z'
}

## NB. Adobe Illustrator 2020 doesn't appear to support marker definitions in SVG

def add_marker_definitions(drawing):
#===================================
    # arrowhead markers (see https://developer.mozilla.org/en-US/docs/Web/SVG/Element/marker)
    # 18 Jan 2023: markers appear in Chrome with black fill; no markers in Firefox
    for id, path in ARROW_MARKERS.items():
        marker = drawing.marker(id=id,
                                viewBox="0 0 10 10",
                                refX="5", refY="5",
                                markerUnits="userSpaceOnUse",
                                markerWidth="6",
                                markerHeight="6",
                                orient="auto")
        marker.add(drawing.path(d=path))   ## , fill='context-stroke' is not supported by svgwrite
        drawing.defs.add(marker)

def marker_id(marker_def, end):
#==============================
    marker_type = marker_def.get('type')
    return ('#{}-{}'.format(marker_type, end)
            if marker_type is not None
            else None)

#===============================================================================

# Don't set a path id for default shape names

EXCLUDED_NAME_PREFIXES = [
    'Freeform',
    'Group',
    'Oval',
    'Star',
]

# Markup that has been deprecated

EXCLUDED_NAME_MARKUP = [
    '.siblings',
]

# Check to see if we have a valid name and encode it as an id

def valid_markup(name):
#======================
    if name not in EXCLUDED_NAME_MARKUP:
        for prefix in EXCLUDED_NAME_PREFIXES:
            if name.startswith(prefix):
                return False
        return True
    return False

def add_markup(element, markup):
#===============================
    if valid_markup(markup):
        element.set_desc(title=markup)

def add_class(xml, cls):
#=======================
    if 'class' not in xml.attribs:
        xml.attribs['class'] = cls
    else:
        xml.attribs['class'] += f' {cls}'

#===============================================================================

class Gradient(object):
    def __init__(self, dwg, id, shape, colour_map):
        self.__id = 'gradient-{}'.format(id)
        fill = shape.fill
        gradient = None
        if fill._fill._gradFill.path is None:
            gradient = svgwrite.gradients.LinearGradient(id=self.__id)
            rotation = fill.gradient_angle
            if ('rotWithShape' in fill._fill._gradFill.attrib
             and fill._fill._gradFill.attrib['rotWithShape'] == '1'):
                rotation += shape.rotation
            if rotation != 0:
                gradient.rotate(rotation % 360, (0.5, 0.5))

        elif fill._fill._gradFill.path.attrib['path'] == 'circle':
                fill_to = fill._fill._gradFill.path.find('{http://schemas.openxmlformats.org/drawingml/2006/main}fillToRect').attrib
                tileRect = fill._fill._gradFill.find('{http://schemas.openxmlformats.org/drawingml/2006/main}tileRect')
                tile = tileRect.attrib if tileRect is not None else {}
                cx = (float(fill_to['l']) if 'l' in fill_to else float(fill_to['r']) + float(tile.get('l', 0.0)))/100000.0
                cy = (float(fill_to['t']) if 't' in fill_to else float(fill_to['b']) + float(tile.get('t', 0.0)))/100000.0
                sx = (float(fill_to['r']) if 'r' in fill_to else float(fill_to['l']) + float(tile.get('r', 0.0)))/100000.0
                sy = (float(fill_to['b']) if 'b' in fill_to else float(fill_to['t']) + float(tile.get('b', 0.0)))/100000.0
                if shape.width > shape.height:
                    scale_x = shape.height/shape.width
                    scale_y = 1.0
                elif shape.width < shape.height:
                    scale_x = 1.0
                    scale_y = shape.width/shape.height
                else:
                    scale_x = 1.0
                    scale_y = 1.0
                if len(tile) == 0:
                    radius = 1.0
                    if (cx, cy) != (0.5, 0.5) and (sx, sy) != (0.5, 0.5):
                        print('Preset radial gradient for shape:', shape.name)
                else:
                    radius = sqrt(((cx-sx)/scale_x)**2 + ((cy-sy)/scale_y)**2)
                gradient = svgwrite.gradients.RadialGradient((cx/scale_x, cy/scale_y), radius, id=self.__id)
                if shape.rotation != 0:
                    gradient.rotate(shape.rotation, (0.5, 0.5))
                if shape.width != shape.height:
                    gradient.scale(scale_x, scale_y)

        elif fill._fill._gradFill.path.attrib['path'] == 'rect':
            print('Rect fill ignored for', shape.name)
            return

        if gradient is not None:
            for stop in sorted(fill.gradient_stops, key=lambda stop: stop.position):
                gradient.add_stop_color(offset=stop.position,
                    color=colour_map.lookup(stop.color),
                    opacity=stop.color.alpha)
            dwg.defs.add(gradient)
        else:
            print('UNKNOWN FILL: {}\n'.format(shape.name), fill._fill._element.xml)

    @property
    def url(self):
        return 'url(#{})'.format(self.__id)

## WIP  Want list of unique gradient definitions

#===============================================================================

class DrawMLTransform(object):
    def __init__(self, shape, bbox=None):
        if bbox is None:
            bbox = (shape.width, shape.height)

        xfrm = shape.element.xfrm

        # From Section L.4.7.6 of ECMA-376 Part 1
        (Bx, By) = ((xfrm.chOff.x, xfrm.chOff.y)
                        if xfrm.chOff is not None else
                    (0, 0))
        (Dx, Dy) = ((xfrm.chExt.cx, xfrm.chExt.cy)
                        if xfrm.chExt is not None else
                    bbox)
        (Bx_, By_) = (xfrm.off.x, xfrm.off.y)
        (Dx_, Dy_) = (xfrm.ext.cx, xfrm.ext.cy)
        theta = xfrm.rot*PI/180.0
        Fx = -1 if xfrm.flipH else 1
        Fy = -1 if xfrm.flipV else 1
        T_st = np.array([[Dx_/Dx,      0, Bx_ - (Dx_/Dx)*Bx] if Dx != 0 else [1, 0, Bx_],
                         [     0, Dy_/Dy, By_ - (Dy_/Dy)*By] if Dy != 0 else [0, 1, By_],
                         [     0,      0,                 1]])
        U = np.array([[1, 0, -(Bx_ + Dx_/2.0)],
                      [0, 1, -(By_ + Dy_/2.0)],
                      [0, 0,                1]])
        R = np.array([[cos(theta), -sin(theta), 0],
                      [sin(theta),  cos(theta), 0],
                      [0,                    0, 1]])
        Flip = np.array([[Fx,  0, 0],
                         [ 0, Fy, 0],
                         [ 0,  0, 1]])
        T_rf = np.linalg.inv(U)@R@Flip@U
        self.__T = T_rf@T_st

    def matrix(self):
        return self.__T

#===============================================================================

class Transform(object):
    def __init__(self, matrix):
        self.__matrix = np.array(matrix)

    def __matmul__(self, matrix):
        return Transform(self.__matrix@np.array(matrix))

    def __str__(self):
        return str(self.__matrix)

    def rotate_angle(self, angle):
    #==============================
        rotation = transforms3d.affines.decompose(self.__matrix)[1]
        theta = acos(rotation[0, 0])
        if rotation[0, 1] >= 0:
            theta = 2*PI - theta
        angle = angle + theta
        while angle >= 2*PI:
            angle -= 2*PI
        return angle

    def scale_length(self, length):
    #==============================
        scaling = transforms3d.affines.decompose(self.__matrix)[2]
        return (abs(scaling[0]*length[0]), abs(scaling[1]*length[1]))

    def transform_point(self, point):
    #================================
        return (self.__matrix@[point[0], point[1], 1.0])[:2]

#===============================================================================

class SvgLayer(object):
    def __init__(self, size, slide: PptxSlide, slide_number: int, ppt_theme, kind: str='base', shape_filter=None, quiet=False):
        self.__slide = slide
        self.__colour_map = ColourMap(ppt_theme, slide)
        self.__dwg = svgwrite.Drawing(filename=None, size=None)
        self.__dwg.attribs['viewBox'] = f'0 0 {size[0]} {size[1]}'
        add_marker_definitions(self.__dwg)
        self.__id = None
        self.__models = None
        if slide.has_notes_slide:
            notes_slide = slide.notes_slide
            notes_text = notes_slide.notes_text_frame.text
            if notes_text.startswith('.'):
                for part in notes_text[1:].split():
                    id_match = re.match(r'id *\((.*)\)', part)
                    if id_match is not None:
                        self.__id = id_match[1].strip()
                    models_match = re.match(r'models *\((.*)\)', part)
                    if models_match is not None:
                        self.__models = models_match[1].strip()
        if self.__id is None:
            self.__id = 'slide-{:02d}'.format(slide_number)
        self.__gradient_id = 0
        self.__kind = kind
        self.__shape_filter = shape_filter
        self.__quiet =  quiet

    @property
    def id(self):
        return self.__id

    @property
    def models(self):
        return self.__models

    def save(self, file_object):
    #===========================
        self.__dwg.write(file_object, pretty=True, indent=4)

    def get_colour(self, shape: PptxShape, group_colour: Optional[str]=None) -> tuple[Optional[str], float]:
    #=======================================================================================================
        def colour_from_fill(shape, fill):
            if fill.type == MSO_FILL_TYPE.SOLID:
                return (self.__colour_map.lookup(fill.fore_color),
                        fill.fore_color.alpha)
            elif fill.type == MSO_FILL_TYPE.GRADIENT:
                log.warning(f'{shape.name}: gradient fill ignored')
            elif fill.type == MSO_FILL_TYPE.GROUP:
                if group_colour is not None:
                    return group_colour
            elif fill.type is not None and fill.type != MSO_FILL_TYPE.BACKGROUND:
                log.warning(f'{shape.name}: unsupported fill type: {fill.type}')
            return (None, 1.0)

        colour = None
        alpha = 1.0
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            colour, alpha = colour_from_fill(shape, FillFormat.from_fill_parent(shape.element.grpSpPr))
        elif shape.shape_type != MSO_SHAPE_TYPE.LINE:
#        if not isinstance(shape, pptx.shapes.connector.Connector):  ## ????
            colour, alpha = colour_from_fill(shape, shape.fill)
        elif shape.line.fill.type == MSO_FILL_TYPE.SOLID:
            colour = self.__colour_map.lookup(shape.line.color)
            alpha = shape.line.fill.fore_color.alpha
        elif shape.line.fill.type is None:
            # Check for a fill colour in the <style> block
            xml = etree.fromstring(shape.element.xml)
            if (scheme_colour := xml.find('.//p:style/a:fillRef/a:schemeClr',
                                            namespaces=PPTX_NAMESPACE)) is not None:
                colour = self.__colour_map.scheme_colour(scheme_colour.attrib['val'])
        elif shape.line.fill.type != MSO_FILL_TYPE.BACKGROUND:
            log.warning(f'{shape.name}: unsupported line fill type: {shape.line.fill.type}')
        return (colour, alpha)

    def process(self, transform: Transform):
    #=======================================
        self.process_shape_list(self.__slide.shapes, self.__dwg, transform,  not self.__quiet)
        if self.__kind == 'base' and self.__shape_filter is not None:
            self.__shape_filter.create_filter()

    def process_group(self, group: PptxGroupShape, svg_parent: SvgElement, transform: Transform):
    #============================================================================================
        svg_group = self.__dwg.g(id=group.shape_id)
        add_markup(svg_group, group.name)
        svg_parent.add(svg_group)
        self.process_shape_list(group.shapes, svg_group, transform@DrawMLTransform(group).matrix(),
                                group_colour=self.get_colour(group))

    def process_shape_list(self, shapes: PptxGroupShapes, svg_parent: SvgElement, transform: Transform, group_colour: str=None, show_progress: bool=False):
    #===================================================================================================
        if show_progress:
            print('Processing shape list...')
            progress_bar = tqdm(total=len(shapes),
                unit='shp', ncols=40,
                bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}')
        for shape in shapes:
            if (shape.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE
             or shape.shape_type == MSO_SHAPE_TYPE.FREEFORM
             or shape.shape_type == MSO_SHAPE_TYPE.TEXT_BOX
             or isinstance(shape, pptx.shapes.connector.Connector)):
                self.process_shape(shape, svg_parent, transform, group_colour=group_colour)
            elif shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                self.process_group(shape, svg_parent, transform)
            elif shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                pass
            else:
                print('"{}" {} not processed...'.format(shape.name, str(shape.shape_type)))
            if show_progress:
                progress_bar.update(1)
        if show_progress:
            progress_bar.close()

    def process_shape(self, shape: PptxShape, svg_parent: SvgElement, transform: Transform, group_colour: str=None):
    #===============================================================================================================

        closed = False
        coordinates = []
        pptx_geometry = Geometry(shape)

        svg_path = self.__dwg.path(id=shape.shape_id, fill='none', class_='non-scaling-stroke')

        for path in pptx_geometry.path_list:
            bbox = (shape.width, shape.height) if path.w is None else (path.w, path.h)
            T = transform@DrawMLTransform(shape, bbox).matrix()

            current_point = []
            first_point = None
            moved = False

            exclude_shape = False
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
                    phi = T.rotate_angle(0)
                    large_arc_flag = 0
                    svg_path.push('A', *T.scale_length((wR, hR)),
                                       180*phi/PI, large_arc_flag, 1,
                                       *T.transform_point(pt))
                    large_arc_flag = 1 if swAng >= PI else 0
                    segs = bezier_segments_from_arc_endpoints(tuple2(wR, hR),
                                        0, large_arc_flag, 1,
                                        tuple2(*current_point), tuple2(*pt),
                                        T)
                    coordinates.extend(bezier_sample(BezierPath.fromSegments(segs)))
                    current_point = pt
                elif c.tag == DML('close'):
                    svg_path.push('Z')
                    closed = True
                    if first_point is not None and current_point != first_point:
                        coordinates.append(T.transform_point(first_point))
                    first_point = None
                elif c.tag == DML('cubicBezTo'):
                    coords = []
                    bz_coords = [BezierPoint(*T.transform_point(current_point))]
                    for p in c.getchildren():
                        pt = pptx_geometry.point(p)
                        coords.extend(T.transform_point(pt))
                        bz_coords.append(BezierPoint(*T.transform_point(pt)))
                        current_point = pt
                    svg_path.push('C', *coords)
                    bz = CubicBezier(*bz_coords)
                    coordinates.extend(bezier_sample(bz))
                elif c.tag == DML('lnTo'):
                    pt = pptx_geometry.point(c.pt)
                    coords = T.transform_point(pt)
                    svg_path.push('L', *coords)
                    if moved:
                        coordinates.append(T.transform_point(current_point))
                        moved = False
                    coordinates.append(coords)
                    current_point = pt
                elif c.tag == DML('moveTo'):
                    pt = pptx_geometry.point(c.pt)
                    coords = T.transform_point(pt)
                    svg_path.push('M', *coords)
                    if first_point is None:
                        first_point = pt
                    moved = True
                    current_point = pt
                elif c.tag == DML('quadBezTo'):
                    coords = []
                    bz_coords = [BezierPoint(*T.transform_point(current_point))]
                    for p in c.getchildren():
                        pt = pptx_geometry.point(p)
                        coords.extend(T.transform_point(pt))
                        bz_coords.append(BezierPoint(*T.transform_point(pt)))
                        current_point = pt
                    svg_path.push('Q', *coords)
                    bz = QuadraticBezier(*bz_coords)
                    coordinates.extend(bezier_sample(bz))
                else:
                    print('Unknown path element: {}'.format(c.tag))

        bbox = (shape.width, shape.height)
        T = transform@DrawMLTransform(shape, bbox).matrix()
        shape_size = T.scale_length(bbox)

        exclude_shape = False
        exclude_text = True
        svg_text = None
        label = None
        colour, alpha = self.get_colour(shape, group_colour)
        if not isinstance(shape, pptx.shapes.connector.Connector):
            svg_path.attribs.update(self.__get_fill(shape, group_colour))
            label = text_content(shape)
            if self.__shape_filter is not None and len(coordinates) > 2 and closed:
                # Apply filter to closed shapes
                ## this doesn't work for shapes drawn using arcTo or *BezTo commands
                ## OK for FC since (most) shapes are rectangular (but not circular nodes...)
                geometry = shapely.geometry.Polygon(coordinates).buffer(0)
                properties = {
                    'colour': colour,
                    'alpha': alpha
                }
                if label is not None:
                    properties['label'] = label
                closed_shape = Shape(SHAPE_TYPE.FEATURE, shape.shape_id, geometry, properties)
                if self.__kind == 'base':
                    self.__shape_filter.add_shape(closed_shape)
                elif self.__kind == 'layer':
                    self.__shape_filter.filter(closed_shape)
                exclude_shape = properties.get('exclude', False)
                exclude_text = properties.get('exclude-text', False)
            else:
                exclude_text = False

            exclude_text = True ####################### TEMP
            if (not exclude_text and not exclude_shape   ## <<<<<<<<<<<<<<<<<<<<< No text at all...
            and self.__kind == 'base' and label is not None):
                svg_text = self.__draw_shape_label(shape, label, shape_size, T)

        elif True:  #####  WIP self.__shape_filter is not None:   ## No filter for pptx2celldel ??
            # Exclude connectors when filtering shapes
            exclude_shape = True

            if 'type' in shape.line.headEnd or 'type' in shape.line.tailEnd:
                svg_path.set_markers((marker_id(shape.line.headEnd, 'head'),
                                      None, marker_id(shape.line.tailEnd, 'tail')
                                    ))

        if not exclude_shape:
            svg_path.attribs.update(self.__get_stroke(shape))

            # Use shapely to get geometry
            if closed:
                geometry = shapely.geometry.Polygon(coordinates).buffer(0)
            else:
                geometry = shapely.geometry.LineString(coordinates)
                if shape.name.strip().startswith('.') and 'closed' in shape.name:
                    coordinates.append(coordinates[0])
                    geometry = shapely.geometry.Polygon(coordinates).buffer(0)
            shape_kind = pptx_geometry.shape_kind

            if (shape_kind is not None
             and not shape_kind.startswith('star')
             and shape_size[0]*shape_size[1] < 200):
                add_class(svg_path, 'connector')    ## FC
                                                    ## cardio (circle) versus neural (rect)
                                                    ## nerve features...

            if (hyperlink := self.__get_link(shape)) is not None:
                if label is None:
                    label = hyperlink
                link_element = self.__dwg.a(href=hyperlink)
                link_element.add(svg_path)
                if svg_text is not None:
                    link_element.add(svg_text)
                svg_parent.add(link_element)
            else:
                svg_parent.add(svg_path)
                if svg_text is not None:
                    svg_parent.add(svg_text)
            if label is not None:
                add_markup(svg_path, label)  # Set's <title>
                if svg_text is not None:
                    add_markup(svg_text, label)
            else:
                add_markup(svg_path, shape.name)

    def __draw_shape_label(self, shape: PptxShape, label: str, shape_size: tuple[float, float], transform: Transform) -> SvgElement:
    #===============================================================================================================================
        # Draw text if base map

        style = {}
        font = shape.text_frame.paragraphs[0].runs[0].font
        font_size = round(font.size/EMU_PER_PIXEL)
        if font.name is not None:   ## Else need to get from theme
            style['font-family'] = font.name
        style['font-size'] = f'{font_size}px'
        style['font-weight'] = 700 if font.bold else 400
        if font.italic:
            style['font-size'] = 'italic'
        if font.color.type is not None:
            style['fill'] = self.__colour_map.lookup(font.color)
            if font.color.alpha != 1.0:
                style['fill-opacity'] = font.color.alpha

        svg_text = self.__dwg.text(label)   ## text_run.text
        svg_text.attribs['style'] = ' '.join([f'{name}: {value};' for name, value in style.items()])

        shape_pos = transform.transform_point((0, 0))
        svg_text.attribs['x'] = shape_pos[0]
        svg_text.attribs['y'] = shape_pos[1]
        (halign, valign) = text_alignment(shape)

        if halign == 'right':
            svg_text.attribs['text-anchor'] = 'end'
            svg_text.attribs['x'] += shape_size[0] - TEXT_MARGINS[0]
        elif halign == 'centre':
            svg_text.attribs['text-anchor'] = 'middle'
            svg_text.attribs['x'] += shape_size[0]/2
        else:   # Default to 'left'
            svg_text.attribs['text-anchor'] = 'start'
            svg_text.attribs['x'] += TEXT_MARGINS[0]
        if valign == 'bottom':
            svg_text.attribs['dominant-baseline'] = 'auto'
            svg_text.attribs['y'] += shape_size[1]
        elif valign == 'middle':
            svg_text.attribs['dominant-baseline'] = 'middle'
            svg_text.attribs['y'] += shape_size[1]/2
        else:   # Default to 'top'
            svg_text.attribs['dominant-baseline'] = 'auto'
            svg_text.attribs['y'] += font_size + TEXT_MARGINS[1]
        return svg_text

    def __get_fill(self, shape: PptxShape, group_colour: str) -> dict[str, Any]:
    #===========================================================================
        fill_attribs = {}
        colour, alpha = self.get_colour(shape, group_colour)
        if (shape.fill.type == MSO_FILL_TYPE.SOLID
         or shape.fill.type == MSO_FILL_TYPE.GROUP):
            fill_attribs['fill'] = colour
            if alpha < 1.0:
                fill_attribs['opacity'] = alpha
        elif shape.fill.type == MSO_FILL_TYPE.GRADIENT:
            self.__gradient_id += 1
            gradient = Gradient(self.__dwg, self.__gradient_id, shape, self.__colour_map)
            fill_attribs['fill'] = gradient.url
        elif shape.fill.type is None:
            fill_attribs['fill'] = '#FF0000'
            fill_attribs['opacity'] = 1.0
        elif shape.fill.type != MSO_FILL_TYPE.BACKGROUND:
            print('Unsupported fill type: {}'.format(shape.fill.type))
        return fill_attribs

    @staticmethod
    def __get_link(shape: PptxShape) -> str:
    #=======================================
        shape_xml = etree.fromstring(shape.element.xml)
        for link_ref in shape_xml.findall('.//a:hlinkClick', namespaces=PPTX_NAMESPACE):
            r_id = link_ref.attrib[pptx_resolve('r:id')]
            if (r_id in shape.part.rels
             and shape.part.rels[r_id].reltype == 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink'):
                return shape.part.rels[r_id].target_ref

    def __get_stroke(self, shape: PptxShape) -> dict[str, Any]:
    #==========================================================
        stroke_attribs = {}
        stroke_width = points_to_pixels(max(Length(shape.line.width).pt, MIN_STROKE_WIDTH))
        stroke_attribs['stroke-width'] = stroke_width
        shape_xml = etree.fromstring(shape.element.xml)

        line_dash = None
        if (line_props := shape_xml.find('.//p:spPr/a:ln', namespaces=PPTX_NAMESPACE)) is not None:
            for prop in line_props.getchildren():
                if prop.tag == DML('prstDash'):
                    line_dash = prop.attrib.get('val', 'solid')
                    break
        try:
            dash_style = shape.line.dash_style
        except KeyError:
            dash_style = None
        if line_dash is not None or dash_style is not None:
            if dash_style == MSO_LINE_DASH_STYLE.DASH:
                stroke_attribs['stroke-dasharray'] = 4*stroke_width
            elif line_dash == 'sysDot':
                stroke_attribs['stroke-dasharray'] = '{} {} {} {}'.format(4*stroke_width, stroke_width, stroke_width, stroke_width)
            elif line_dash == MSO_LINE_DASH_STYLE.LONG_DASH:
                stroke_attribs['stroke-dasharray'] = '{} {}'.format(4*stroke_width, stroke_width)
            elif dash_style == MSO_LINE_DASH_STYLE.SQUARE_DOT:
                stroke_attribs['stroke-dasharray'] = '{} {}'.format(2*stroke_width, stroke_width)
            elif dash_style == MSO_LINE_DASH_STYLE.ROUND_DOT:
                stroke_attribs['stroke-dasharray'] = '{} {}'.format(stroke_width, stroke_width)
            elif line_dash != 'solid':
                print(f'Unsupported line dash style: {dash_style}/{line_dash}')

        if shape.line.fill.type == MSO_FILL_TYPE.SOLID:
            stroke_attribs['stroke'] = self.__colour_map.lookup(shape.line.color)
            alpha = shape.line.fill.fore_color.alpha
            if alpha < 1.0:
                stroke_attribs['stroke-opacity'] = alpha
        elif (line_style := shape_xml.find('.//p:style/a:lnRef', namespaces=PPTX_NAMESPACE)) is not None:
            for prop in line_style.getchildren():
                if prop.tag == DML('schemeClr'):
                    scheme_colour = prop.attrib.get('val')
                    stroke_attribs['stroke'] = self.__colour_map.scheme_colour(scheme_colour)
        elif shape.line.fill.type is None:
            stroke_attribs['stroke'] = 'none'
        elif shape.line.fill.type != MSO_FILL_TYPE.BACKGROUND:
            print('Unsupported line fill type: {}'.format(shape.line.fill.type))

        return stroke_attribs

#===============================================================================

class Pptx2Svg(object):
    def __init__(self, powerpoint_href, kind='base', shape_filter=None, quiet=True):
        self.__source_name = Path(powerpoint_href).stem
        ppt_bytes = FilePath(powerpoint_href).get_BytesIO()
        self.__pptx = Presentation(ppt_bytes)
        self.__theme = Theme(ppt_bytes)
        self.__slides = self.__pptx.slides
        (pptx_width, pptx_height) = (self.__pptx.slide_width, self.__pptx.slide_height)
        self.__transform = Transform([[1.0/EMU_PER_PIXEL,                 0, 0],
                                      [                0, 1.0/EMU_PER_PIXEL, 0],
                                      [                0,                 0, 1]])
        self.__svg_size = self.__transform.transform_point((pptx_width, pptx_height))
        self.__kind = kind
        self.__shape_filter = shape_filter
        self.__quiet = quiet
        self.__svg_layers = []
        self.__saved_svg = OrderedDict()
        self.__id = Path(powerpoint_href).name.split('.')[0].replace(' ', '_')
        self.__models = None

    @property
    def id(self):
        return self.__id

    @property
    def svg_layers(self):
        return self.__svg_layers

    def slide_to_svg(self, slide, slide_number):
    #===========================================
        layer = SvgLayer(self.__svg_size, slide, slide_number, self.__theme,
                         kind=self.__kind, shape_filter=self.__shape_filter,
                         quiet=self.__quiet)
        layer.process(self.__transform)
        self.__svg_layers.append(layer)
        if slide_number == 1:
            if layer.id is not None and not layer.id.startswith('slide-'):
                self.__id = layer.id
            self.__models = layer.models

    def slides_to_svg(self):
    #=======================
        for n, slide in enumerate(self.__slides):
            self.slide_to_svg(slide, n+1)

    def save_layers(self, output_dir):
    #=================================
        self.__saved_svg = OrderedDict()
        layer_ids = len(self.__svg_layers) > 1
        for layer in self.__svg_layers:
            if layer_ids:
                filename = f'{self.__source_name}-{layer.id}.svg'
            else:
                filename = f'{self.__source_name}.svg'
            svg_file = os.path.join(output_dir, filename)
            with open(svg_file, 'w', encoding='utf-8') as fp:
                layer.save(fp)
            self.__saved_svg[layer.id] = svg_file
        return self.__saved_svg

    def update_manifest(self, manifest):
    #===================================
        if 'id' not in manifest and self.__id is not None:
            manifest['id'] = self.__id
        if 'models' not in manifest and self.__models is not None:
            manifest['models'] = self.__models
        sources = [ source for source in manifest['sources']
                        if source['kind'] != 'slides']
        next_kind = 'base'
        for id, filename in self.__saved_svg.items():
            sources.append(OrderedDict(
                id=id,
                href=filename,
                kind=next_kind
            ))
            if next_kind == 'base':
                next_kind = 'details'
        manifest['sources'] = sources

#===============================================================================
