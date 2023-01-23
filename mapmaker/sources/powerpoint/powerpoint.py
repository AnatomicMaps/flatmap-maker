#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2018 - 2023  David Brooks
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

from typing import Optional

#===============================================================================

from lxml import etree
import numpy as np

from pptx import Presentation
from pptx.dml.fill import FillFormat
from pptx.enum.dml import MSO_FILL_TYPE             # type: ignore
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN     # type: ignore
from pptx.shapes.autoshape import Shape as PptxShape
from pptx.shapes.connector import Connector as PptxConnector
from pptx.shapes.group import GroupShape as PptxGroupShape
from pptx.shapes.shapetree import GroupShapes as PptxGroupShapes
from pptx.shapes.shapetree import SlideShapes as PptxSlideShapes
from pptx.slide import Slide as PptxSlide

#===============================================================================

from mapmaker.geometry import Transform
from mapmaker.properties.markup import parse_layer_directive, parse_markup
from mapmaker.sources import WORLD_METRES_PER_EMU
from mapmaker.sources.shape import Shape, SHAPE_TYPE
from mapmaker.utils import FilePath, log, ProgressBar, TreeList

from .colour import ColourMap, Theme
from .geometry import get_shape_geometry
from .presets import DML
from .transform import DrawMLTransform

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


# (colour, opacity)
ColourPair = tuple[Optional[str], float]

#===============================================================================

class Slide():
    def __init__(self, index: int, pptx_slide: PptxSlide, theme: Theme, transform: Transform):
        self.__id = None
        # Get any layer directives
        if pptx_slide.has_notes_slide:
            notes_slide = pptx_slide.notes_slide
            notes_text = notes_slide.notes_text_frame.text
            if notes_text.startswith('.'):
                layer_directive = parse_layer_directive(notes_text)
                if 'error' in layer_directive:
                    log.error('error', 'Slide {}: invalid layer directive: {}'
                                 .format(index+1, notes_text))
                if 'id' in layer_directive:
                    self.__id = layer_directive['id']
        self.__colour_map = ColourMap(theme, pptx_slide)
        self.__pptx_slide = pptx_slide
        self.__transform = transform
        self.__shapes_by_id: dict[int, Shape] = {}

    @property
    def id(self) -> Optional[str]:
        return self.__id

    @property
    def pptx_slide(self) -> PptxSlide:
        return self.__pptx_slide

    @property
    def slide_id(self) -> int:
        return self.__pptx_slide.slide_id

    def shape(self, id: int) -> Optional[PowerpointShape]:
    #=====================================================
        return self.__shapes_by_id.get(id)

    def process(self) -> TreeList:
    #=============================
        # Return the slide's group structure as a nested list of Shapes
        return self.__process_pptx_shapes(self.__pptx_slide.shapes,      # type: ignore
                                          self.__transform, show_progress=True)


    def __get_colour(self, shape: PptxConnector | PptxGroupShape | PptxShape,
                     group_colour: Optional[ColourPair]=None) -> ColourPair:
    #=======================================================================
        def colour_from_fill(shape, fill) -> ColourPair:
            if fill.type == MSO_FILL_TYPE.SOLID:                    # type: ignore
                return (self.__colour_map.lookup(fill.fore_color),
                        fill.fore_color.alpha)
            elif fill.type == MSO_FILL_TYPE.GRADIENT:               # type: ignore
                log.warning(f'{shape.name}: gradient fill ignored')
            elif fill.type == MSO_FILL_TYPE.GROUP:                  # type: ignore
                if group_colour is not None:
                    return group_colour
            elif fill.type is not None and fill.type != MSO_FILL_TYPE.BACKGROUND:   # type: ignore
                log.warning(f'{shape.name}: unsupported fill type: {fill.type}')
            return (None, 1.0)

        colour = None
        alpha = 1.0
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:                # type: ignore
            colour, alpha = colour_from_fill(shape, FillFormat.from_fill_parent(shape.element.grpSpPr))
        elif shape.shape_type != MSO_SHAPE_TYPE.LINE:               # type: ignore
            colour, alpha = colour_from_fill(shape, shape.fill)     # type: ignore
        elif shape.line.fill.type == MSO_FILL_TYPE.SOLID:           # type: ignore
            colour = self.__colour_map.lookup(shape.line.color)     # type: ignore
            alpha = shape.line.fill.fore_color.alpha                # type: ignore
        elif shape.line.fill.type is None:                          # type: ignore
            # Check for a fill colour in the <style> block
            xml = etree.fromstring(shape.element.xml)
            if (scheme_colour := xml.find('.//p:style/a:fillRef/a:schemeClr',
                                            namespaces=PPTX_NAMESPACE)) is not None:
                colour = self.__colour_map.scheme_colour(scheme_colour.attrib['val'])
        elif shape.line.fill.type != MSO_FILL_TYPE.BACKGROUND:      # type: ignore
            log.warning(f'{shape.name}: unsupported line fill type: {shape.line.fill.type}')    # type: ignore
        return (colour, alpha)

    def __process_group(self, group: PptxGroupShape, transform: Transform) -> TreeList:
    #==================================================================================
        return self.__process_pptx_shapes(group.shapes, transform@DrawMLTransform(group),       # type: ignore
                                          group_colour=self.__get_colour(group))

