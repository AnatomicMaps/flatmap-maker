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

from pathlib import Path

#===============================================================================

from lxml import etree
from PIL import Image

import numpy as np
import shapely.geometry

#===============================================================================

from geometry import mercator_transform, mercator_transformer, transform_point
from tilemaker import make_background_tiles_from_image

#===============================================================================

METRES_PER_PIXEL = 10

#===============================================================================

class MBFXmlFile(object):
    def __init__(self, xml_file, layer_id):
        self._xml_file = xml_file
        self._layer_id = layer_id

        self._mbf = etree.parse(xml_file).getroot()
        self._ns = self._mbf.nsmap[None]

        sparcdata = self._mbf.find(self.ns_tag('sparcdata'))
        self._species = sparcdata.find(self.ns_tag('subject')).get('species')
        self._organ = sparcdata.find(self.ns_tag('atlas')).get('rootid')

        image = self._mbf.find('{}/{}'.format(self.ns_tag('images'), self.ns_tag('image')))
        scale = image.find(self.ns_tag('scale'))
        self._scale = (float(scale.get('x', 1.0)), float(scale.get('y', 1.0)))
        coord = image.find(self.ns_tag('coord'))
        self._offset = (float(coord.get('x', 0.0)), float(coord.get('y', 0.0)))

        filename = image.find(self.ns_tag('filename')).text
        image_file = Path(xml_file).with_name(filename.split('\\')[-1])

        self._image = Image.open(image_file)
        self._bounds = (0, 0, self._image.width, self._image.height)
        self._transform = np.array([[METRES_PER_PIXEL,                 0, 0],
                                    [               0, -METRES_PER_PIXEL, 0],
                                    [               0,                 0, 1]])@np.array([[1, 0, -self._bounds[2]/2.0],
                                                                                         [0, 1, -self._bounds[3]/2.0],
                                                                                         [0, 0,                  1.0]])
    @property
    def organ(self):
    #===============
        return self._organ

    @property
    def species(self):
    #=================
        return self._species

    def image_area(self):
    #====================
        top_left = transform_point(self._transform, (self._bounds[0], self._bounds[1]))
        bottom_right = transform_point(self._transform, (self._bounds[2], self._bounds[3]))
        return abs(bottom_right[0] - top_left[0]) * (top_left[1] - bottom_right[1])

    def latlng_bounds(self):
    #=======================
        top_left = mercator_transformer.transform(*transform_point(self._transform, (self._bounds[0], self._bounds[1])))
        bottom_right = mercator_transformer.transform(*transform_point(self._transform, (self._bounds[2], self._bounds[3])))
        return [top_left[0], top_left[1], bottom_right[0], bottom_right[1]]

    def ns_tag(self, tag):
    #=====================
        return '{{{}}}{}'.format(self._ns, tag)

    def scale_offset(self, point):
    #=============================
        return (self._scale[0]*point[0] + self._offset[0],
                self._scale[1]*point[1] + self._offset[1])

    def geojson_features(self):
    #==========================
        features = []
        next_id = 1
        for contour in self._mbf.findall(self.ns_tag('contour')):
            anatomical_id = contour.xpath('ns:property[name="TraceAssociation"]/ns:s', namespaces={'ns': self._ns}).text

            points = []
            for point in contour.findall(self.ns_tag('point')):
                points.append((point['x'], point['y']))
            if contour.get('closed'):
                if points[0] != points[-1]:
                    points.append(points[-1])
                geometry = shapely.geometry.Polygon((points))
            else:
                geometry = shapely.geometry.LineString(points)
            mercator_geometry = mercator_transform(geometry)

            features.append({
                'type': 'Feature',
                'id': next_id,   # Must be numeric for tipeecanoe
                'tippecanoe' : {
                    'layer' : self._layer_id
                },
                'geometry': shapely.geometry.mapping(mercator_geometry),
                'properties': {
                    'area': geometry.area,
                    'bounds': list(mercator_geometry.bounds),
                    # The viewer requires `centroid`
                    'centroid': list(list(mercator_geometry.centroid.coords)[0]),
                    'length': geometry.length,
                    'layer': self._layer_id,
                    'models': anatomical_id
                }
            })
            next_id += 1

#===============================================================================

def main():
#==========
    mbf_xml = MBFXmlFile('mbf/pig/sub-10_sam-1_P10-1MergeMask.xml', 'features')

    #make_background_tiles_from_image(map_extent, [MIN_ZOOM, max_zoom],
    #                                '../maps/demo', jpeg_file, 'test')

#===============================================================================

if __name__ == '__main__':
    main()

#===============================================================================
