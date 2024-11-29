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

from pyparsing import alphanums, nums, printables
from pyparsing import Combine, delimitedList, Group, Keyword
from pyparsing import Optional, Suppress, Word, ZeroOrMore
from pyparsing import ParseException, ParseResults

#===============================================================================

from mapmaker.settings import settings

#===============================================================================

FREE_TEXT = Word(printables + ' ', excludeChars='()')
INTEGER = Word(nums)

ID_TEXT = Word(alphanums, alphanums+':/_-.')

ONTOLOGY_SUFFIX = (Keyword('ABI')
                 | Keyword('FM')
                 | Keyword('FMA')
                 | Keyword('ILX')
                 | Keyword('MA')
                 | Keyword('NCBITaxon')
                 | Keyword('UBERON')
                 )
ONTOLOGY_ID = Combine(ONTOLOGY_SUFFIX + ':' + ID_TEXT)

#===============================================================================

IDENTIFIER = Group(Keyword('id') + Suppress('(') + ID_TEXT + Suppress(')'))
MODELS = Group(Keyword('models') + Suppress('(') + ONTOLOGY_ID + Suppress(')'))

ZOOM_LEVEL = INTEGER
ZOOM = Group(Keyword('zoom') + Suppress('(')
                               + Group(ZOOM_LEVEL + Suppress(',') + ZOOM_LEVEL + Suppress(',') + ZOOM_LEVEL)
                             + Suppress(')'))

LAYER_DIRECTIVES = IDENTIFIER | MODELS | ZOOM
LAYER_DIRECTIVE = '.' + ZeroOrMore(LAYER_DIRECTIVES)

#===============================================================================

#    LAYER = Group(Keyword('layer') + Suppress('(') + ONTOLOGY_ID + Suppress(')'))
## WIP: DETAILS = Group(Keyword('details') + Suppress('(') + Suppress(')'))  ## Zoom start, slide/layer ID
## Details are positioned within polygon's boundary on a layer "above" the polygon's
## fill layer. Say positioned on an invisible place holder that is grouped with the polygon??

CLASS = Group(Keyword('class') + Suppress('(') + ID_TEXT + Suppress(')'))
CHILDCLASSES = Group(Keyword('children') + Suppress('(') + ID_TEXT + Suppress(')'))
DETAILS = Group(Keyword('details') + Suppress('(') + ID_TEXT + Suppress(',') + ZOOM_LEVEL + Suppress(')'))
PATH = Group(Keyword('path') + Suppress('(') + ID_TEXT + Suppress(')'))
STYLE = Group(Keyword('style') + Suppress('(') + INTEGER + Suppress(')'))

NAME = Group(Keyword('name') + Suppress('(') + FREE_TEXT + Suppress(')'))

FEATURE_PROPERTIES = CLASS | CHILDCLASSES | IDENTIFIER | NAME | STYLE

SHAPE_FLAGS = Group(Keyword('boundary')
                  | Keyword('closed')
                  | Keyword('exterior')
                  | Keyword('interior')
                  )

FEATURE_FLAGS = Group(Keyword('centreline')
                    | Keyword('divider')
                    | Keyword('group')
                    | Keyword('invisible')
                    | Keyword('marker')
                    | Keyword('node')
                    | Keyword('region')
                    | Keyword('siblings')
                    | Keyword('styling')       # Element (and sub-elements) are just for stylistic effects
                  )

SHAPE_MARKUP = '.' + ZeroOrMore(DETAILS
                              | FEATURE_FLAGS
                              | FEATURE_PROPERTIES
                              | PATH
                              | SHAPE_FLAGS)

#===============================================================================

DEPRECATED_MARKUP = [
    'marker',
    'siblings',
    'style'
]

#===============================================================================

def parse_layer_directive(s):
    result = {}
    try:
        parsed = LAYER_DIRECTIVE.parseString(s, parseAll=True)
        for directive in parsed[1:]:
            if directive[0] == 'zoom':
                result['zoom'] = [int(z) for z in directive[1]]
            else:
                result[directive[0]] = directive[1]
    except ParseException:
        result['error'] = 'Syntax error in layer directive'
    return result

#===============================================================================

def parse_markup(markup):
    properties = {'markup': markup}
    deprecated = []
    try:
        parsed = SHAPE_MARKUP.parseString(markup, parseAll=True)
        for prop in parsed[1:]:
            if prop[0] in DEPRECATED_MARKUP:
                deprecated.append(prop[0])
            if (FEATURE_FLAGS.matches(prop[0])
             or SHAPE_FLAGS.matches(prop[0])):
                properties[prop[0]] = True
            elif prop[0] == 'details':
                properties[prop[0]] = prop[1]
                properties['maxzoom'] = int(prop[2]) - 1
            else:
                properties[prop[0]] = prop[1]
    except ParseException:
        properties['error'] = 'Syntax error'
        if settings.get('debug', False):
            raise
    if len(deprecated):
        properties['warning'] = f"Deprecated `{', '.join(deprecated)}`"
    if ('styling' in properties
    and ('id' in properties or 'class' in properties)):
        properties['error'] = "'styling' element can't have an 'id' nor 'class'"
    return properties

#===============================================================================

def properties_to_markup(properties):
    markup_elements = []
    details = {}
    for key, value in properties.items():
        if (FEATURE_FLAGS.matches(key)
         or SHAPE_FLAGS.matches(key)):
            if value:
                markup_elements.append(key)
        elif key in ['details', 'maxzoom']:
            details[key] = value
        elif key not in ['error', 'markup', 'warning']:
            markup_elements.append(f'{key}({value})')
    if len(details) == 2:
        markup_elements.append(f'details({details["details"]}, {details["maxzoom"] + 1})')
    markup = '.' + ' '.join(markup_elements)
    properties = {'markup': markup}
    return markup

#===============================================================================

if __name__ == '__main__':

    def test(method, text):
        parsed = method(text)
        print('{} --> {}'.format(text, parsed))

    test(parse_layer_directive, '.id(LAYER) models(NCBITaxon:1)')
    test(parse_layer_directive, '.selected')

    test(parse_markup, '.boundary')
    test(parse_markup, '.id(ID) class(FEATURE)')
    test(parse_markup, '.models(FM:1)')
    test(parse_markup, '.models(FMA:1)')
    test(parse_markup, '.models(UBERON:1)')
    test(parse_markup, '.models (N1)')

    test(parse_markup, '.path(P1, P2, P3, P4, P5, P6, P7, P8)')
    test(parse_markup, '.route(urinary_5, keast_2, S50_L6_B, S50_L6_T, S45_L6, C1, S44_L6)')
    test(parse_markup, '.route(urinary_5, keast_2, S50_L6_B, S50_L6_T, S45_L6, C1, S44_L6, (S42_L6, S38_L6, S37_L6, S34_L6, S33_L6, S42_L6))')
    test(parse_markup, '.path(P1, P2, P3, P4, P5, P6, P7, P8) route (urinary_5, keast_2, S50_L6_B, S50_L6_T, S45_L6, C1, S44_L6, (S42_L6, S38_L6, S37_L6, S34_L6, S33_L6, S42_L6))')

#===============================================================================