###        if len(shapes) < 2:  ## shapes[0] might be a TreeList ##
###                             ## or shapes[0].type != SHAPE_TYPE.FEATURE:
###            return shapes
###
###        colour = shapes[0].properties['colour']
###        label = shapes[0].label
###        alignment = shapes[0].properties.get('align')
###        geometry = [shapes[0].geometry]
###        for shape in shapes[1:]:
###            if shape.type != SHAPE_TYPE.FEATURE or colour != shape.properties['colour']:
###                return shapes
###            if label == '':
###                label = shape.label
###                alignment = shape.properties.get('align')
###            elif shape.label != '':
###                return shapes
###            geometry.append(shape.geometry)
###        if label == '':
###            return shapes
###
###        # Merge a group of shapes that are all the same colour and with only
###        # one having a label into a single shape
###        return Shape(SHAPE_TYPE.FEATURE, group.shape_id,
###                      shapely.ops.unary_union(geometry), {
###                        'colour': colour,
###                        'label': label,
###                        'shape-name': group.name,
###                        'text-align': alignment
###                       })

    def __process_pptx_shapes(self, pptx_shapes: PptxGroupShapes | PptxSlideShapes,
                              transform: Transform, group_colour: Optional[ColourPair]=None,
                              show_progress=False) -> TreeList:
    #========================================================================================
        def text_alignment(shape) -> tuple[str, str]:
            para = shape.text_frame.paragraphs[0].alignment
            vertical = shape.text_frame.vertical_anchor
            return ('left' if para in [PP_ALIGN.LEFT, PP_ALIGN.DISTRIBUTE, PP_ALIGN.JUSTIFY, PP_ALIGN.JUSTIFY_LOW] else
                    'right' if para == PP_ALIGN.RIGHT else
                    'centre',
                    'top' if vertical == MSO_ANCHOR.TOP else
                    'bottom' if vertical == MSO_ANCHOR.BOTTOM else
                    'middle')
        def text_content(shape) -> str:
            text = shape.text.replace('\n', ' ').replace('\xA0', ' ').replace('\v', ' ').strip() # Newline, non-breaking space, vertical-tab
            return text if text not in ['', '.'] else ''

        progress_bar = ProgressBar(show=show_progress,
            total=len(pptx_shapes),
            unit='shp', ncols=40,
            bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}')
        shapes = TreeList()
        for pptx_shape in pptx_shapes:
            shape_name = pptx_shape.name
            shape_properties = parse_markup(shape_name) if shape_name.startswith('.') else {}
            if (pptx_shape.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE              # type: ignore
             or pptx_shape.shape_type == MSO_SHAPE_TYPE.FREEFORM                # type: ignore
             or pptx_shape.shape_type == MSO_SHAPE_TYPE.TEXT_BOX                # type: ignore
             or pptx_shape.shape_type == MSO_SHAPE_TYPE.LINE):                  # type: ignore
                colour, alpha = self.__get_colour(pptx_shape, group_colour)     # type: ignore
                shape_properties.update({
                    'shape-name': shape_name,
                    'colour': colour
                })
                if alpha < 1.0:
                    shape_properties['opacity'] = round(100*alpha, 1)
                geometry = get_shape_geometry(pptx_shape, transform, shape_properties)
                if geometry is not None and geometry.is_valid:
                    shape_xml = etree.fromstring(pptx_shape.element.xml)
                    for link_ref in shape_xml.findall('.//a:hlinkClick',
                                                    namespaces=PPTX_NAMESPACE):
                        r_id = link_ref.attrib[pptx_resolve('r:id')]
                        if (r_id in pptx_shape.part.rels
                         and pptx_shape.part.rels[r_id].reltype == 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink'):
                            shape_properties['hyperlink'] = pptx_shape.part.rels[r_id].target_ref
                            break
                    if pptx_shape.shape_type == MSO_SHAPE_TYPE.LINE:            # type: ignore
                        ## cf. pptx2svg for stroke colour
                        shape_type = SHAPE_TYPE.CONNECTOR
                        if (connection := shape_xml.find('.//p:nvCxnSpPr/p:cNvCxnSpPr',
                                                        namespaces=PPTX_NAMESPACE)) is not None:
                            for c in connection.getchildren():
                                if c.tag == DML('stCxn'):
                                    shape_properties['connection-start'] = int(c.attrib['id'])
                                elif c.tag == DML('endCxn'):
                                    shape_properties['connection-end'] = int(c.attrib['id'])
                        line_style = 'solid'
                        head_end = 'none'
                        tail_end = 'none'
                        if (line_props := shape_xml.find('.//p:spPr/a:ln',
                                                        namespaces=PPTX_NAMESPACE)) is not None:
                            for prop in line_props.getchildren():
                                if prop.tag == DML('prstDash'):
                                    line_style = prop.attrib.get('val', 'solid')
                                elif prop.tag == DML('headEnd'):
                                    head_end = prop.attrib.get('type', 'none')
                                elif prop.tag == DML('tailEnd'):
                                    tail_end = prop.attrib.get('type', 'none')
                        shape_properties['line-style'] = line_style
                        shape_properties['head-end'] = head_end
                        shape_properties['tail-end'] = tail_end
                        shape_properties['stroke-width'] = abs(transform.scale_length((int(pptx_shape.line.width.emu), 0))[0])  # type: ignore
                    else:
                        shape_type = SHAPE_TYPE.FEATURE
                        label = text_content(pptx_shape)
                        if label != '':
                            shape_properties['label'] = label
                            shape_properties['align'] = text_alignment(pptx_shape)
                    shape_properties['pptx-shape'] = pptx_shape
                    shape = PowerpointShape(shape_type, pptx_shape.shape_id, geometry, shape_properties)
                    self.__shapes_by_id[shape.id] = shape
                    shapes.append(shape)
                elif geometry is None:
                    log.warning(f'Shape "{shape_name}" {pptx_shape.shape_type}/{shape_properties.get("shape-kind")} not processed -- cannot get geometry')
                else:
                    log.warning(f'Shape "{shape_name}" {pptx_shape.shape_type}/{shape_properties.get("shape-kind")} not processed -- cannot get valid geometry')
            elif pptx_shape.shape_type == MSO_SHAPE_TYPE.GROUP:             # type: ignore
                shapes.append(self.__process_group(pptx_shape, transform))  # type: ignore
            elif pptx_shape.shape_type == MSO_SHAPE_TYPE.PICTURE:           # type: ignore
                log.warning('Image "{}" {} not processed...'.format(shape_name, str(pptx_shape.shape_type)))
            else:
                log.warning('Shape "{}" {} not processed...'.format(shape_name, str(pptx_shape.shape_type)))
            progress_bar.update(1)

        progress_bar.close()
        return shapes

#===============================================================================

class Powerpoint():
    def __init__(self, source_href: str):
        ppt_bytes = FilePath(source_href).get_BytesIO()
        pptx = Presentation(ppt_bytes)

        (width, height) = (pptx.slide_width, pptx.slide_height)
        self.__transform = Transform([[WORLD_METRES_PER_EMU,                     0, 0],
                                      [                    0, -WORLD_METRES_PER_EMU, 0],
                                      [                    0,                     0, 1]])@np.array([[1.0, 0.0,  -width/2.0],
                                                                                                    [0.0, 1.0, -height/2.0],
                                                                                                    [0.0, 0.0,         1.0]])
        top_left = self.__transform.transform_point((0, 0))
        bottom_right = self.__transform.transform_point((width, height))
        # southwest and northeast corners
        self.__bounds = (top_left[0], bottom_right[1], bottom_right[0], top_left[1])

        theme = Theme(ppt_bytes)
        self.__slides: list[Slide] = [Slide(n, slide, theme, self.__transform) for n, slide in enumerate(pptx.slides)]

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return self.__bounds

    @property
    def slides(self) -> list[Slide]:
        return self.__slides

    @property
    def transform(self) -> Transform:
        return self.__transform

#===============================================================================
