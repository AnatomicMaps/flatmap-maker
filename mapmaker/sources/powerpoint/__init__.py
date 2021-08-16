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

import os

#===============================================================================

import numpy as np

from pptx import Presentation

#===============================================================================

from .. import MapSource, RasterSource
from .. import WORLD_METRES_PER_EMU

from mapmaker.geometry import Transform
from mapmaker.settings import settings
from mapmaker.utils import log, FilePath

from .slide import PowerpointSlide

#===============================================================================

class PowerpointSource(MapSource):
    def __init__(self, flatmap, id, source_href):
        super().__init__(flatmap, id, source_href, 'slides')
        self.__pptx = Presentation(FilePath(source_href).get_BytesIO())
        self.__slides = self.__pptx.slides

        (width, height) = (self.__pptx.slide_width, self.__pptx.slide_height)
        self.__transform = Transform([[WORLD_METRES_PER_EMU,                     0, 0],
                                      [                    0, -WORLD_METRES_PER_EMU, 0],
                                      [                    0,                     0, 1]])@np.array([[1, 0, -width/2.0],
                                                                                                    [0, 1, -height/2.0],
                                                                                                    [0, 0,         1.0]])
        top_left = self.__transform.transform_point((0, 0))
        bottom_right = self.__transform.transform_point((width, height))
        # southwest and northeast corners
        self.bounds = (top_left[0], bottom_right[1], bottom_right[0], top_left[1])
        pdf_source = FilePath('{}_cleaned.pdf'.format(os.path.splitext(source_href)[0]))
        self.set_raster_source(RasterSource('pdf', pdf_source.get_data()))

    @property
    def transform(self):
        return self.__transform

    def process(self):
    #=================
        for n in range(len(self.__slides)):
            slide = self.__slides[n]
            slide_number = n + 1
            slide_layer = PowerpointSlide(self, slide, slide_number)
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
