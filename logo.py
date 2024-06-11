from PIL import Image

def logo(webcam_file, logo_file, name, logo_place, logo_size):
    # Open the images
    logo = Image.open(logo_file)
    webcam = Image.open(webcam_file)

    # Resize logo
    logo = logo.resize(logo_size)

    # Create a copy of image
    webcam_and_logo = webcam.copy()

    # Paste logo onto cam at the specified location
    webcam_and_logo.paste(logo, logo_place, logo)

    path = f'images/{name}_logo.jpg'

    webcam_and_logo.save(path)
    return path
