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

from mapmaker.annotation import create_annotator

from mapmaker.maker import Manifest

from mapmaker.sources.fc_powerpoint import FCSlide
from mapmaker.sources.powerpoint.powerpoint import Powerpoint

from mapmaker.sources.shapefilter import ShapeFilter

#===============================================================================

class Functional2CellDL:
    def __init__(self, manifest: Manifest):
        self.__manifest = manifest
        self.__shape_filter = ShapeFilter()
        if manifest.annotation is not None:
            self.__annotator = create_annotator(manifest.annotation)
        else:
            self.__annotator = None

    def process(self):
        def kind_order(source):
            kind = source.get('kind', '')
            return ('0' if kind in ['base', 'slides'] else '1') + kind

        have_base = False
        for source in sorted(self.__manifest.sources, key=kind_order):
            kind = source.get('kind')
            if not have_base:
                if kind == 'base':
                    have_base = True
                else:
                    raise ValueError('Missing `base` layer for FC map')
            elif kind == 'base':
                raise ValueError('FC map can only have a single `base` layer')
            id = source.get('id')
            href = source['href']
            if kind in ['base', 'layer']:
                powerpoint = Powerpoint(id, href, kind, shape_filter=self.__shape_filter, SlideClass=FCSlide)
            else:
                raise ValueError('Unsupported FC kind: {}'.format(kind))

            for slide in powerpoint.slides:
                slide.process()
                if self.__annotator is not None:
                    slide.annotate(self.__annotator)

    def save(self):
        # Don't save annotator ??
        pass

#===============================================================================

__version__ = '0.0.1'

#===============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Convert functional connectivity Powerpoint slides to CellDL.')

    parser.add_argument('-v', '--version', action='version', version=__version__)
    parser.add_argument('manifest', metavar='MANIFEST',
                        help='a manifest of a functional connectivity flatmap in Powerpoint')
    args = parser.parse_args()

    manifest = Manifest(args.manifest, ignore_git=True)
    if manifest.kind != 'functional':
        parser.error("Manifest doesn't describe a functional connectivity flatmap")


    fc2celldl = Functional2CellDL(manifest)
    fc2celldl.process()
    fc2celldl.save()

#===============================================================================

if __name__ == '__main__':
    main()

#===============================================================================
