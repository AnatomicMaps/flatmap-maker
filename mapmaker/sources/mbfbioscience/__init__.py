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

import json
import os
from urllib.parse import urljoin

#===============================================================================

import cv2
from lxml import etree
import numpy as np
import shapely.geometry

#===============================================================================

from .. import MapSource, RasterSource
from .. import WORLD_METRES_PER_UM

from mapmaker.flatmap.layers import MapLayer
from mapmaker.geometry import Transform
from mapmaker.settings import settings
from mapmaker.sources import mask_image
from mapmaker.utils import FilePath

#===============================================================================

SPARC_DATASET_SIGNATURE = 'https://api.sparc.science/s3-resource/'

SPARC_DATASET_URL_FORMAT = 'https://sparc.science/datasets/{}?type=dataset'

def sparc_dataset(url):
#======================
    if url.startswith(SPARC_DATASET_SIGNATURE):
        return SPARC_DATASET_URL_FORMAT.format(url.split('/')[4])

#===============================================================================

class MBFSource(MapSource):
    def __init__(self, flatmap, id, source_href, boundary_id=None, exported=False):
        super().__init__(flatmap, id, source_href, 'image')
        self.__sparc_dataset = sparc_dataset(source_href)

        self.__boundary_id = boundary_id
        self.__boundary_geometry = None

        self.__layer = MapLayer(id, self, exported=exported)
        self.add_layer(self.__layer)

        self.__mbf = etree.parse(FilePath(source_href).get_fp()).getroot()
        self.__ns = self.__mbf.nsmap[None]

        sparcdata = self.__mbf.find(self.ns_tag('sparcdata'))
        self.__species = sparcdata.find(self.ns_tag('subject')).get('species')
        self.__organ = sparcdata.find(self.ns_tag('atlas')).get('rootid')

        image_element = self.__mbf.find('{}/{}'.format(self.ns_tag('images'), self.ns_tag('image')))
        scale_element = image_element.find(self.ns_tag('scale'))
        scaling = (float(scale_element.get('x', 1.0)), float(scale_element.get('y', 1.0)))    # um/px
        coord_element = image_element.find(self.ns_tag('coord'))
        offset = (float(coord_element.get('x', 0.0)), float(coord_element.get('y', 0.0)))

        filename = image_element.find(self.ns_tag('filename')).text
        image_file = FilePath(urljoin(source_href, filename.split('\\')[-1]))
        image_array = np.frombuffer(image_file.get_data(), dtype=np.uint8)
        self.__image = cv2.imdecode(image_array, cv2.IMREAD_UNCHANGED)
        if self.__image.shape[2] == 3:
            self.__image = cv2.cvtColor(self.__image, cv2.COLOR_RGB2RGBA)
        image_size = (self.__image.shape[1], self.__image.shape[0])
        self.__image_to_world = (Transform([[scaling[0]*WORLD_METRES_PER_UM,                    0, 0],
                                            [                  0, -scaling[1]*WORLD_METRES_PER_UM, 0],
                                            [                  0,                               0, 1]])
                                 @np.array([[1, 0, -image_size[0]/2.0],
                                            [0, 1, -image_size[1]/2.0],
                                            [0, 0,                1.0]]))
        self.__world_to_image = self.__image_to_world.inverse()
        (width, height) = (scaling[0]*image_size[0], scaling[1]*image_size[1])               # um
        self.__um_to_world = (Transform([[WORLD_METRES_PER_UM,                   0, 0],
                                         [                  0, WORLD_METRES_PER_UM, 0],
                                         [                  0,                   0, 1]])
                              @np.array([[1, 0, -width/2.0],
                                         [0, 1, height/2.0],
                                         [0, 0,        1.0]]))
        top_left = self.__um_to_world.transform_point((0, 0))
        bottom_right = self.__um_to_world.transform_point((width, -height))
        # southwest and northeast corners
        self.bounds = (top_left[0], bottom_right[1], bottom_right[0], top_left[1])

    @property
    def boundary_geometry(self):
        return self.__boundary_geometry

    @property
    def image_to_world(self):
        return self.__image_to_world

    @property
    def organ(self):
        return self.__organ

    @property
    def species(self):
        return self.__species

    def __set_raster_source(self, boundary_geometry):
    #================================================
        if boundary_geometry is not None and boundary_geometry.geom_type == 'Polygon':
            # Save boundary in case transformed image is used for details
            self.__boundary_geometry = boundary_geometry
            # Mask image with boundary to remove artifacts
            self.__image = mask_image(self.__image,
                                      self.__world_to_image.transform_geometry(boundary_geometry))
        self.set_raster_source(RasterSource('image', self.__image))

    def ns_tag(self, tag):
    #=====================
        return '{{{}}}{}'.format(self.__ns, tag)

    def process(self):
    #=================
        boundary_geometry = None
        for contour in self.__mbf.findall(self.ns_tag('contour')):
            label = contour.get('name')
            association = contour.xpath('ns:property[@name="TraceAssociation"]/ns:s', namespaces={'ns': self.__ns})
            anatomical_id = association[0].text if len(association) else None
            points = []
            for point in contour.findall(self.ns_tag('point')):
                x = float(point.get('x'))
                y = float(point.get('y'))
                points.append(self.__um_to_world.transform_point((x, y)))

            if contour.get('closed'):
                if (points[0] != points[-1]).all():
                    points.append(points[-1])
                geometry = shapely.geometry.Polygon((points))
            else:
                geometry = shapely.geometry.LineString(points)

            properties = {'tile-layer': 'features'}
            if label is not None:
                properties['label'] = label
            if anatomical_id is not None:
                properties['models'] = anatomical_id
            feature = self.flatmap.new_feature(geometry, properties)
            feature.set_property('dataset', self.__sparc_dataset)
            feature.set_property('source', self.source_href)
            self.__layer.add_feature(feature)
            if anatomical_id == self.__boundary_id:
                boundary_geometry = feature.geometry
                self.__layer.boundary_feature = feature

        self.__set_raster_source(boundary_geometry)

#===============================================================================
