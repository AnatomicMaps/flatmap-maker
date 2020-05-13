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

from math import pi as PI
import os

#===============================================================================

import svgwrite

#===============================================================================

from .extractor import Extractor, Layer, Transform
from .extractor import EMU_PER_DOT, ellipse_point
from .formula import Geometry, radians
from .presets import DML

#===============================================================================

def svg_coords(x, y):
#====================
    return (x/EMU_PER_DOT, y/EMU_PER_DOT)

def svg_units(emu):
#===================
    return emu/EMU_PER_DOT

def svg_transform(m):
#====================
    return (          m[0, 0],            m[1, 0],
                      m[0, 1],            m[1, 1],
            svg_units(m[0, 2]), svg_units(m[1, 2]))

#===============================================================================

class SvgLayer(Layer):
    def __init__(self, extractor, slide, slide_number):
        super().__init__(extractor, slide, slide_number)
        self.__dwg = svgwrite.Drawing(filename=None,
                                     size=svg_coords(extractor.slide_size[0], extractor.slide_size[1]))
        self.__dwg.defs.add(self.__dwg.style('.non-scaling-stroke { vector-effect: non-scaling-stroke; }'))

    def process(self):
        self.process_shape_list(self.__slide.shapes, self.__dwg)

    def save(self, filename=None):
        if filename is None:
            filename = os.path.join(self.settings.output_dir, '{}.svg'.format(self.layer_id))
        self.__dwg.saveas(filename)

    def process_group(self, group, properties, svg_parent):
        svg_group = self.__dwg.g(id=group.shape_id)
        svg_group.matrix(*svg_transform(Transform(group).matrix()))
        svg_parent.add(svg_group)
        self.process_shape_list(group.shapes, svg_group)

    def process_shape(self, shape, properties, svg_parent):
        geometry = Geometry(shape)
        for path in geometry.path_list:
            bbox = (shape.width, shape.height) if path.w is None else (path.w, path.h)
            svg_path = self.__dwg.path(id=shape.shape_id, fill='none', stroke_width=3,
                                      class_='non-scaling-stroke')
            svg_path.matrix(*svg_transform(Transform(shape, bbox).matrix()))
            first_point = None
            current_point = None
            closed = False
            for c in path.getchildren():
                if   c.tag == DML('arcTo'):
                    wR = geometry.attrib_value(c, 'wR')
                    hR = geometry.attrib_value(c, 'hR')
                    stAng = radians(geometry.attrib_value(c, 'stAng'))
                    swAng = radians(geometry.attrib_value(c, 'swAng'))
                    p1 = ellipse_point(wR, hR, stAng)
                    p2 = ellipse_point(wR, hR, stAng + swAng)
                    pt = (current_point[0] - p1[0] + p2[0],
                          current_point[1] - p1[1] + p2[1])
                    large_arc_flag = 1 if swAng >= PI else 0
                    svg_path.push('A', svg_units(wR), svg_units(hR),
                                       0, large_arc_flag, 1,
                                       svg_units(pt[0]), svg_units(pt[1]))
                    current_point = pt

                elif c.tag == DML('close'):
                    if first_point is not None and current_point != first_point:
                        svg_path.push('Z')
                    closed = True
                    first_point = None
                elif c.tag == DML('cubicBezTo'):
                    coords = []
                    for p in c.getchildren():
                        pt = geometry.point(p)
                        coords.append(svg_units(pt[0]))
                        coords.append(svg_units(pt[1]))
                        current_point = pt
                    svg_path.push('C', *coords)
                elif c.tag == DML('lnTo'):
                    pt = geometry.point(c.pt)
                    svg_path.push('L', svg_units(pt[0]), svg_units(pt[1]))
                    current_point = pt
                elif c.tag == DML('moveTo'):
                    pt = geometry.point(c.pt)
                    svg_path.push('M', svg_units(pt[0]), svg_units(pt[1]))
                    if first_point is None:
                        first_point = pt
                    current_point = pt
                elif c.tag == DML('quadBezTo'):
                    coords = []
                    for p in c.getchildren():
                        pt = geometry.point(p)
                        coords.append(svg_units(pt[0]))
                        coords.append(svg_units(pt[1]))
                        current_point = pt
                    svg_path.push('Q', *coords)
                else:
                    print('Unknown path element: {}'.format(c.tag))
            if closed:
                svg_path.attribs['fill'] = '#808080'
                svg_path.attribs['opacity'] = 0.3
                svg_path.attribs['stroke'] = 'red'
            else:
                svg_path.attribs['stroke'] = 'blue'

            svg_parent.add(svg_path)

#===============================================================================

class SvgExtractor(Extractor):
    def __init__(self, pptx, settings):
        super().__init__(pptx, settings, SvgLayer)

    def bounds(self):
        return [svg_units(b) for b in super().bounds()]

#===============================================================================
