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

from .. import MapSource, ImageTileSource

from mapmaker.geometry import transform_point

from .slide import PowerpointSlide

#===============================================================================

METRES_PER_EMU = 0.1   ## This to become a command line parameter...
                       ## Or in a specification file...

#===============================================================================

class PowerpointSource(MapSource):
    def __init__(self, flatmap, id, source_path, get_background=False):
        super().__init__(flatmap, id)
        if source_path.startswith('http:') or source_path.startswith('https:'):
            response = requests.get(source_path)
            if response.status_code != requests.codes.ok:
                raise ValueError('Cannot retrieve remote Powerpoint')
            pptx_modified = 0   ## Can we get timestamp from PMR metadata??
            pptx_file = io.BytesIO(response.content)
        else:
            if not os.path.exists(source_path):
                raise ValueError('Missing Powerpoint file')
            pptx_modified = os.path.getmtime(source_path)
            pptx_file = open(source_path, 'rb')

        self.__pptx = Presentation(pptx_file)
        pptx_file.close()
        self.__slides = self.__pptx.slides

        (width, height) = (self.__pptx.slide_width, self.__pptx.slide_height)
        self.__transform = np.array([[METRES_PER_EMU,               0, 0],
                                    [              0, -METRES_PER_EMU, 0],
                                    [              0,               0, 1]])@np.array([[1, 0, -width/2.0],
                                                                                      [0, 1, -height/2.0],
                                                                                      [0, 0,         1.0]])
        top_left = transform_point(self.__transform, (0, 0))
        bottom_right = transform_point(self.__transform, (width, height))
        # southwest and northeast corners
        self.bounds = (top_left[0], bottom_right[1], bottom_right[0], top_left[1])

        if get_background:
            pdf_source = '{}.pdf'.format(os.path.splitext(source_path)[0])
            if pdf_source.startswith('http:') or pdf_source.startswith('https:'):
                response = requests.get(pdf_source)
                if response.status_code != requests.codes.ok:
                    pptx_bytes.close()
                    raise ValueError('Cannot retrieve PDF of Powerpoint (needed to generate background tiles)')
                pdf_bytes = io.BytesIO(response.content)
            else:
                if not os.path.exists(pdf_source):
                    raise ValueError('Missing PDF of Powerpoint (needed to generate background tiles)')
                if os.path.getmtime(pdf_source) < pptx_modified:
                    raise ValueError('PDF of Powerpoint is too old...')
                with open(pdf_source, 'rb') as f:
                    pdf_bytes = f.read()
            self.__image_tile_source = ImageTileSource('pdf', pdf_bytes)
        else:
            self.__image_tile_source = None

    @property
    def image_tile_source(self):
        return self.__image_tile_source

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

#===============================================================================



