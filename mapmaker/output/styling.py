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

from mapmaker.geometry import MapBounds

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

class MBRasterTileSource(object):
    @staticmethod
    def style(layer_id, bounds, min_zoom, max_zoom):
        return {
            'type': 'raster',
            'tiles': ['/tiles/{}/{{z}}/{{x}}/{{y}}'.format(layer_id)],
            'format': 'png',
            'minzoom': min_zoom,
            'maxzoom': max_zoom,
            'bounds': bounds    # southwest(lng, lat), northeast(lng, lat)
        }

#===============================================================================

class MBVectorTileSource(object):
    @staticmethod
    def style(vector_sources, bounds, layer_zoom):
        return {
            'type': 'vector',
            'tiles': ['/mvtiles/{z}/{x}/{y}'],
            'format': 'pbf',
            'version': '2',
            'minzoom': layer_zoom[0],
            'maxzoom': layer_zoom[1],
            'bounds': bounds,   # southwest(lng, lat), northeast(lng, lat)
            'attribution': ATTRIBUTION,
            'generator': 'tippecanoe',
            'vector_layers': vector_sources['vector_layers'],
            'tilestats': vector_sources['tilestats']
        }

#===============================================================================

class MBTileSources(object):
    @staticmethod
    def style(raster_sources, vector_sources, bounds, map_zoom):
        sources = {}
        sources['vector-tiles'] = MBVectorTileSource.style(vector_sources, bounds, map_zoom)
        for source in raster_sources:
            sources[source.id] = MBRasterTileSource.style(source.id, bounds, source.min_zoom, source.max_zoom)
        return sources

#===============================================================================

class PMTileSources(object):
    @staticmethod
    def style(raster_sources):
        sources = {
            'vector-tiles': {
                'type': 'vector',
                'url': 'pmtiles:/'
            }
        }
        for source in raster_sources:
            sources[source.id] = {
                'type': 'raster',
                'url': f'pmtiles:/{source.id}'
            }
        return sources

#===============================================================================

class MapStyle(object):
    @staticmethod
    def style(raster_sources, mb_vector_sources, map_zoom, bounds: MapBounds, centre: tuple[float, float]):
        return {
            'version': 8,
            'sources': PMTileSources.style(raster_sources) if mb_vector_sources is None
                  else MBTileSources.style(raster_sources, mb_vector_sources, bounds, map_zoom),
            'glyphs': 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
            'zoom': map_zoom[2],
            'center': centre,
            'layers': []
        }

#===============================================================================
