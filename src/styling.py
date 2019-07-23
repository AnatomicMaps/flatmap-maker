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
    def style(background_image, bounds):
        return {
            'type': 'image',
            'url': '/images/{}'.format(background_image),
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
    def style(layer_id, bounds, map_zoom):
        return {
            'type': 'raster',
            'tiles': ['/tiles/{}/{{z}}/{{x}}/{{y}}'.format(layer_id)],
            'format': 'png',
            'minzoom': map_zoom[0],
            'maxzoom': map_zoom[1],
            'bounds': bounds    # southwest(lng, lat), northeast(lng, lat)
        }

#===============================================================================

class VectorSource(object):
    @staticmethod
    def style(vector_layer_dict, bounds, map_zoom):
        return {
            'type': 'vector',
            'tiles': ['/mvtiles/{z}/{x}/{y}'],
            'format': 'pbf',
            'version': '2',
            'minzoom': map_zoom[0],
            'maxzoom': map_zoom[1],
            'bounds': bounds,   # southwest(lng, lat), northeast(lng, lat)
            'attribution': ATTRIBUTION,
            'generator': 'tippecanoe v1.34.0',
            'vector_layers': vector_layer_dict['vector_layers'],
            'tilestats': vector_layer_dict['tilestats']
        }

#===============================================================================

class Sources(object):
    @staticmethod
    def style(layers, vector_layer_dict, bounds, map_zoom):
        sources = {
            'features': VectorSource.style(vector_layer_dict, bounds, map_zoom)
        }
        for layer_id in layers:
            sources['{}-image'.format(layer_id)] = RasterSource.style(layer_id, bounds, map_zoom)
        return sources

#===============================================================================

class Style(object):
    @staticmethod
    def style(layers, metadata, map_zoom):
        vector_layer_dict = json.loads(metadata['json'])
        bounds = [float(x) for x in metadata['bounds'].split(',')]
        return {
            'version': 8,
            'sources': Sources.style(layers, vector_layer_dict, bounds, map_zoom),
            'zoom': map_zoom[2],
            'center': [float(x) for x in metadata['center'].split(',')],
            'layers': []
        }

#===============================================================================
