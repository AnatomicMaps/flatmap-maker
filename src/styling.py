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

#===============================================================================

ATTRIBUTION = '© <a href="https://www.auckland.ac.nz/en/abi.html">Auckland Bioengineering Institute</a>'

#===============================================================================

class ImageSource(object):
    @staticmethod
    def style(map_id, background_image, bounds):
        return {
            'type': 'image',
            'url': '/{}/images/{}'.format(map_id, background_image),
            'coordinates': [
                [bounds[0], bounds[3]],  # top-left (nw)
                [bounds[2], bounds[3]],  # top-right (ne)
                [bounds[2], bounds[1]],  # bottom-right (se)
                [bounds[0], bounds[1]]   # bottom-left (sw)
            ]
        }

#===============================================================================

class RasterSource(object):
    @staticmethod
    def style(map_id, layer_id, bounds, max_zoom):
        return {
            'type': 'raster',
            'tiles': ['/{}/tiles/{}/{{z}}/{{x}}/{{y}}'.format(map_id, layer_id)],
            'format': 'png',
            'minzoom': 0,
            'maxzoom': max_zoom,
            'bounds': bounds    # southwest(lng, lat), northeast(lng, lat)
        }

#===============================================================================

class VectorSource(object):
    @staticmethod
    def style(map_id, vector_layer_dict, bounds, max_zoom):
        return {
            'type': 'vector',
            'tiles': ['/{}/mvtiles/{{z}}/{{x}}/{{y}}'.format(map_id)],
            'format': 'pbf',
            'version': '2',
            'minzoom': 0,
            'maxzoom': max_zoom,
            'bounds': bounds,   # southwest(lng, lat), northeast(lng, lat)
            'attribution': ATTRIBUTION,
            'generator': 'tippecanoe v1.34.0',
            'vector_layers': vector_layer_dict['vector_layers'],
            'tilestats': vector_layer_dict['tilestats']
        }

#===============================================================================

class Sources(object):
    @staticmethod
    def style(map_id, layers, vector_layer_dict, bounds, max_zoom):
        sources = {
            'features': VectorSource.style(map_id, vector_layer_dict, bounds, max_zoom)
        }
        sources['background'] = RasterSource.style(map_id, 'background', bounds, max_zoom)
                              # ImageSource.style(map_id, 'background.png', bounds)
        for layer_id in layers:
            sources['{}-background'.format(layer_id)] = RasterSource.style(map_id, layer_id, bounds, max_zoom)
                                                      # ImageSource.style(map_id, '{}.png'.format(layer_id), bounds)
        return sources

#===============================================================================

class Style(object):
    @staticmethod
    def style(map_id, layers, metadata, max_zoom):
        vector_layer_dict = json.loads(metadata['json'])
        bounds = [float(x) for x in metadata['bounds'].split(',')]
        return {
            'version': 8,
            'sources': Sources.style(map_id, layers, vector_layer_dict, bounds, max_zoom),
            'zoom': 0,
            'center': [float(x) for x in metadata['center'].split(',')],
            'layers': []
        }

#===============================================================================
