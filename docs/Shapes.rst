Processing shapes
-----------------

::

            properties = self.get_properties_(shape)
            if (shape.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE
             or shape.shape_type == MSO_SHAPE_TYPE.FREEFORM
             or isinstance(shape, pptx.shapes.connector.Connector)):
                geometry = self.process_shape(shape, properties, *args)
                feature = Feature(shape.shape_id, geometry, properties)
                features.append(feature)
                self.__features.append(feature)
            elif shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                self.process_group(shape, *args)
            elif (shape.shape_type == MSO_SHAPE_TYPE.TEXT_BOX
               or shape.shape_type == MSO_SHAPE_TYPE.PICTURE):
                pass
            else:
                print('"{}" {} not processed...'.format(shape.name, str(shape.shape_type)))
