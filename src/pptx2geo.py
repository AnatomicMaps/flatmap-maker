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

from drawml import GeoJsonExtractor, SvgExtractor

#===============================================================================

if __name__ == '__main__':
    import argparse
    import os

    parser = argparse.ArgumentParser(description='Extract geometries from Powerpoint slides.')
    parser.add_argument('--debug-xml', action='store_true',
                        help="save a slide's DrawML for debugging")
    parser.add_argument('--format', choices=['geojson', 'svg'], default='geojson',
                        help='output format (default `geojson`)')
    parser.add_argument('--slide', type=int, metavar='N',
                        help='only process this slide number (1-origin)')
    parser.add_argument('--version', action='version', version='0.2.1')
    parser.add_argument('output_dir', metavar='OUTPUT_DIRECTORY',
                        help='directory in which to save geometries')
    parser.add_argument('powerpoint', metavar='POWERPOINT_FILE',
                        help='the name of a Powerpoint file')

    ## specify range of slides...
    ## specify format

    args = parser.parse_args()

    if not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)

    if   args.format == 'geojson':
        extractor = GeoJsonExtractor(args.powerpoint, args)
    elif args.format == 'svg':
        extractor = SvgExtractor(args.powerpoint, args)

    extractor.slides_to_geometry(args.slide)

#===============================================================================
