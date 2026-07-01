#===============================================================================

from mapmaker.sources.svg.rasteriser import SVGRasteriser

#===============================================================================

if __name__ == '__main__':
    import sys
    if len(sys.argv) < 3:
        sys.exit('Usage: {sys.argv[1]} INPUT_SVG_FILE OUTPUT_PNG_FILE')

    with open(sys.argv[1], 'rb') as fp:
        source_svg = fp.read()
    rasteriser = SVGRasteriser(source_svg)
    print('Render size', rasteriser.size)
    rasteriser.render(scaling=100)
    rasteriser.save_image(sys.argv[2])

#===============================================================================
