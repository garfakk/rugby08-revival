from PIL import Image
import struct
from typing import List, Dict, Optional

from shared.log import get_logger

log = get_logger(__name__)


class FSHFile:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.shapes = []
        self.header = {}
        self._read_header()

    def _read_header(self):
        with open(self.file_path, 'rb') as file:
            # Read the header information
            file_type = file.read(4).decode('ascii')
            file_length = struct.unpack('I', file.read(4))[0]
            num_shapes = struct.unpack('I', file.read(4))[0]
            version = file.read(4).decode('ascii')

            self.header = {
                'file_type': file_type,
                'file_length': file_length,
                'num_shapes': num_shapes,
                'version': version
            }

            # Read shape tags and offsets
            self.shapes = []
            for _ in range(num_shapes):
                tag = file.read(4).decode('ascii')
                offset = struct.unpack('I', file.read(4))[0]
                self.shapes.append({'tag': tag, 'offset': offset})

    def list_contents(self) -> List[Dict]:
        """List the contents of the FSH file."""
        return self.shapes

    def extract_data(self, shape_index: int) -> Optional[bytes]:
        """Extract sections for a given shape from the FSH file."""
        if shape_index >= len(self.shapes):
            return None

        sections = {}

        with open(self.file_path, 'rb') as file:
            shape = self.shapes[shape_index]
            file.seek(shape['offset'])

            for section_index in range(3):
              # Read section headers to determine the size of the image data
              #section_type, is_compressed, next_section_offset = struct.unpack('B3sI', file.read(8))
              #section_type = (section_type & 0x7F)  # Extract section type

              temp_byte = file.read(1)
              section_type = temp_byte[0] & 0xFE
              is_compressed = temp_byte[0] & 0x01 
              next_section_offset = int.from_bytes(file.read(3), byteorder='little', signed=False)

              # Calculate the size of the current section
              current_position = file.tell()
              section_size = next_section_offset - 8  # Subtract the header size

              log.debug(f"Section type: {section_type}")
              log.debug(f"Next section offset: {next_section_offset}")
              log.debug(f"Is compressed: {is_compressed}")
              log.debug(f"Section size: {section_size}")
              
              if section_type in [0x62, 0x7C]:
              
                bytes = file.read(12)
                
                log.debug(bytes[0:2])
                
                image_data = {
                  "width": int.from_bytes(bytes[0:2], byteorder='little', signed=False),
                  "height": int.from_bytes(bytes[2:4], byteorder='little', signed=False),
                  "center_x": int.from_bytes(bytes[4:6], byteorder='little', signed=False),
                  "center_y": int.from_bytes(bytes[6:8], byteorder='little', signed=False),
                  "left_X": 0, # Not implemented
                  "is_referenced": 0, # Not implemented
                  "is_swizzled": 0, # Not implemented
                  "is_transposed": 0, # Not implemented
                  "reserved": 0, # Not implemented
                  "top_Y": 0, # Not implemented
                  "levels_count": bytes[11] & 0x0F,
                  "pixels": file.read(section_size - 8),
                }
                
                
                return image_data

    def import_image(self, shape_index: int, image_data: bytes) -> bool:
        """Import an image into the FSH file."""
        if shape_index >= len(self.shapes):
            return False

        with open(self.file_path, 'r+b') as file:
            shape = self.shapes[shape_index]
            file.seek(shape['offset'])

            # Write the image data
            file.write(image_data)
            return True

    def create_image_from_data(self, image_data: Dict) -> Optional[Image.Image]:
        """Create an image from the extracted pixel data."""
        if not image_data or 'pixels' not in image_data:
            return None

        width = image_data['width']
        height = image_data['height']
        pixels = image_data['pixels']

        try:
            # Assuming the pixel data is in a format compatible with mode 'RGBA'
            image = Image.frombytes('RGBA', (width, height), pixels)
            return image
        except Exception as e:
            log.error(f"Error creating image: {e}")
            return None

# Example usage
if __name__ == "__main__":
    fsh = FSHFile('example.fsh')
    log.debug("Contents of the FSH file:")
    for shape in fsh.list_contents():
        log.debug(shape)

    image_data = fsh.extract_data(0)
    if image_data:
        log.debug({k: image_data[k] for k in image_data.keys() - {'pixels'}})
        log.debug(f"Pixels number: {len(image_data['pixels'])}")
        image = fsh.create_image_from_data(image_data)
        if image:
            log.debug("show")
            image.show()  # This will display the image
            image.save('output.png')  # Save the image to a file

    # Example of importing new image data
    new_image_data = b'NEW_IMAGE_DATA'  # Replace with actual image data
#    fsh.import_image(0, new_image_data)
