#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019 - 2022  David Brooks
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
from io import BytesIO, StringIO

#===============================================================================

from mapmaker.flatmap.feature import Feature
from mapmaker.flatmap.layers import MapLayer
from mapmaker.settings import settings
from mapmaker.utils import log, TreeList

from .. import MapSource, RasterSource

from .powerpoint import Powerpoint, Slide
from .pptx2svg import Pptx2Svg

# Exports
from .powerpoint import Slide, SHAPE_TYPE

#===============================================================================

class PowerpointLayer(MapLayer):
    def __init__(self, source: PowerpointSource, slide: Slide, slide_number: int):
        if slide.id is not None:
            id = slide.id
        else:
            id = f'{source.id}_slide-{slide_number:02d}'
        if source.source_range is None:
            exported = slide_number == 1
        else:
            exported = slide_number == source.source_range[0]
        super().__init__(id, source, exported=exported)
        self.__slide = slide
        self.__slide_number = slide_number

    @property
    def slide(self):
        return self.__slide

    @property
    def slide_number(self):
        return self.__slide_number

    def _extract_shapes(self) -> TreeList:              # Override in sub-class
    #=====================================
        return self.__slide.process()

    def process(self):
    #=================
        shapes = self._extract_shapes()
        features = self.__process_shape_list(shapes)
        self.add_features('Slide', features, outermost=True)

    def __process_shape_list(self, shapes: TreeList) -> list[Feature]:
    #=================================================================
        features = []
        for shape in shapes:
            if isinstance(shape, TreeList):
                group_features = self.__process_shape_list(shape)
                grouped_feature = self.add_features('Group', group_features)
                if grouped_feature is not None:
                    features.append(grouped_feature)
            else:
##                print('>>>>>>>>>>>>>>>', shape.type, shape.label)
                properties = shape.properties
                self.source.check_markup_errors(properties)
                if 'tile-layer' not in properties:
                    properties['tile-layer'] = 'features'   # Passed through to map viewer
                if 'error' in properties:
                    pass
                elif 'invisible' in properties:
                    pass
                elif 'path' in properties:
                    pass
                elif properties.get('exclude', False):
                    pass
                else:
                    feature = self.flatmap.new_feature(shape.geometry, properties)
                    features.append(feature)
        return features

#===============================================================================

class PowerpointSource(MapSource):
    def __init__(self, flatmap, id, source_href, source_kind='slides', source_range=None,
                 SlideLayerClass=PowerpointLayer, shape_filters=None):
        super().__init__(flatmap, id, source_href, source_kind, source_range=source_range)
        self.__SlideLayerClass = SlideLayerClass
        self.__powerpoint = Powerpoint(source_href)
        self.bounds = self.__powerpoint.bounds   # Set bounds of MapSource
        self.__slides: list[Slide] = self.__powerpoint.slides
        if shape_filters is not None:
            self.__map_shape_filter = shape_filters.map_filter
            self.__svg_shape_filter = shape_filters.svg_filter
        else:
            self.__map_shape_filter = None
            self.__svg_shape_filter = None

    @property
    def transform(self):
        return self.__powerpoint.transform

    def filter_map_shape(self, shape):
    #=================================
        # Called as each shape is extracted from a slide
        if self.__map_shape_filter is not None:
            if self.kind == 'base':
                self.__map_shape_filter.add_shape(shape)
            elif self.kind == 'layer':
                self.__map_shape_filter.filter(shape)

    def process(self):
    #=================
        if self.__map_shape_filter is not None and self.kind == 'base':
            self.__map_shape_filter.create_filter()
        if self.source_range is None:
            slide_numbers = range(1, len(self.__slides)+1)
        else:
            slide_numbers = self.source_range
        for slide_number in slide_numbers:
            # Skip slides not in the presentation
            if slide_number < 1 or slide_number >= (len(self.__slides) + 1):
                continue
            slide = self.__slides[slide_number - 1]
            slide_layer = self.__SlideLayerClass(self, slide, slide_number)
            log('Slide {}, {}'.format(slide_number, slide_layer.id))
            if settings.get('saveDrawML'):
                with open(self.flatmap.full_filename(f'{slide_layer.id}.xml'), 'w') as xml:
                    xml.write(slide.pptx_slide.element.xml)
            slide_layer.process()
            self.add_layer(slide_layer)

    def get_raster_source(self):
    #===========================
        return RasterSource('svg', self.__get_raster_data)

    def __get_raster_data(self):
    #===========================
        svg_extractor = Pptx2Svg(self.source_href,
            kind=self.kind, shape_filter=self.__svg_shape_filter)

        # slides to SVG is simply slide_to_svg for all slides in the PPT, using the GLOBAL svg shape filter
        # Do we need a local, secondary filter??
        # PowerpointSource.__slides is the list of PPTX Slide objects
        # Use slide number to access local FCSlideLayer (which has a svg_filter(shape) method??)

        svg_extractor.slides_to_svg()

        ## Have option to keep intermediate SVG??
        svg = StringIO()
        for layer in svg_extractor.svg_layers:    ### this just gets the first slide...
            layer.save(svg)
            break
        svg_bytes = BytesIO(svg.getvalue().encode('utf-8'))
        svg.close()
        svg_bytes.seek(0)
        return svg_bytes

#===============================================================================
