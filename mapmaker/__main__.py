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
import requests

#===============================================================================

from mapmaker import __version__
from mapmaker.maker import Flatmap

#===============================================================================

def main():
    import configargparse
    import os, sys

    parser = configargparse.ArgumentParser() ## description='Convert Powerpoint slides to a flatmap.')

    parser.add_argument('-c', '--conf', is_config_file=True, help='configuration file containing arguments')

    parser.add_argument('-b', '--background-tiles',  dest='backgroundTiles', action='store_true',
                        help="generate image tiles of map's layers (may take a while...)")
    parser.add_argument('--background-only', dest='backgroundOnly', action='store_true',
                        help="don't generate vector tiles (sets --background-tiles)")

    parser.add_argument('--check-errors', dest='errorCheck', action='store_true',
                        help='check for errors without generating a map')
    parser.add_argument('-z', '--initialZoom', metavar='N', type=int, default=4,
                        help='initial zoom level (defaults to 4)')
    parser.add_argument('--max-zoom', dest='maxZoom', metavar='N', type=int, default=10,
                        help='maximum zoom level (defaults to 10)')
    parser.add_argument('--min-zoom', dest='minZoom', metavar='N', type=int, default=2,
                        help='minimum zoom level (defaults to 2)')

    parser.add_argument('-d', '--debug', dest='debugXml', action='store_true',
                        help="save a slide's DrawML for debugging")
    parser.add_argument('-s', '--save-geojson', dest='saveGeoJSON', action='store_true',
    parser.add_argument('--save-beziers', dest='saveBeziers', action='store_true',
                        help='Save Bezier curve segments as a feature property')
                        help='Save GeoJSON files for each layer')
    parser.add_argument('-t', '--tippecanoe', dest='showTippe', action='store_true',
                        help='Show command used to run Tippecanoe')

    parser.add_argument('--clean', action='store_true',
                        help="Remove all files from generated map's directory before generating new map")
    parser.add_argument('--refresh-labels', dest='refreshLabels', action='store_true',
                        help='Clear the label text cache before map making')
    parser.add_argument('--upload', dest='uploadHost', metavar='USER@SERVER',
                        help='Upload generated map to server')

    parser.add_argument('-q', '--quiet', action='store_true',
                        help="don't show progress messages")
    parser.add_argument('-v', '--version', action='version', version=__version__)

    required = parser.add_argument_group('required arguments')

    required.add_argument('--output-dir', dest='outputDir', metavar='OUTPUT_DIR', required=True,
                        help='base directory for generated flatmaps')
    required.add_argument('--map', dest='mapPath', metavar='MAP_PATH', required=True,
                        help='URL or directory path containing a flatmap manifest')

    args = parser.parse_args()
    try:
        flatmap = Flatmap(vars(args))
        flatmap.make()
    except ValueError as error:
        sys.exit(error)

#===============================================================================

if __name__ == '__main__':
    main()

#===============================================================================
