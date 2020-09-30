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
from pathlib import Path

#===============================================================================

import cv2
from lxml import etree
import numpy as np
import shapely.geometry

#===============================================================================

from flatmap import Flatmap, MapLayer
from geometry import mercator_transform, mercator_transformer, transform_point
from tilemaker import make_background_tiles_from_image

#===============================================================================

METRES_PER_UM = 100

#===============================================================================

class MBFLayer(MapLayer):
    def __init__(self, xml_file, id):
        super().__init__(id)
        self.__xml_file = xml_file

        self.__mbf = etree.parse(xml_file).getroot()
        self.__ns = self.__mbf.nsmap[None]

        sparcdata = self.__mbf.find(self.ns_tag('sparcdata'))
        self.__species = sparcdata.find(self.ns_tag('subject')).get('species')
        self.__organ = sparcdata.find(self.ns_tag('atlas')).get('rootid')

        image_element = self.__mbf.find('{}/{}'.format(self.ns_tag('images'), self.ns_tag('image')))
        scale_element = image_element.find(self.ns_tag('scale'))
        scaling = (float(scale_element.get('x', 1.0)), float(scale_element.get('y', 1.0)))     # um/px
        coord_element = image_element.find(self.ns_tag('coord'))
        offset = (float(coord_element.get('x', 0.0)), float(coord_element.get('y', 0.0)))

        filename = image_element.find(self.ns_tag('filename')).text
        image_file = Path(xml_file).with_name(filename.split('\\')[-1])
        #self.__image = Image.open(image_file)
        self.__image = cv2.imread(image_file.as_posix(), cv2.IMREAD_UNCHANGED)

        image_size = (self.__image.shape[1], self.__image.shape[0])
        self.__bounds = (0, 0, scaling[0]*image_size[0], -scaling[1]*image_size[1])  # um
        self.__transform = np.array([[METRES_PER_UM,             0, 0],
                                     [            0, METRES_PER_UM, 0],
                                     [            0,             0, 1]])@np.array([[1, 0, -self.__bounds[2]/2.0],
                                                                                   [0, 1, -self.__bounds[3]/2.0],
                                                                                   [0, 0,                   1.0]])
    @property
    def image(self):
        return self.__image

    @property
    def organ(self):
        return self.__organ

    @property
    def species(self):
        return self.__species

    def image_area(self):
    #====================
        top_left = transform_point(self.__transform, (self.__bounds[0], self.__bounds[1]))
        bottom_right = transform_point(self.__transform, (self.__bounds[2], self.__bounds[3]))
        return abs(bottom_right[0] - top_left[0]) * (top_left[1] - bottom_right[1])

    def latlng_bounds(self):
    #=======================
        top_left = mercator_transformer.transform(*transform_point(self.__transform, (self.__bounds[0], self.__bounds[1])))
        bottom_right = mercator_transformer.transform(*transform_point(self.__transform, (self.__bounds[2], self.__bounds[3])))
        # southwest and northeast corners
        return (top_left[0], bottom_right[1], bottom_right[0], top_left[1])

    def ns_tag(self, tag):
    #=====================
        return '{{{}}}{}'.format(self.__ns, tag)

    def geojson_features(self, tile_layer):
    #======================================
        features = []
        next_id = 1
        for contour in self.__mbf.findall(self.ns_tag('contour')):
            label = contour.get('name')
            association = contour.xpath('ns:property[@name="TraceAssociation"]/ns:s', namespaces={'ns': self.__ns})
            anatomical_id = association[0].text if len(association) else None
            points = []
            for point in contour.findall(self.ns_tag('point')):
                x = float(point.get('x'))
                y = float(point.get('y'))
                points.append(transform_point(self.__transform, (x, y)))

            if contour.get('closed'):
                if points[0] != points[-1]:
                    points.append(points[-1])
                geometry = shapely.geometry.Polygon((points))
            else:
                geometry = shapely.geometry.LineString(points)
            mercator_geometry = mercator_transform(geometry)

            source_layer = '{}-{}'.format(self.id, tile_layer)
            feature = {
                'type': 'Feature',
                'id': next_id,   # Must be numeric for tipeecanoe
                'tippecanoe' : {
                    'layer' : source_layer
                },
                'geometry': shapely.geometry.mapping(mercator_geometry),
                'properties': {
                    'area': geometry.area,
                    'bounds': list(mercator_geometry.bounds),
                    # The viewer requires `centroid`
                    'centroid': list(list(mercator_geometry.centroid.coords)[0]),
                    'id': '{}#{}'.format(self.id, next_id),
                    'length': geometry.length,
                    'layer': self.id,
                    'source-layer': source_layer,
                    'tile-layer': 'features',
                    'scale': 1,
                }
            }
            if label is not None:
                feature['properties']['label'] = label
            if anatomical_id is not None:
                feature['properties']['models'] = anatomical_id
            features.append(feature)
            next_id += 1

        return features

    def save(self, map_dir):
    #=======================
        tile_layer = 'features'
        filename = os.path.join(map_dir, '{}_{}.json'.format(self.id, tile_layer))
        # Tippecanoe doesn't need a FeatureCollection
        # Delimit features with RS...LF   (RS = 0x1E)
        with open(filename, 'w') as output_file:
            for feature in self.geojson_features(tile_layer):
                output_file.write('\x1E{}\x0A'.format(json.dumps(feature)))
        return {tile_layer: filename}

