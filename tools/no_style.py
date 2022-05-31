#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019 - 2022  David Brooks
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

from dataclasses import dataclass
from pathlib import Path
import os

#===============================================================================

from lxml import etree

#===============================================================================

from mapmaker.sources.markup import parse_markup, properties_to_markup
from mapmaker.sources.svg.utils import adobe_decode, adobe_encode
from mapmaker.utils import FilePath, relative_path

#===============================================================================

class PathError(Exception):
    pass

#===============================================================================

@dataclass
class Element:
    element: etree.Element
    properties: dict

#===============================================================================

class StyleRemover:
    def __init__(self, manifest_path, output_dir):
        self.__manifest_file = FilePath(manifest_path)
        self.__manifest = self.__manifest_file.get_json()
        self.__svg_sources = []
        for source in self.__manifest.get('sources', []):
            if source.get('kind') in ['base', 'details']:
                if not relative_path(source['href']):
                    raise PathError('Paths to SVG files must be relative.')
                self.__svg_sources.append(source['href'])
        self.__output_dir = Path(output_dir)

    def __process_svg(self, svg_file):
    #=================================
        svg = etree.parse(FilePath(self.__manifest_file.join_url(svg_file)).get_fp())
        elements = []
        for xml_element in svg.findall('//*[@id]'):
            # Don't rewrite IDs of gradient elements
            if xml_element.tag in ['radialGradient', 'linearGradient']:
                continue
            markup = adobe_decode(xml_element.attrib['id'])
            if markup.startswith('.'):
                properties = parse_markup(markup)
                if 'style' in properties:
                    properties.pop('style')
                    xml_element.attrib['id'] = adobe_encode(properties_to_markup(properties))
        # Save the updated SVG
        svg.write(str(self.__output_dir.joinpath(svg_file)), xml_declaration=True, encoding='utf-8')

    def process_svg_files(self):
    #===========================
        for svg_file in self.__svg_sources:
            self.__process_svg(svg_file)


#===============================================================================

def remove_style(manifest_path, output_dir):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    style_remover = StyleRemover(manifest_path, output_dir)
    style_remover.process_svg_files()

#===============================================================================

def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Remove `style` markup from flatmap's SVG sources")
    parser.add_argument('manifest', metavar='MANIFEST', help='Path of flatmap manifest')
    parser.add_argument('output_dir', metavar='OUTPUT_DIR', help='Directory to save converted SVGs in')

    try:
        args = parser.parse_args()
        remove_style(args.manifest, args.output_dir)
    except PathError as error:
        sys.stderr.write(f'{error}\n')
        sys.exit(1)
    sys.exit(0)

#===============================================================================

if __name__ == '__main__':
    main()

#===============================================================================
