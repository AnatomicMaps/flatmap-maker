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

import os

#===============================================================================

from mapmaker.flatmap.layers import MapLayer
from mapmaker.settings import settings
from mapmaker.utils import log, FilePath, TreeList

from .. import MapSource, RasterSource

from .powerpoint import Powerpoint, SHAPE_TYPE

#===============================================================================

class PowerpointSlide(MapLayer):
    def __init__(self, source, slide, slide_number):
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

    def _extract_shapes(self):              # Override in sub-class
    #=========================
        return self.__slide.process()

    def process(self):
    #=================
        shapes = self._extract_shapes()
        features = self.__process_shape_list(shapes)
        self.add_features('Slide', features, outermost=True)

    def __process_shape_list(self, shapes):
    #======================================
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
                else:
                    feature = self.flatmap.new_feature(shape.geometry, shape.properties)
                    features.append(feature)
        return features

#===============================================================================

class PowerpointSource(MapSource):
    def __init__(self, flatmap, id, source_href, source_kind='slides', source_range=None, SlideClass=PowerpointSlide):
        super().__init__(flatmap, id, source_href, source_kind, source_range=source_range)
        self.__SlideClass = SlideClass
        self.__powerpoint = Powerpoint(source_href)
        self.bounds = self.__powerpoint.bounds   # Set bounds of MapSource
        self.__slides = self.__powerpoint.slides
        pdf_source = FilePath('{}_cleaned.pdf'.format(os.path.splitext(source_href)[0]))
        self.set_raster_source(RasterSource('pdf', None, file_path=pdf_source))

    @property
    def transform(self):
        return self.__powerpoint.transform

    def process(self):
    #=================
        if self.source_range is None:
            slide_numbers = range(1, len(self.__slides)+1)
        else:
            slide_numbers = self.source_range
        for slide_number in slide_numbers:
            # Skip slides not in the presentation
            if slide_number < 1 or slide_number >= (len(self.__slides) + 1):
                continue
            slide = self.__slides[slide_number - 1]
            slide_layer = self.__SlideClass(self, slide, slide_number)
            log('Slide {}, {}'.format(slide_number, slide_layer.id))
            if settings.get('saveDrawML'):
                xml = open(os.path.join(settings.get('output'),
                                        self.flatmap.id,
                                        '{}.xml'.format(slide_layer.id)), 'w')
                xml.write(slide.element.xml)
                xml.close()
            slide_layer.process()
            self.add_layer(slide_layer)

#===============================================================================
