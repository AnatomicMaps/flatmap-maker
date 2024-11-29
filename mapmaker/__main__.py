#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019 - 2023  David Brooks
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

#===============================================================================

from mapmaker import MapMaker, __version__
from mapmaker.utils import log

#===============================================================================

def arg_parser():
    parser = argparse.ArgumentParser(description='Generate a flatmap from its source manifest.')

    parser.add_argument('-v', '--version', action='version', version=__version__)

    log_options = parser.add_argument_group('Logging')
    log_options.add_argument('--log', dest='logFile', metavar='LOG_FILE',
                        help="Append messages to a log file")
    log_options.add_argument('--silent', action='store_true',
                        help='Suppress all messages to screen')
    log_options.add_argument('--verbose', action='store_true',
                        help="Show progress bars")

    generation_options = parser.add_argument_group('Map generation')
    generation_options.add_argument('--all-path-taxons', dest='allPathTaxons', action='store_true', default=True,
                        help="Include paths whose taxons don't match the map's taxon")
    generation_options.add_argument('--background-tiles',  dest='backgroundTiles', action='store_true',
                        help="Generate image tiles of map's layers (may take a while...)")
    generation_options.add_argument('--clean-connectivity', dest='cleanConnectivity', action='store_true',
                        help='Refresh local connectivity knowledge from SciCrunch')
    generation_options.add_argument('--disconnected-paths', dest='disconnectedPaths', action='store_true',
                        help="Include paths that are disconnected in the map")
    generation_options.add_argument('--force', action='store_true',
                        help="Generate the map even if it already exists")
    generation_options.add_argument('--id', metavar='ID',
                        help='Set explicit ID for flatmap, overriding manifest')
    generation_options.add_argument('--ignore-git', dest='ignoreGit', action='store_true',
                        help="Don't check that sources are committed into git")
    generation_options.add_argument('--ignore-sckan', dest='ignoreSckan', action='store_true',
                        help="Don't check if functional connectivity neurons are known in SCKAN. Sets `--invalid-neurons` option")
    generation_options.add_argument('--invalid-neurons', dest='invalidNeurons', action='store_true',
                        help="Include functional connectivity neurons that aren't known in SCKAN")
    generation_options.add_argument('--no-path-layout', dest='noPathLayout', action='store_true',
                        help="Don't do `TransitMap` optimisation of paths")
    generation_options.add_argument('--publish', metavar='SPARC_DATASET',
                        help="Create a SPARC Dataset containing the map's sources and the generated map")
    generation_options.add_argument('--sckan-version', dest='sckanVersion', choices=['production', 'staging'],
                        help="Overide version of SCKAN specified by map's manifest")

    debug_options = parser.add_argument_group('Diagnostics')
    debug_options.add_argument('--authoring', action='store_true',
                        help="For use when checking a new map: highlight incomplete features; show centreline network; no image tiles; no neuron paths; etc")
    debug_options.add_argument('--debug', action='store_true',
                        help='See `log.debug()` messages in log')
    debug_options.add_argument('--only-networks', dest='onlyNetworks', action='store_true',
                        help='Only output features that are part of a centreline network')
    debug_options.add_argument('--save-drawml', dest='saveDrawML', action='store_true',
                        help="Save a slide's DrawML for debugging")
    debug_options.add_argument('--save-geojson', dest='saveGeoJSON', action='store_true',
                        help='Save GeoJSON files for each layer')
    debug_options.add_argument('--tippecanoe', dest='showTippe', action='store_true',
                        help='Show command used to run Tippecanoe')

    zoom_options = parser.add_argument_group('Zoom level')
    zoom_options.add_argument('--initial-zoom', dest='initialZoom', metavar='N', type=int, default=4,
                        help='Initial zoom level (defaults to 4)')
    zoom_options.add_argument('--max-zoom', dest='maxZoom', metavar='N', type=int, default=10,
                        help='Maximum zoom level (defaults to 10)')
    zoom_options.add_argument('--max-raster-zoom', dest='maxRasterZoom', metavar='N', type=int,
                        help='Maximum zoom level of rasterised tiles (defaults to maximum zoom level)')

    misc_options = parser.add_argument_group('Miscellaneous')
    misc_options.add_argument('--commit', metavar='GIT_COMMIT',
                        help='The branch/tag/commit to use when the source is a Git repository')
    misc_options.add_argument('--export-features', dest='exportFeatures', metavar='EXPORT_FILE',
                        help='Export identifiers and anatomical terms of labelled features as JSON')
    misc_options.add_argument('--export-neurons', dest='exportNeurons', metavar='EXPORT_FILE',
                        help='Export details of functional connectivity neurons as JSON')
    misc_options.add_argument('--export-svg', dest='exportSVG', metavar='EXPORT_FILE',
                        help='Export Powerpoint sources as SVG')
    misc_options.add_argument('--manifest', metavar='MANIFEST_PATH',
                        help='The relative path of the manifest when the source is a Git repository')
    misc_options.add_argument('--single-file', dest='singleFile', choices=['celldl', 'svg'],
                        help='Source is a single file of the designated type, not a flatmap manifest')

    required = parser.add_argument_group('Required arguments')
    required.add_argument('--output', required=True,
                        help='Base directory for generated flatmaps')
    required.add_argument('--source', required=True,
                        help='''Path of a flatmap manifest or the URL of a Git repository
 containing a manifest. The `--manifest` option is required if the source is a Git repository''')

    return parser

#===============================================================================

def main():
    import sys
    parser = arg_parser()
    args = parser.parse_args()
    try:
        mapmaker = MapMaker({k:v for k, v in vars(args).items() if not (v is None or isinstance(v, bool) and v == False)})
        mapmaker.make()
    except Exception as error:
        msg = str(error)
        log.exception(msg, exc_info=True)
        sys.exit(1)

#===============================================================================

if __name__ == '__main__':
    main()

#===============================================================================
