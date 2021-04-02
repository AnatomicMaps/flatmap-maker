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

import argparse
import json
import logging
import os, sys
import requests

#===============================================================================

from mapmaker import MapMaker, __version__
from mapmaker.utils import log

#===============================================================================

def arg_parser():
    parser = argparse.ArgumentParser(description='Generate a flatmap from its source manifest.')

    parser.add_argument('-v', '--version', action='version', version=__version__)

    log_options = parser.add_argument_group('logging')
    log_options.add_argument('--log', dest='logFile', metavar='LOG_FILE',
                        help="append messages to a log file")
    log_options.add_argument('--silent', action='store_true',
                        help='suppress all messages to screen')
    log_options.add_argument('--verbose', action='store_true',
                        help="show progress bars")

    tile_options = parser.add_argument_group('image tiling')
    tile_options.add_argument('--clean', action='store_true',
                        help="Remove all files from generated map's directory before generating new map")
    tile_options.add_argument('--background-tiles',  dest='backgroundTiles', action='store_true',
                        help="generate image tiles of map's layers (may take a while...)")

    debug_options = parser.add_argument_group('diagnostics')
    debug_options.add_argument('--check-errors', dest='errorCheck', action='store_true',
                        help='check for errors without generating a map')
    debug_options.add_argument('--save-drawml', dest='saveDrawML', action='store_true',
                        help="save a slide's DrawML for debugging")
    debug_options.add_argument('--save-geojson', dest='saveGeoJSON', action='store_true',
                        help='Save GeoJSON files for each layer')
    debug_options.add_argument('--tippecanoe', dest='showTippe', action='store_true',
                        help='Show command used to run Tippecanoe')

    zoom_options = parser.add_argument_group('zoom level')
    zoom_options.add_argument('--initialZoom', metavar='N', type=int, default=4,
                        help='initial zoom level (defaults to 4)')
    zoom_options.add_argument('--max-zoom', dest='maxZoom', metavar='N', type=int, default=10,
                        help='maximum zoom level (defaults to 10)')
    zoom_options.add_argument('--min-zoom', dest='minZoom', metavar='N', type=int, default=2,
                        help='minimum zoom level (defaults to 2)')

    misc_options = parser.add_argument_group('miscellaneous')
    misc_options.add_argument('--refresh-labels', dest='refreshLabels', action='store_true',
                        help='Clear the label text cache before map making')
    misc_options.add_argument('--upload', dest='uploadHost', metavar='USER@SERVER',
                        help='Upload generated map to server')

    required = parser.add_argument_group('required arguments')
    required.add_argument('--output', required=True,
                        help='base directory for generated flatmaps')
    required.add_argument('--source', required=True,
                        help='URL or path of a flatmap manifest')
    return parser

#===============================================================================

def main():
    parser = arg_parser()
    args = parser.parse_args()
    try:
        mapmaker = MapMaker(vars(args))
        mapmaker.make()
    except Exception as error:
        log.exception(str(error))

#===============================================================================

if __name__ == '__main__':
    main()

#===============================================================================
