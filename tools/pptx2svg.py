#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019 - 2022 David Brooks
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
from urllib.parse import urljoin

#===============================================================================

from mapmaker.sources.powerpoint.pptx2svg import Pptx2Svg

#===============================================================================

__version__ = '1.2.0'

#===============================================================================


## Add --crop option (and --margins) ???

def main():
    import argparse
    from pathlib import Path
    import sys

    parser = argparse.ArgumentParser(description='Convert Powerpoint slides to SVG.')

    parser.add_argument('-v', '--version', action='version', version=__version__)

    #parser.add_argument('-d', '--debug', action='store_true', help='save DrawML to aid with debugging')
    #parser.add_argument('-q', '--quiet', action='store_true', help='do not show progress bar')
    #parser.add_argument('-x', '--export-shapes', action='store_true', help='export closed shapes as JSON')
    #parser.add_argument('--exclude-shapes', metavar='FILENAME', help='previously exported shapes to exclude from SVG')
    #
    # --celldl option?? Pass to Pptx2Svg

    parser.add_argument('--powerpoint', metavar='POWERPOINT_FILE',
                        help='the Powerpoint file to convert')
    parser.add_argument('--map', dest='map_dir', metavar='MAP_DIR',
                        help='directory containing a flatmap manifest specifying sources')

    args = parser.parse_args()

    if args.powerpoint is None and args.map_dir is None:
        sys.exit('A map directory or Powerpoint file must be specified')
    elif args.powerpoint is not None and args.map_dir is not None:
        sys.exit('Cannot specify both a map directory and a Powerpoint file')

    if args.map_dir:
        manifest_file = os.path.join(args.map_dir, 'manifest.json')
        with open(manifest_file, 'rb') as fp:
            manifest = json.loads(fp.read())
        for source in manifest['sources']:
            if source['kind'] == 'slides':
                manifest_path = Path(manifest_file).absolute().as_posix()
                args.powerpoint = urljoin(manifest_path, source['href'])
                break
        if args.powerpoint is None:
            sys.exit('No Powerpoint file specified in manifest')
        args.output_dir = args.map_dir
    else:
        manifest = { 'sources': [] }
        ##args.output_dir = Path(args.powerpoint).parent.as_posix()   ## <<<<<<<<<<<<<<
        args.output_dir = Path('.')

    print(f'Processing {args.powerpoint}...')
    extractor = Pptx2Svg(args.powerpoint)
    extractor.slides_to_svg()
    svg_files = extractor.save_layers(args.output_dir)

    if args.map_dir:
        # Update an existing manifest
        extractor.update_manifest(manifest)
        manifest_temp_file = os.path.join(args.output_dir, 'manifest.temp')
        with open(manifest_temp_file, 'w') as output:
            output.write(json.dumps(manifest, indent=4))
        manifest_file = os.path.join(args.output_dir, 'manifest.json')
        os.rename(manifest_temp_file, manifest_file)
        print(f'Manifest saved as `{manifest_file}`')
    else:
        print(f'Slides saved as {", ".join([name for name in svg_files.values()])}')

#===============================================================================

if __name__ == '__main__':
    main()

#===============================================================================
