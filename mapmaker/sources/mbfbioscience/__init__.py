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

from mapmaker.flatmap.layers import FeatureLayer
from mapmaker.geometry import Transform
from mapmaker.utils import path_data

#===============================================================================

class MBFSource(MapSource):
    def __init__(self, flatmap, id, source_path, boundary_id=None):
        super().__init__(flatmap, id)
        self.__boundary_id = boundary_id

        self.__layer = FeatureLayer(id, self)
        self.add_layer(self.__layer)

        self.__mbf = etree.parse(source_path).getroot()
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
        image_file = urljoin(source_path, filename.split('\\')[-1])
        image_array = np.frombuffer(path_data(image_file), dtype=np.uint8)
        image = cv2.imdecode(image_array, cv2.IMREAD_UNCHANGED)
        self.__raster_source = RasterSource('raster', image)

        image_size = (image.shape[1], image.shape[0])
        (width, height) = (scaling[0]*image_size[0], scaling[1]*image_size[1])               # um
        self.__transform = Transform([[WORLD_METRES_PER_UM,                   0, 0],
                                      [                  0, WORLD_METRES_PER_UM, 0],
                                      [                  0,                   0, 1]])@np.array([[1, 0, -width/2.0],
                                                                                                [0, 1, height/2.0],
                                                                                                [0, 0,        1.0]])
        top_left = self.__transform.transform_point((0, 0))
        bottom_right = self.__transform.transform_point((width, -height))
        # southwest and northeast corners
        self.bounds = (top_left[0], bottom_right[1], bottom_right[0], top_left[1])

    @property
    def raster_source(self):
        return self.__raster_source

    @property
    def organ(self):
        return self.__organ

    @property
    def species(self):
        return self.__species

    def ns_tag(self, tag):
    #=====================
        return '{{{}}}{}'.format(self.__ns, tag)

    def process(self):
    #=================
        for contour in self.__mbf.findall(self.ns_tag('contour')):
            label = contour.get('name')
            association = contour.xpath('ns:property[@name="TraceAssociation"]/ns:s', namespaces={'ns': self.__ns})
            anatomical_id = association[0].text if len(association) else None
            points = []
            for point in contour.findall(self.ns_tag('point')):
                x = float(point.get('x'))
                y = float(point.get('y'))
                points.append(self.__transform.transform_point((x, y)))

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
            self.__layer.add_feature(feature)
            if anatomical_id == self.__boundary_id:
                self.__layer.boundary_id = feature.feature_id

#===============================================================================