#===============================================================================

def main():
#==========
    import argparse
    import sys

    parser = argparse.ArgumentParser(description='Convert a segmented MBF image to a flatmap.')

    parser.add_argument('-z', '--initial-zoom', metavar='N', type=int, default=4,
                        help='initial zoom level (defaults to 4)')
    parser.add_argument('--max-zoom', dest='max_zoom', metavar='N', type=int, default=10,
                        help='maximum zoom level (defaults to 10)')
    parser.add_argument('--min-zoom', dest='min_zoom', metavar='N', type=int, default=2,
                        help='minimum zoom level (defaults to 2)')
    parser.add_argument('-u', '--upload', metavar='USER@SERVER',
                        help='Upload generated map to server')

    required = parser.add_argument_group('required arguments')
    required.add_argument('--map-dir', dest='map_base', metavar='MAP_DIR', required=True,
                        help='base directory for generated flatmaps')
    required.add_argument('--id', dest='map_id', metavar='MAP_ID', required=True,
                        help='a unique identifier for the map')
    required.add_argument('--mbf', dest='mbf_file', metavar='MBF_XML', required=True,
                        help='File or URL of MBF XML file of segmented image')

    args = parser.parse_args()

    if args.min_zoom < 0 or args.min_zoom > args.max_zoom:
        sys.exit('--min-zoom must be between 0 and {}'.format(args.max_zoom))
    if args.max_zoom < args.min_zoom or args.max_zoom > 15:
        sys.exit('--max-zoom must be between {} and 15'.format(args.min_zoom))
    if args.initial_zoom < args.min_zoom or args.initial_zoom > args.max_zoom:
        sys.exit('--initial-zoom must be between {} and {}'.format(args.min_zoom, args.max_zoom))

    map_zoom = (args.min_zoom, args.max_zoom, args.initial_zoom)

    map_dir = os.path.join(args.map_base, args.map_id)
    if not os.path.exists(map_dir):
        os.makedirs(map_dir)

    if not os.path.exists(args.mbf_file):
        sys.exit('Missing MBF XML file')

    mbf_layer = MBFLayer(os.path.abspath(args.mbf_file), 'vagus')
    flatmap = Flatmap(args.map_id, args.mbf_file, ' '.join(sys.argv),
                      map_dir, map_zoom, mbf_layer.latlng_bounds())
    flatmap.add_layer(mbf_layer)

    print('Running tippecanoe...')
    flatmap.make_vector_tiles()

    print('Creating index and style files...')
    flatmap.save_map_json(True)

    """
    Only if no os.path.isfile(os.path.join(map_dir, '{}.mbtiles'.format(args.map_id)))) ??
    force with --background-tiles option ??

    """
    print('Generating background tiles (may take a while...)')
    image_tile_files = make_background_tiles_from_image(flatmap.bounds, map_zoom, map_dir,
                                                        mbf_layer.image, args.mbf_file, args.map_id)
    flatmap.add_upload_files(image_tile_files)

    if args.upload:
        print('Uploaded map...', flatmap.upload(args.map_base, args.upload))

    # Tidy up
    print('Cleaning up...')
    flatmap.finalise(True)

#===============================================================================

if __name__ == '__main__':
    main()

#===============================================================================
