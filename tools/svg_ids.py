#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2020, 2021  David Brooks
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

from lxml import etree

from mapmaker.properties.markup import parse_markup

#===============================================================================

def SVG_NS(tag):
#===============
    return '{{http://www.w3.org/2000/svg}}{}'.format(tag)

TITLE_TAG = SVG_NS('title')

#===============================================================================

def print_ids(element):
#======================
    if (title := element.find(TITLE_TAG)) is not None:
        if (markup := title.text.strip()).startswith('.'):
            if (id := parse_markup(markup).get('id', '')) != '':
                print(id)
    for child in element:
        if child.tag != TITLE_TAG:
            print_ids(child)

if __name__ == '__main__':
#=========================
    import sys

    if len(sys.argv) < 2:
        sys.exit('Usage: {} SVG_FILE'.format(sys.argv[0]))

    svg = etree.parse(sys.argv[1])

    print_ids(svg.getroot())

#===============================================================================
