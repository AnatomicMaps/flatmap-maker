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

from .. import MapSource

from mapmaker.geometry import mercator_transform, mercator_transformer, transform_point

from .slide import PowerpointSlide

#===============================================================================

METRES_PER_EMU = 0.1   ## This to become a command line parameter...
                       ## Or in a specification file...

#===============================================================================

class PowerpointSource(MapSource):
    def __init__(self, flatmap, id, source_path):
        super().__init__(flatmap, id, source_path)
        if source_path.startswith('http:') or source_path.startswith('https:'):
            response = requests.get(source_path)
            if response.status_code != requests.codes.ok:
                raise ValueError('Cannot retrieve remote Powerpoint')
            pptx_file = io.BytesIO(response.content)
        else:
            if not os.path.exists(source_path):
                raise ValueErrort('Missing Powerpoint file')
            pptx_file = open(source_path, 'rb')

        self.__pptx = Presentation(pptx_file)
        pptx_file.close()

        self.__slides = self.__pptx.slides

        (width, height) = (self.__pptx.slide_width, self.__pptx.slide_height)
        self.__bounds = (0, 0, width, height)
        self.__transform = np.array([[METRES_PER_EMU,               0, 0],
                                    [              0, -METRES_PER_EMU, 0],
                                    [              0,               0, 1]])@np.array([[1, 0, -width/2.0],
                                                                                      [0, 1, -height/2.0],
                                                                                      [0, 0,         1.0]])
    @property
    def transform(self):
        return self.__transform

    def process(self):
    #=================
        for n in range(len(self.__slides)):
            slide = self.__slides[n]
            slide_number = n + 1
            slide_layer = PowerpointSlide(self, slide, slide_number)
            print('Slide {}, {}'.format(slide_number, slide_layer.id))
            if self.flatmap.options.get('debugXml'):
                xml = open(os.path.join(self.flatmap.map_directory,
                                        '{}.xml'.format(slide_layer.id)), 'w')
                xml.write(slide.element.xml)
                xml.close()
            slide_layer.process()
            for error in self.errors:
                print(error)
            else:
                self.add_layer(slide_layer.feature_layer)

    def map_area(self):
    #==================
        bounds = self.__bounds
        top_left = transform_point(self.__transform, (bounds[0], bounds[1]))
        bottom_right = transform_point(self.__transform, (bounds[2], bounds[3]))
        return abs(bottom_right[0] - top_left[0]) * (top_left[1] - bottom_right[1])

    def extent(self):
    #================
        bounds = self.__bounds
        top_left = mercator_transformer.transform(*transform_point(self.__transform, (bounds[0], bounds[1])))
        bottom_right = mercator_transformer.transform(*transform_point(self.__transform, (bounds[2], bounds[3])))
        # southwest and northeast corners
        return (top_left[0], bottom_right[1], bottom_right[0], top_left[1])

#===============================================================================



