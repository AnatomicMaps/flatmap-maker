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

import json
import math
import os

#===============================================================================

import shapely.geometry

#===============================================================================

from mapmaker.geometry import mercator_transform
from mapmaker.sources.markup import ignore_property
from mapmaker.utils import ProgressBar

#===============================================================================

class GeoJSONOutput(object):
    def __init__(self, layer, map_area, output_dir):
    #================================================
        self.__layer = layer
        self.__map_area = map_area
        self.__output_dir = output_dir
        self.__geojson_layers = {
            'features': [],
            'pathways': [],
            'autopaths': [],
        }

    def save(self, features, pretty_print=False):
    #============================================
        self.__save_features(features)
        saved_filenames = {}
        for geojson_id in self.__geojson_layers:
            filename = os.path.join(self.__output_dir, '{}_{}.json'.format(self.__layer.id, geojson_id))
            saved_filenames[geojson_id] = filename
            with open(filename, 'w') as output_file:
                if pretty_print:
                    feature_collection = {
                        'type': 'FeatureCollection',
                        'features': self.__geojson_layers.get(geojson_id, [])
                    }
                    output_file.write(json.dumps(feature_collection, indent=4))
                else:
                    # Tippecanoe doesn't need a FeatureCollection
                    # Delimit features with RS...LF   (RS = 0x1E)
                    for feature in self.__geojson_layers.get(geojson_id, []):
                        output_file.write('\x1E{}\x0A'.format(json.dumps(feature)))
        return saved_filenames

    def __save_features(self, features):
    #===================================
        progress_bar = ProgressBar(total=len(features),
            unit='ftr', ncols=40,
            bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}')

        for feature in features:
            properties = feature.properties.copy()
            if 'bezier-segments' in properties:  # There's no need to export paths
                properties.pop('bezier-segments')
            geometry = feature.geometry
            area = geometry.area
            mercator_geometry = mercator_transform(geometry)
            geojson = {
                'type': 'Feature',
                'id': feature.feature_id,
                'tippecanoe' : {
                    'layer' : properties['tile-layer']
                },
                'geometry': shapely.geometry.mapping(mercator_geometry),
                'properties': {
                    'bounds': list(mercator_geometry.bounds),
                    # The viewer requires `centroid`
                    'centroid': list(list(mercator_geometry.centroid.coords)[0]),
                    'area': area,
                    'length': geometry.length,
                    'layer': self.__layer.id,
                }
            }
            if 'maxzoom' in properties:
                geojson['tippecanoe']['maxzoom'] = properties['maxzoom']
            if 'minzoom' in properties:
                geojson['tippecanoe']['minzoom'] = properties['minzoom']
            if area > 0:
                scale = math.log(math.sqrt(self.__map_area/area), 2)
                geojson['properties']['scale'] = scale
                if scale > 6 and 'group' not in properties and 'minzoom' not in properties:
                    geojson['tippecanoe']['minzoom'] = 5
            else:
                geojson['properties']['scale'] = 10

            for (key, value) in properties.items():
                if not ignore_property(key):
                    geojson['properties'][key] = value
            properties['bounds'] = geojson['properties']['bounds']
            properties['centroid'] = geojson['properties']['centroid']
            properties['geometry'] = geojson['geometry']['type']
            properties['layer'] = self.__layer.id

            # The layer's annotation had property details for each feature
            self.__layer.annotate(feature, properties)

            self.__geojson_layers[properties['tile-layer']].append(geojson)
            progress_bar.update(1)

        progress_bar.close()
