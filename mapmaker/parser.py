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
    IDENTIFIER = Group(Keyword('id') + Suppress('(') + ID_TEXT + Suppress(')'))

    ONTOLOGY_SUFFIX = Keyword('FMA') | Keyword('ILX') | Keyword('NCBITaxon') | Keyword('UBERON')
    ONTOLOGY_ID = Combine(ONTOLOGY_SUFFIX + ':' + ID_TEXT)

    MODELS = Group(Keyword('models') + Suppress('(') + ONTOLOGY_ID + Suppress(')'))

    BACKGROUND = Group(Keyword('background-for') + Suppress('(') + IDENTIFIER + Suppress(')'))
    DESCRIPTION = Group(Keyword('description') + Suppress('(') + FREE_TEXT + Suppress(')'))
    LABEL = Group(Keyword('label') + Suppress('(') + FREE_TEXT + Suppress(')'))
    SELECTION = Group(Keyword('no-selection') | Keyword('selected') | Keyword('queryable'))
    ZOOM = Group(Keyword('zoom') + Suppress('(')
                                   + Group(INTEGER + Suppress(',') + INTEGER + Suppress(',') + INTEGER)
                                 + Suppress(')'))

    LAYER_DIRECTIVES = BACKGROUND | DESCRIPTION | IDENTIFIER | MODELS | SELECTION | ZOOM
    LAYER_DIRECTIVE = '.' + ZeroOrMore(LAYER_DIRECTIVES)


    FEATURE_ID = Combine(Suppress('#') + ID_TEXT)

    NEURAL_CLASS = Keyword('N1') | Keyword('N2') | Keyword('N3') | Keyword('N4') | Keyword('N5')
    NODE = Group(Keyword('node') + Suppress('(') + NEURAL_CLASS + Suppress(')'))

    EDGE = Group(Keyword('edge') + Suppress('(') + Group(delimitedList(FEATURE_ID)) + Suppress(')'))

    FEATURE_TYPE = NODE | EDGE

    ROUTING_TYPE = Keyword('source') | Keyword('target') | Keyword('via')
    ROUTING = Group(ROUTING_TYPE + Suppress('(') + FEATURE_ID + Suppress(')'))

    ## Need to check at least two IDs...
    ## and that they are nodes...
    FEATURE_FLAGS = Group(Keyword('boundary') | Keyword('group') | Keyword('region'))

    FEATURE_PROPERTIES = FEATURE_FLAGS | FEATURE_TYPE | IDENTIFIER  | LABEL | MODELS | ROUTING
    ANNOTATION = '.' + ZeroOrMore(FEATURE_PROPERTIES)

    @staticmethod
    def layer_directive(s):
        result = {}
        try:
            parsed = Parser.LAYER_DIRECTIVE.parseString(s, parseAll=True)
            result['selectable'] = True
            for directive in parsed[1:]:
                if directive[0] in ['background-for',
                                    'description',
                                    'id',
                                    'models']:
                    result[directive[0]] = directive[1]
                elif directive[0] == 'not-selectable':
                    result['selectable'] = False
                elif directive[0] == 'selected':
                    result['selected'] = True
                elif directive[0] == 'queryable-nodes':
                    result['queryable-nodes'] = True
                elif directive[0] == 'zoom':
                    result['zoom'] = [int(z) for z in directive[1]]

        except ParseException:
            result['error'] = 'Syntax error in directive'
        return result

    @staticmethod
    def annotation(s):
        id = None
        properties = {}
        try:
            parsed = Parser.ANNOTATION.parseString(s, parseAll=True)
            for prop in parsed[1:]:
                if prop[0] == 'boundary':
                    properties['boundary'] = True
                elif prop[0] == 'group':
                    properties['group'] = True
                elif prop[0] == 'region':
                    properties['region'] = True
                else:
                    properties[prop[0]] = prop[1]
        except ParseException:
            properties['error'] = 'Syntax error in directive'
        return properties

#===============================================================================

if __name__ == '__main__':

    def test(method, text):
        parsed = method(text)
        print('{} --> {}'.format(text, parsed))

    test(Parser.layer_directive, '.id(LAYER) models(NCBITaxon:1)')
    test(Parser.layer_directive, '.selected')
    test(Parser.annotation, '.boundary')
    test(Parser.annotation, '.id(FEATURE) models(UBERON:1)')
    test(Parser.annotation, '.models(UBERON:1)')
    test(Parser.annotation, '.edge(#n1, #n2)')

#===============================================================================
