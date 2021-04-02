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

#    LABEL = Group(Keyword('label') + Suppress('(') + FREE_TEXT + Suppress(')'))
#    LAYER = Group(Keyword('layer') + Suppress('(') + ONTOLOGY_ID + Suppress(')'))
## WIP: DETAILS = Group(Keyword('details') + Suppress('(') + Suppress(')'))  ## Zoom start, slide/layer ID
## Details are positioned within polygon's boundary on a layer "above" the polygon's
## fill layer. Say positioned on an invisible place holder that is grouped with the polygon??

CLASS = Group(Keyword('class') + Suppress('(') + ID_TEXT + Suppress(')'))
CHILDCLASSES = Group(Keyword('children') + Suppress('(') + ID_TEXT + Suppress(')'))
DETAILS = Group(Keyword('details') + Suppress('(') + ID_TEXT + Suppress(',') + ZOOM_LEVEL + Suppress(')'))
PATH = Group(Keyword('path') + Suppress('(') + ID_TEXT + Suppress(')'))

# Deprecated...
STYLE = Group(Keyword('style') + Suppress('(') + INTEGER + Suppress(')'))

FEATURE_PROPERTIES = CLASS | CHILDCLASSES | IDENTIFIER | STYLE

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
    try:
        parsed = SHAPE_MARKUP.parseString(markup, parseAll=True)
        deprecated = []
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
        properties['error'] = 'Syntax error in element markup'
    if len(deprecated):
        properties['warning'] = "Deprecated '{}'".format("', '".join(deprecated))
    if ('styling' in properties
    and ('id' in properties or 'class' in properties)):
        properties['error'] = "A 'styling' element can't have an 'id' nor 'class' property"
    return properties

#===============================================================================

def ignore_property(name):
    return SHAPE_FLAGS.matches(name) or name in DEPRECATED_MARKUP

#===============================================================================

if __name__ == '__main__':

    def test(method, text):
        parsed = method(text)
        print('{} --> {}'.format(text, parsed))

    test(Parser.layer_directive, '.id(LAYER) models(NCBITaxon:1)')
    test(Parser.layer_directive, '.selected')
    test(Parser.shape_properties, '.boundary')
    test(Parser.shape_properties, '.id(ID) class(FEATURE)')
    test(Parser.shape_properties, '.models(FM:1)')
    test(Parser.shape_properties, '.models(FMA:1)')
    test(Parser.shape_properties, '.models(UBERON:1)')
    test(Parser.shape_properties, '.models (N1)')

    test(Parser.shape_properties, '.path(P1, P2, P3, P4, P5, P6, P7, P8)')
    test(Parser.shape_properties, '.route(urinary_5, keast_2, S50_L6_B, S50_L6_T, S45_L6, C1, S44_L6)')
    test(Parser.shape_properties, '.route(urinary_5, keast_2, S50_L6_B, S50_L6_T, S45_L6, C1, S44_L6, (S42_L6, S38_L6, S37_L6, S34_L6, S33_L6, S42_L6))')
    test(Parser.shape_properties, '.path(P1, P2, P3, P4, P5, P6, P7, P8) route (urinary_5, keast_2, S50_L6_B, S50_L6_T, S45_L6, C1, S44_L6, (S42_L6, S38_L6, S37_L6, S34_L6, S33_L6, S42_L6))')

#===============================================================================
