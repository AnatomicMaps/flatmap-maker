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

from pyparsing import alphanums, nums, printables, Combine, delimitedList, Group, Keyword
from pyparsing import Optional, ParseException, Suppress, Word, ZeroOrMore

#===============================================================================

class Parser(object):
    FREE_TEXT = Word(printables + ' ', excludeChars='()')
    INTEGER = Word(nums)

    ID_TEXT = Word(alphanums, alphanums+':/_-.')

    ONTOLOGY_SUFFIX = (Keyword('FM')
                     | Keyword('FMA')
                     | Keyword('ILX')
                     | Keyword('MA')
                     | Keyword('NCBITaxon')
                     | Keyword('UBERON')
                     )
    ONTOLOGY_ID = Combine(ONTOLOGY_SUFFIX + ':' + ID_TEXT)

    CLASS = Group(Keyword('class') + Suppress('(') + ID_TEXT + Suppress(')'))
    IDENTIFIER = Group(Keyword('id') + Suppress('(') + ID_TEXT + Suppress(')'))
    LABEL = Group(Keyword('label') + Suppress('(') + FREE_TEXT + Suppress(')'))
    LAYER = Group(Keyword('layer') + Suppress('(') + ONTOLOGY_ID + Suppress(')'))
    MODELS = Group(Keyword('models') + Suppress('(') + ONTOLOGY_ID + Suppress(')'))
    STYLE = Group(Keyword('style') + Suppress('(') + INTEGER + Suppress(')'))

    DETAILS = Group(Keyword('details') + Suppress('(') + Suppress(')'))  ## Zoom start, slide/layer ID

    BACKGROUND = Group(Keyword('background-for') + Suppress('(') + IDENTIFIER + Suppress(')'))
    DESCRIPTION = Group(Keyword('description') + Suppress('(') + FREE_TEXT + Suppress(')'))
    SELECTION_FLAGS = Group(Keyword('not-selectable') | Keyword('selected') | Keyword('queryable'))
    ZOOM = Group(Keyword('zoom') + Suppress('(')
                                   + Group(INTEGER + Suppress(',') + INTEGER + Suppress(',') + INTEGER)
                                 + Suppress(')'))

    LAYER_DIRECTIVES = BACKGROUND | DESCRIPTION | IDENTIFIER | MODELS | SELECTION_FLAGS | ZOOM
    LAYER_DIRECTIVE = '.' + ZeroOrMore(LAYER_DIRECTIVES)

    FEATURE_ID = Combine(Suppress('#') + ID_TEXT)
    NEURAL_CLASS = Keyword('N1') | Keyword('N2') | Keyword('N3') | Keyword('N4') | Keyword('N5')
    NODE = Group(Keyword('node') + Suppress('(') + NEURAL_CLASS + Suppress(')'))
    EDGE = Group(Keyword('edge') + Suppress('(') + Group(delimitedList(FEATURE_ID)) + Suppress(')'))
    SHAPE_TYPE = NODE | EDGE

    PROPERTIES = CLASS | IDENTIFIER | STYLE

    ROUTING_TYPE = Keyword('source') | Keyword('target') | Keyword('via')
    ROUTING = Group(ROUTING_TYPE + Suppress('(') + Group(FEATURE_ID | ONTOLOGY_ID) + Suppress(')'))

    SHAPE_FLAGS = Group(Keyword('boundary')
                      | Keyword('children')
                      | Keyword('hole')
                      | Keyword('invisible')
                      | Keyword('open')
                      | Keyword('region'))

    FEATURE_FLAGS = Group(Keyword('group')
                      |   Keyword('organ')
                      )

    SHAPE_MARKUP = '.' + ZeroOrMore(FEATURE_FLAGS | PROPERTIES | ROUTING | SHAPE_FLAGS | SHAPE_TYPE)

    @staticmethod
    def layer_directive(s):
        result = {}
        try:
            parsed = Parser.LAYER_DIRECTIVE.parseString(s, parseAll=True)
            result['selectable'] = True
            for directive in parsed[1:]:
                if directive[0] == 'not-selectable':
                    result['selectable'] = False
                elif Parser.SELECTION_FLAGS.matches(directive[0]):
                    result[directive[0]] = True
                elif directive[0] == 'zoom':
                    result['zoom'] = [int(z) for z in directive[1]]
                else:
                    result[directive[0]] = directive[1]

        except ParseException:
            result['error'] = 'Syntax error in directive'
        return result

    @staticmethod
    def shape_properties(s):
        id = None
        properties = {}
        try:
            parsed = Parser.SHAPE_MARKUP.parseString(s, parseAll=True)
            for prop in parsed[1:]:
                if (Parser.FEATURE_FLAGS.matches(prop[0])
                 or Parser.SHAPE_FLAGS.matches(prop[0])):
                    properties[prop[0]] = True
                else:
                    properties[prop[0]] = prop[1]
        except ParseException:
            properties['error'] = 'Syntax error in directive'
        return properties

    @staticmethod
    def ignore_property(name):
        return Parser.SHAPE_FLAGS.matches(name)

#===============================================================================

if __name__ == '__main__':

    def test(method, text):
        parsed = method(text)
        print('{} --> {}'.format(text, parsed))

    test(Parser.layer_directive, '.id(LAYER) models(NCBITaxon:1)')
    test(Parser.layer_directive, '.selected')
    test(Parser.shape_properties, '.boundary')
    test(Parser.shape_properties, '.id(FEATURE) models(UBERON:1)')
    test(Parser.shape_properties, '.models(FM:1)')
    test(Parser.shape_properties, '.models(FMA:1)')
    test(Parser.shape_properties, '.models(UBERON:1)')
    test(Parser.shape_properties, '.models (N1)')
    test(Parser.shape_properties, '.edge(#n1, #n2)')
    test(Parser.shape_properties, '.source(#n1) via(#n2) target(#n3)')

#===============================================================================
