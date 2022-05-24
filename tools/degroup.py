#===============================================================================

from datetime import datetime, timezone

#===============================================================================

from lxml import etree

#===============================================================================

__version__ = '1.0.0'


SVG_NS = 'http://www.w3.org/2000/svg'
SVG_GROUP = f'{{{SVG_NS}}}g'

NAMESPACE_MAP = {
    None: 'http://www.w3.org/2000/svg',
    'xlink': 'http://www.w3.org/1999/xlink',
}

#===============================================================================

class DeGrouper(object):
    def __init__(self, svg_file):
        self.__svg_file = svg_file
        self.__svg = etree.parse(svg_file)
        self.__svg_root = self.__svg.getroot()
        self.__output = None

    def degroup(self):
    #=================
        self.__output = self.__process_element(self.__svg_root)

    def save(self):
    #==============
        for comment in self.__svg.xpath('/comment()'):
            self.__output.addprevious(comment)
        header = f' Degrouped at {datetime.now(timezone.utc).isoformat()} '
        self.__output.addprevious(etree.Comment(header))
        degrouped = etree.ElementTree(self.__output)
        degrouped.write(self.__svg_file, encoding='utf-8', pretty_print=True,
                        xml_declaration=True)

    def __process_element(self, element, output=None):
    #=================================================
        if output is None:
            output = etree.Element(element.tag, **element.attrib, nsmap=NAMESPACE_MAP)
        elif element.tag != SVG_GROUP or len(element.attrib) > 0 or len(element) > 1:
            output = etree.SubElement(output, element.tag, **element.attrib)
        for child in element:
            self.__process_element(child, output)
        return output

#===============================================================================

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Remove extraneous nested groups from an SVG file.')
    parser.add_argument('-v', '--version', action='version', version=__version__)
    parser.add_argument('svg_file', metavar='SVG_FILE', help='SVG file to remove nested groups from. The file is overwritten.')

    args = parser.parse_args()
    degrouper = DeGrouper(args.svg_file)
    degrouper.degroup()
    degrouper.save()

#===============================================================================
